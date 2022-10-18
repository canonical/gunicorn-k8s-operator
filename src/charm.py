#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import ops
import pgsql
import yaml
from charms.data_platform_libs.v0.database_requires import DatabaseRequires
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.nginx_ingress_integrator.v0.ingress import IngressRequires
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from jinja2 import BaseLoader, Environment, meta
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

logger = logging.getLogger(__name__)

REQUIRED_JUJU_CONFIG = ["external_hostname"]
JUJU_CONFIG_YAML_DICT_ITEMS = ["environment"]


class GunicornK8sCharm(CharmBase):
    _stored = StoredState()
    _log_path = "/var/log/gunicorn.log"

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.gunicorn_pebble_ready, self._on_gunicorn_pebble_ready)

        # Provide ability for Gunicorn to be scraped by Prometheus using prometheus_scrape
        self._metrics_endpoint = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": ["*:80"]}]}],
        )

        # Enable log forwarding for Loki and other charms that implement loki_push_api
        self._logging = LogProxyConsumer(
            self, relation_name="logging", log_files=[self._log_path], container_name="gunicorn"
        )

        # Provide grafana dashboards over a relation interface
        self._grafana_dashboards = GrafanaDashboardProvider(
            self, relation_name="grafana-dashboard"
        )
        self.mongodb = DatabaseRequires(
            self, relation_name="mongodb_client", database_name=self.app.name
        )
        # The `database_created` event is fired whenever a new unit is added to
        # this application, even if the database has already been created
        # (because a previous unit requested it). Responding to the following
        # two events means we don't need to handle `relation-changed` or
        # `relation-joined` events.
        self.framework.observe(
            self.mongodb.on.database_created, self._mongodb_client_relation_changed
        )
        self.framework.observe(
            self.mongodb.on.endpoints_changed, self._mongodb_client_relation_changed
        )

        self.ingress = IngressRequires(
            self,
            {
                "service-hostname": self.config["external_hostname"],
                "service-name": self.app.name,
                "service-port": self.config["external_port"],
            },
        )

        self._stored.set_default(
            reldata={},
        )

        self._init_postgresql_relation()

    def _mongodb_client_relation_changed(self, event: ops.framework.EventBase) -> None:
        """Handle changes to the MongoDB relation."""
        if "mongodb" not in self._stored.reldata:
            self._stored.reldata["mongodb"] = {}

        initial = dict(self._stored.reldata["mongodb"])
        self._stored.reldata["mongodb"].update(
            self.mongodb.fetch_relation_data()[event.relation.id]
        )
        if initial != self._stored.reldata["mongodb"]:
            self._configure_workload(event)

    def _get_gunicorn_pebble_config(self, event: ops.framework.EventBase) -> dict:
        """Generate gunicorn's container pebble config."""
        port = self.config["external_port"]
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
                    "http": {"url": f"http://127.0.0.1:{port}"},
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
            self.unit.status = BlockedStatus("Error getting pod_env_config")
            return {}
        elif type(pod_env_config) is set:
            self.unit.status = BlockedStatus(
                "Waiting for {} relation(s)".format(", ".join(sorted(pod_env_config)))
            )
            event.defer()
            return {}

        if pod_env_config:
            pebble_config["services"]["gunicorn"]["environment"] = pod_env_config
        return pebble_config

    def _get_statsd_pebble_config(self, event: ops.framework.EventBase) -> dict:
        """Generate statsd exporter pebble config."""
        pebble_config = {
            "summary": "statsd exporter layer",
            "description": "statsd exporter layer",
            "services": {
                "statsd-prometheus-exporter": {
                    "override": "replace",
                    "summary": "statsd exporter service",
                    "user": "nobody",
                    "command": "/bin/statsd_exporter",
                    "startup": "enabled",
                }
            },
            "checks": {
                "container-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": "http://localhost:9102/metrics"},
                },
            },
        }

        return pebble_config

    def _on_config_changed(self, event: ops.framework.EventBase) -> None:
        """Handle the config changed event."""

        self._configure_workload(event)

    def _on_gunicorn_pebble_ready(self, event: ops.framework.EventBase) -> None:
        """Handle the workload ready event."""

        self._configure_workload(event)

    def _configure_workload(self, event: ops.charm.EventBase) -> None:
        """Configure the workload container."""
        gunicorn_pebble_config = self._get_gunicorn_pebble_config(event)
        if not gunicorn_pebble_config:
            # Charm will be in blocked status.
            return
        statsd_pebble_config = self._get_statsd_pebble_config(event)
        juju_conf = self._check_juju_config()
        if juju_conf:
            self.unit.status = BlockedStatus(str(juju_conf))
            return {}

        # Ensure the ingress relation has the external hostname.
        self.ingress.update_config(
            {
                "service-hostname": self.config["external_hostname"],
                "service-port": self.config["external_port"],
            }
        )

        gunicorn_container = self.unit.get_container("gunicorn")
        statsd_container = self.unit.get_container("statsd-prometheus-exporter")
        # pebble may not be ready, in which case we just return
        if not gunicorn_container.can_connect() or not statsd_container.can_connect():
            self.unit.status = MaintenanceStatus("waiting for pebble to start")
            logger.debug("waiting for pebble to start")
            return

        logger.debug(
            "About to add_layer with pebble_config: %s", yaml.dump(gunicorn_pebble_config)
        )
        gunicorn_container.add_layer("gunicorn", gunicorn_pebble_config, combine=True)
        gunicorn_container.pebble.replan_services()
        statsd_container.add_layer(
            "statsd-prometheus-exporter", statsd_pebble_config, combine=True
        )
        statsd_container.pebble.replan_services()

        self.unit.status = ActiveStatus()

    def _init_postgresql_relation(self) -> None:
        """Initialization related to the postgresql relation"""
        if "pg" not in self._stored.reldata:
            self._stored.reldata["pg"] = {}
        self.pg = pgsql.PostgreSQLClient(self, "pg")
        self.framework.observe(
            self.pg.on.database_relation_joined, self._on_database_relation_joined
        )
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

        self._stored.reldata["pg"]["conn_str"] = (
            None if event.master is None else event.master.conn_str
        )
        self._stored.reldata["pg"]["db_uri"] = None if event.master is None else event.master.uri

        if event.master is None:
            return

        self._on_config_changed(event)

    def _on_standby_changed(self, event: pgsql.StandbyChangedEvent) -> None:
        """Handle changes in the secondary database unit(s)."""
        if event.database != self.app.name:
            # Leader has not yet set requirements. Wait until next
            # event, or risk connecting to an incorrect database.
            return

        self._stored.reldata["pg"]["ro_uris"] = [c.uri for c in event.standbys]

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
                        " using only the first one (id: %s) for relation data.",
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
                            "using only the first one (id: %s) for relation data.",
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
        env = self.model.config["environment"]

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
