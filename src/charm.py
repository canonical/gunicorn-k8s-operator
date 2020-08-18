#!/usr/bin/env python3
# Copyright 2020 Ubuntu
# See LICENSE file for licensing details.

import logging

import ops
from ops.framework import StoredState
from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
)


logger = logging.getLogger(__name__)

REQUIRED_JUJU_CONFIG = ['image_path']


class GunicornK8sCharmJujuConfigError(Exception):
    """Exception when the Juju config is bad."""

    pass


class GunicornK8sCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.start, self.configure_pod)
        self.framework.observe(self.on.config_changed, self.configure_pod)
        self.framework.observe(self.on.leader_elected, self.configure_pod)
        self.framework.observe(self.on.upgrade_charm, self.configure_pod)

        self._stored.set_default(things=[])

    def _check_juju_config(self) -> None:
        """Check if all the required Juju config options are set

        :raises GunicornK8sCharmJujuConfigError: if a required config is not set
        """
        errors = []
        for required in REQUIRED_JUJU_CONFIG:
            if required not in self.model.config:
                logger.error("Required Juju config not set : %s", required)
                errors.append(required)
        if errors:
            raise GunicornK8sCharmJujuConfigError(
                "Required Juju config not set : {0}".format(", ".join(sorted(errors)))
            )

    def _update_pod_spec_for_k8s_ingress(self, pod_spec: dict) -> None:
        """Add resources to pod_spec configuring site ingress, if needed.

        :param dict pod_spec: pod spec v3 as defined by juju.
        """

        ingress = {
            "name": "{}-ingress".format(self.app.name),
            "spec": {
                "rules": [
                    {
                        "host": "example.com",
                        "http": {
                            "paths": [{"path": "/", "backend": {"serviceName": self.app.name, "servicePort": 80},}]
                        },
                    }
                ]
            },
            "annotations": {'nginx.ingress.kubernetes.io/ssl-redirect': 'false',},
        }

        # Due to https://github.com/canonical/operator/issues/293 we
        # can't use pod.set_spec's k8s_resources argument.
        resources = pod_spec.get('kubernetesResources', {})
        resources['ingressResources'] = [ingress]
        pod_spec['kubernetesResources'] = resources

    def _make_pod_config(self) -> dict:
        """Return an envConfig with some core configuration.

        :returns: A dictionary used for envConfig in podspec
        :rtype: dict
        """
        pod_config = {}

        return pod_config

    def _make_pod_spec(self) -> dict:
        """Return a pod spec with some core configuration."""

        config = self.model.config
        image_details = {
            'imagePath': config['image_path'],
        }
        if config.get('image_username', None):
            image_details.update({'username': config['image_username'], 'password': config['image_password']})
        pod_config = self._make_pod_config()

        return {
            'version': 3,  # otherwise resources are ignored
            'containers': [
                {
                    'name': self.app.name,
                    'imageDetails': image_details,
                    # TODO: debatable. The idea is that if you want to force an update with the same image name, you
                    # don't need to empty kubelet cache on each node to have the right version.
                    # This implies a performance drop upon start.
                    'imagePullPolicy': 'Always',
                    'ports': [{'containerPort': 80, 'protocol': 'TCP'}],
                    'envConfig': pod_config,
                    'kubernetes': {'readinessProbe': {'httpGet': {'path': '/', 'port': 80}},},
                }
            ],
        }

    def configure_pod(self, event: ops.framework.EventBase) -> None:
        """Assemble the pod spec and apply it, if possible.

        :param ops.framework.EventBase event: Event that triggered the method.
        """

        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        try:
            self._check_juju_config()
        except GunicornK8sCharmJujuConfigError as e:
            self.unit.status = BlockedStatus(str(e))
            return

        self.unit.status = MaintenanceStatus('Assembling pod spec')
        pod_spec = self._make_pod_spec()
        self._update_pod_spec_for_k8s_ingress(pod_spec)

        self.unit.status = MaintenanceStatus('Setting pod spec')
        self.model.pod.set_spec(pod_spec)
        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(GunicornK8sCharm, use_juju_for_storage=True)
