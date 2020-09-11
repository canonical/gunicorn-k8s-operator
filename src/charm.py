#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

from jinja2 import Environment, BaseLoader, meta
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
import pgsql


logger = logging.getLogger(__name__)

REQUIRED_JUJU_CONFIG = ['image_path', 'external_hostname']
JUJU_CONFIG_YAML_DICT_ITEMS = ['environment']


class GunicornK8sCharmJujuConfigError(Exception):
    """Exception when the Juju config is bad."""

    pass


class GunicornK8sCharmYAMLError(Exception):
    """Exception raised when parsing YAML fails"""

    pass


class GunicornK8sCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.start, self._configure_pod)
        self.framework.observe(self.on.config_changed, self._configure_pod)
        self.framework.observe(self.on.leader_elected, self._configure_pod)
        self.framework.observe(self.on.upgrade_charm, self._configure_pod)

        # For special-cased relations
        self._stored.set_default(reldata={})

        self._init_postgresql_relation()

    def _init_postgresql_relation(self) -> None:
        """Initialization related to the postgresql relation"""
        self._stored.reldata['pg'] = {}
        self.pg = pgsql.PostgreSQLClient(self, 'pg')
        self.framework.observe(self.pg.on.database_relation_joined, self._on_database_relation_joined)
        self.framework.observe(self.pg.on.master_changed, self._on_master_changed)
        self.framework.observe(self.pg.on.standby_changed, self._on_standby_changed)

    def _on_database_relation_joined(self, event: pgsql.DatabaseRelationJoinedEvent) -> None:
        """Handle db-relation-joined."""
        if self.model.unit.is_leader():
            # Provide requirements to the PostgreSQL server.
            event.database = self.app.name  # Request database named like the Juju app
        elif event.database != self.app.name:
            # Leader has not yet set requirements. Defer, in case this unit
            # becomes leader and needs to perform that operation.
            event.defer()

    def _on_master_changed(self, event: pgsql.MasterChangedEvent) -> None:
        """Handle changes in the primary database unit."""
        if event.database != self.app.name:
            # Leader has not yet set requirements. Wait until next
            # event, or risk connecting to an incorrect database.
            return

        self._stored.reldata['pg']['conn_str'] = None if event.master is None else event.master.conn_str
        self._stored.reldata['pg']['db_uri'] = None if event.master is None else event.master.uri

        if event.master is None:
            return

        self._configure_pod(event)

    def _on_standby_changed(self, event: pgsql.StandbyChangedEvent) -> None:
        """Handle changes in the secondary database unit(s)."""
        if event.database != self.app.name:
            # Leader has not yet set requirements. Wait until next
            # event, or risk connecting to an incorrect database.
            return

        self._stored.reldata['pg']['ro_uris'] = [c.uri for c in event.standbys]

        # TODO: Emit event when we add support for read replicas

    def _check_juju_config(self) -> None:
        """Check if all the required Juju config options are set,
        and if all the Juju config options are properly formatted

        :raises GunicornK8sCharmJujuConfigError: if a required config is not set
        """

        # Verify required items
        errors = []
        for required in REQUIRED_JUJU_CONFIG:
            if not self.model.config[required]:
                logger.error("Required Juju config item not set : %s", required)
                errors.append(required)
        if errors:
            raise GunicornK8sCharmJujuConfigError(
                "Required Juju config item(s) not set : {}".format(", ".join(sorted(errors)))
            )

    def _make_k8s_ingress(self) -> list:
        """Return an ingress that you can use in k8s_resources

        :returns: A list to be used as k8s ingress
        """

        hostname = self.model.config['external_hostname']

        ingress = {
            "name": "{}-ingress".format(self.app.name),
            "spec": {
                "rules": [
                    {
                        "host": hostname,
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "backend": {"serviceName": self.app.name, "servicePort": 80},
                                }
                            ]
                        },
                    }
                ]
            },
            "annotations": {
                'nginx.ingress.kubernetes.io/ssl-redirect': 'false',
            },
        }

        return [ingress]

    def _render_template(self, tmpl: str, ctx: dict) -> str:
        """Render a Jinja2 template

        :returns: A rendered Jinja2 template
        """
        j2env = Environment(loader=BaseLoader())
        j2template = j2env.from_string(tmpl)

        return j2template.render(**ctx)

    def _get_context_from_relations(self) -> dict:
        """Build a template context from relation data - to be used for Jinja2
        template rendering

        :returns: A dict with relation data that can be used as context for Jinja2 template rendering
        """
        ctx = {}

        # Add variables from "special" relations
        for rel in self._stored.reldata:
            if self._stored.reldata[rel]:
                ctx[str(rel)] = self._stored.reldata[rel]

        # Add variables from raw relation data
        for rel in self.model.relations:
            r = self.model.relations[rel]  # TODO handle multiple relations ?
            if len(r) > 0:
                r = r[0]
                if len(r.units) > 0:
                    u = next(iter(r.units))
                    if r.name not in ctx:  # can be present from the "special" relations above
                        ctx[r.name] = {}
                    for k, v in r.data[u].items():
                        ctx[r.name][k] = v

        return ctx

    def _validate_yaml(self, supposed_yaml: str, expected_type: type) -> None:
        """Validate that the supplied YAML is parsed into the supplied type.

        :raises GunicornK8sCharmYAMLError: if the YAML is incorrect, or if it's not parsed into the expected type
        """
        err = False
        parsed = None

        try:
            parsed = yaml.safe_load(supposed_yaml)
        except yaml.scanner.ScannerError as e:
            logger.error("Error when parsing the following YAML : %s : %s", supposed_yaml, str(e))
            err = True
        else:
            if not isinstance(parsed, expected_type):
                err = True
                logger.error(
                    "Expected type '%s' but got '%s' when parsing YAML : %s",
                    expected_type,
                    parsed.__class__,
                    supposed_yaml,
                )

        if err:
            raise GunicornK8sCharmYAMLError("YAML parsing failed, please check \"juju debug-log -l ERROR\"")

    def _make_pod_env(self) -> dict:
        """Return an envConfig with some core configuration.

        :returns: A dictionary used for envConfig in podspec
        """
        env = self.model.config['environment']

        if not env:
            return {}

        ctx = self._get_context_from_relations()
        rendered_env = self._render_template(env, ctx)

        try:
            self._validate_yaml(rendered_env, dict)
        except GunicornK8sCharmYAMLError:
            raise GunicornK8sCharmJujuConfigError(
                "Could not parse Juju config 'environment' as a YAML dict - check \"juju debug-log -l ERROR\""
            )

        env = yaml.safe_load(rendered_env)

        return env

    def _make_pod_spec(self) -> dict:
        """Return a pod spec with some core configuration.

        :returns: A pod spec
        """

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
                    'kubernetes': {
                        'readinessProbe': {'httpGet': {'path': '/', 'port': 80}},
                    },
                }
            ],
        }

    def _configure_pod(self, event: ops.framework.EventBase) -> None:
        """Assemble the pod spec and apply it, if possible.

        :param event: Event that triggered the method.
        """

        env = self.model.config['environment']
        ctx = self._get_context_from_relations()

        if env:
            j2env = Environment(loader=BaseLoader)
            j2template = j2env.parse(env)
            missing_vars = set()

            for req_var in meta.find_undeclared_variables(j2template):
                if not ctx.get(req_var):
                    missing_vars.add(req_var)

            if missing_vars:
                logger.info(
                    "Missing YAML vars to interpolate the 'environment' config option, "
                    "setting status to 'waiting' : %s",
                    ", ".join(sorted(missing_vars)),
                )
                self.unit.status = BlockedStatus('Waiting for {} relation'.format(", ".join(sorted(missing_vars))))
                event.defer()
                return

        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        try:
            self._check_juju_config()
        except GunicornK8sCharmJujuConfigError as e:
            self.unit.status = BlockedStatus(str(e))
            return

        self.unit.status = MaintenanceStatus('Assembling pod spec')

        try:
            pod_spec = self._make_pod_spec()
        except GunicornK8sCharmJujuConfigError as e:
            self.unit.status = BlockedStatus(str(e))
            return

        resources = pod_spec.get('kubernetesResources', {})
        resources['ingressResources'] = self._make_k8s_ingress()

        self.unit.status = MaintenanceStatus('Setting pod spec')
        self.model.pod.set_spec(pod_spec, k8s_resources={'kubernetesResources': resources})
        logger.info("Setting active status")
        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: no cover
    main(GunicornK8sCharm, use_juju_for_storage=True)
