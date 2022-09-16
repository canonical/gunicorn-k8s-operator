#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

from jinja2 import Environment, BaseLoader, meta
import logging
import yaml

from charms.data_platform_libs.v0.database_requires import (
    DatabaseCreatedEvent,
    DatabaseRequires,
)
from charms.nginx_ingress_integrator.v0.ingress import IngressRequires
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

REQUIRED_JUJU_CONFIG = ['external_hostname']
JUJU_CONFIG_YAML_DICT_ITEMS = ['environment']
CONTAINER_NAME = yaml.full_load(open('metadata.yaml', 'r')).get('name').replace("-k8s", "")


class GunicornK8sCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.gunicorn_pebble_ready, self._on_gunicorn_pebble_ready)

        self.mongodb = DatabaseRequires(self, relation_name="mongodb-client", database_name=self.app.name)
        self.framework.observe(self.mongodb.on.database_created, self._on_mongodb_created)

        self.ingress = IngressRequires(
            self,
            {
                "service-hostname": self.config["external_hostname"],
                "service-name": self.app.name,
                "service-port": 80,
            },
        )

        self._stored.set_default(
            reldata={},
        )

        self._init_postgresql_relation()

        self.framework.observe(self.on["peer"].relation_changed, self._on_peer_relation_changed)
        self.framework.observe(self.on["peer"].relation_joined, self._on_peer_relation_changed)

    def _on_peer_relation_changed(self, event: ops.framework.EventBase) -> None:
        """Handle the peer relation changed event."""
        # Get data for our MongoDB relation if a DB has been created.
        if "mongodb-database" in event.relation.data[self.app]:
            if "mongodb" not in self._stored.reldata:
                self._stored.reldata["mongodb"] = {}
            self._stored.reldata["mongodb"].update(
                {
                    "database": event.relation.data[self.app]["mongodb-database"],
                    "username": event.relation.data[self.app]["mongodb-username"],
                    "password": event.relation.data[self.app]["mongodb-password"],
                    "endpoints": event.relation.data[self.app]["mongodb-endpoints"],
                }
            )
        else:
            # Remove any data related to MongoDB.
            self._stored.reldata.pop("mongodb-database", None)
            self._stored.reldata.pop("mongodb-username", None)
            self._stored.reldata.pop("mongodb-password", None)
            self._stored.reldata.pop("mongodb-endpoints", None)
        self._configure_workload(event)

    def _on_mongodb_created(self, event: DatabaseCreatedEvent) -> None:
        """Handle the on MongoDB created event."""
        if self.model.unit.is_leader():
            # Add data to peer relation if it doesn't exist there. We can only
            # store string data in the relation itself.
            peer_relation = self.model.get_relation("peer")
            peer_relation.data[self.app]["mongodb-database"] = self.app.name
            peer_relation.data[self.app]["mongodb-username"] = event.username
            peer_relation.data[self.app]["mongodb-password"] = event.password
            peer_relation.data[self.app]["mongodb-endpoints"] = event.endpoints

    def _get_pebble_config(self, event: ops.framework.EventBase) -> dict:
        """Generate pebble config."""
        pebble_config = {
            "summary": "gunicorn layer",
            "description": "gunicorn layer",
            "services": {
                "gunicorn": {
                    "override": "replace",
                    "summary": "gunicorn service",
                    "command": "/srv/gunicorn/run",
                    "startup": "enabled",
                }
            },
            "checks": {
                "gunicorn-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": "http://127.0.0.1:80"},
                },
            },
        }

        # Update pod environment config.
        pod_env_config = self._make_pod_env()
        if type(pod_env_config) is bool:
            logger.error(
                "Error getting pod_env_config: %s",
                "Could not parse Juju config 'environment' as a YAML dict - check \"juju debug-log -l ERROR\"",
            )
            self.unit.status = BlockedStatus('Error getting pod_env_config')
            return {}
        elif type(pod_env_config) is set:
            self.unit.status = BlockedStatus('Waiting for {} relation(s)'.format(", ".join(sorted(pod_env_config))))
            event.defer()
            return {}

        juju_conf = self._check_juju_config()
        if juju_conf:
            self.unit.status = BlockedStatus(str(juju_conf))
            return {}

        if pod_env_config:
            pebble_config["services"]["gunicorn"]["environment"] = pod_env_config
        return pebble_config

    def _on_config_changed(self, event: ops.framework.EventBase) -> None:
        """Handle the config changed event."""

        self._configure_workload(event)

    def _on_gunicorn_pebble_ready(self, event: ops.framework.EventBase) -> None:
        """Handle the workload ready event."""

        self._configure_workload(event)

    def _configure_workload(self, event: ops.charm.EventBase) -> None:
        """Configure the workload container."""
        pebble_config = self._get_pebble_config(event)
        if not pebble_config:
            # Charm will be in blocked status.
            return

        # Ensure the ingress relation has the external hostname.
        self.ingress.update_config({"service-hostname": self.config["external_hostname"]})

        container = self.unit.get_container(CONTAINER_NAME)
        # pebble may not be ready, in which case we just return
        if not container.can_connect():
            self.unit.status = MaintenanceStatus('waiting for pebble to start')
            logger.debug('waiting for pebble to start')
            return

        logger.debug("About to add_layer with pebble_config:\n{}".format(yaml.dump(pebble_config)))
        container.add_layer(CONTAINER_NAME, pebble_config, combine=True)
        container.pebble.replan_services()

        self.unit.status = ActiveStatus()

    def _init_postgresql_relation(self) -> None:
        """Initialization related to the postgresql relation"""
        if 'pg' not in self._stored.reldata:
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

        self._on_config_changed(event)

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
        """

        # Verify required items
        errors = []
        for required in REQUIRED_JUJU_CONFIG:
            if not self.model.config[required]:
                logger.error("Required Juju config item not set : %s", required)
                errors.append(required)
        if errors:
            return "Required Juju config item(s) not set : {}".format(", ".join(sorted(errors)))

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
        for rels in self.model.relations.values():
            if len(rels) > 0:
                rel = rels[0]

                if len(rels) > 1:
                    logger.warning(
                        'Multiple relations of type "%s" detected,'
                        ' using only the first one (id: %s) for relation data.',
                        rel.name,
                        rel.id,
                    )

                if len(rel.units) > 0:
                    # We want to always pick the same unit, so sort the set
                    # before picking the first one.
                    u = sorted(rel.units, key=lambda x: x.name)[0]

                    if len(rel.units) > 1:
                        logger.warning(
                            'Multiple units detected in the relation "%s:%s", '
                            'using only the first one (id: %s) for relation data.',
                            rel.name,
                            rel.id,
                            u.name,
                        )
                    if rel.name not in ctx:  # can be present from the "special" relations above
                        ctx[rel.name] = {}
                    for k, v in rel.data[u].items():
                        ctx[rel.name][k] = v

        return ctx

    def _validate_yaml(self, supposed_yaml: str, expected_type: type) -> None:
        """Validate that the supplied YAML is parsed into the supplied type."""
        err = False
        parsed = None

        try:
            parsed = yaml.safe_load(supposed_yaml)
        except yaml.scanner.ScannerError as e:
            logger.error("Error when parsing the following YAML : %s : %s", supposed_yaml, e)
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
            return err

    def _make_pod_env(self) -> dict:
        """Return an envConfig with some core configuration.

        :returns: A dictionary used for envConfig in podspec
        """
        env = self.model.config['environment']

        if not env:
            return {}

        ctx = self._get_context_from_relations()

        j2env = Environment(loader=BaseLoader)
        j2template = j2env.parse(env)
        missing_vars = set()

        for req_var in meta.find_undeclared_variables(j2template):
            if not ctx.get(req_var):
                missing_vars.add(req_var)

        if missing_vars:
            return missing_vars

        rendered_env = self._render_template(env, ctx)

        yaml_val = self._validate_yaml(rendered_env, dict)
        if yaml_val:
            return yaml_val

        env = yaml.safe_load(rendered_env)

        return env


if __name__ == "__main__":  # pragma: no cover
    main(GunicornK8sCharm, use_juju_for_storage=True)
