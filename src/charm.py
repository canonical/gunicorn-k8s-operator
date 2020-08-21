#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import yaml

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
JUJU_CONFIG_YAML_DICT_ITEMS = ['environment']


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
        """Check if all the required Juju config options are set,
        and if all the Juju config options are properly formatted

        :raises GunicornK8sCharmJujuConfigError: if a required config is not set
        """

        # Verify required items
        errors = []
        for required in REQUIRED_JUJU_CONFIG:
            if required not in self.model.config or not self.model.config[required]:
                logger.error("Required Juju config item not set : %s", required)
                errors.append(required)
        if errors:
            raise GunicornK8sCharmJujuConfigError(
                "Required Juju config item not set : {0}".format(", ".join(sorted(errors)))
            )

        # Verify YAML formatting
        errors = []
        for item in JUJU_CONFIG_YAML_DICT_ITEMS:
            supposed_yaml = self.model.config[item]

            parsed = None

            try:
                parsed = yaml.safe_load(supposed_yaml)
            except yaml.scanner.ScannerError as e:
                errors.append(item)
                logger.error("Juju config item '%s' is not YAML : %s", item, str(e))

            if parsed and not isinstance(parsed, dict):
                errors.append(item)
                logger.error("Juju config item '%s' is not a YAML dict", item)

        if errors:
            raise GunicornK8sCharmJujuConfigError(
                "YAML parsing failed on the Juju config item(s) : {0} - check \"juju debug-log -l ERROR\"".format(
                    ", ".join(sorted(errors))
                )
            )

    def _make_k8s_ingress(self) -> list:
        """Return an ingress that you can use in k8s_resources
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

        return [ingress]

    def _make_pod_env(self) -> dict:
        """Return an envConfig with some core configuration.

        :returns: A dictionary used for envConfig in podspec
        :rtype: dict
        """
        env = yaml.safe_load(self.model.config['environment'])

        return env or {}

    def _make_pod_spec(self) -> dict:
        """Return a pod spec with some core configuration."""

        config = self.model.config
        image_details = {
            'imagePath': config['image_path'],
        }
        if config.get('image_username', None):
            image_details.update({'username': config['image_username'], 'password': config['image_password']})
        pod_env = self._make_pod_env()

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
                    'envConfig': pod_env,
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

        resources = pod_spec.get('kubernetesResources', {})
        resources['ingressResources'] = self._make_k8s_ingress()

        self.unit.status = MaintenanceStatus('Setting pod spec')
        self.model.pod.set_spec(pod_spec, k8s_resources={'kubernetesResources': resources})
        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: no cover
    main(GunicornK8sCharm, use_juju_for_storage=True)
