#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
# Since there are several cases of this mypy error and we cannot stop using
# what mypy considers to be overloaded functions, the index check on mypy must be ignored.
# mypy: disable-error-code=index
# pylint: disable=fixme

"""Charm for Gunicorn on kubernetes."""
import json
import logging
import textwrap
import typing
from collections.abc import MutableMapping
from typing import Union

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

JUJU_CONFIG_YAML_DICT_ITEMS = ["environment"]


class GunicornK8sCharm(CharmBase):
    """Charm for Gunicorn on kubernetes."""

    _stored = StoredState()
    _log_path = "/var/log/gunicorn.log"

    def __init__(self, *args):
        """Construct.

        Args:
            args: Variable list of positional arguments passed to the parent constructor.
        """
        super().__init__(*args)

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.gunicorn_pebble_ready, self._on_pebble_ready)
        self.framework.observe(
            self.on.show_environment_context_action, self._on_show_environment_context_action
        )

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
                "service-hostname": self._get_external_hostname(),
                "service-name": self.app.name,
                "service-port": self.config["external_port"],
            },
        )

        self._stored.set_default(
            reldata={},
        )

        self._init_postgresql_relation()

    def _mongodb_client_relation_changed(self, event: ops.framework.EventBase) -> None:
        """Handle changes to the MongoDB relation.

        Args:
            event: Event triggering this handler.
        """
        # mypy does not recognize the operand type
        if "mongodb" not in self._stored.reldata:  # type: ignore[operator]
            self._stored.reldata["mongodb"] = {}

        initial = dict(self._stored.reldata["mongodb"])
        self._stored.reldata["mongodb"].update(
            # Ignore the attr-defined error since we cannot modify the MongoDB class here
            self.mongodb.fetch_relation_data()[event.relation.id]  # type: ignore[attr-defined]
        )
        if initial != self._stored.reldata["mongodb"]:
            self._configure_workload(event)

    def _get_external_hostname(self) -> str:
        """Retrieve the hostname according to the config option.

        If empty, default to the app name.

        Returns:
            The assigned hostname.
        """
        hostname = typing.cast(str, self.config["external_hostname"])
        if hostname == "":
            hostname = self.app.name
        return hostname

    def _get_gunicorn_pebble_config(self, event: ops.framework.EventBase) -> ops.pebble.LayerDict:
        """Generate gunicorn's container pebble config.

        Args:
            event: Event triggering this handler.

        Returns:
            Gunicorn container's pebble config
        """
        port = self.config["external_port"]
        # We use similar fields in the unit test, disable pylint warning.
        # pylint: disable=R0801
        pebble_config = {
            "summary": "gunicorn layer",
            "description": "gunicorn layer",
            "services": {
                "gunicorn": {
                    "override": "replace",
                    "summary": "gunicorn service",
                    "command": self.config["startup_command"],
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
        # pylint: enable=R0801

        # Update pod environment config.
        pod_env_config = self._make_pod_env()
        if isinstance(pod_env_config, bool):
            logger.error(
                "Error getting pod_env_config: %s",
                "Could not parse Juju config 'environment' as a YAML dict - check "
                '"juju debug-log -l ERROR"',
            )
            self.unit.status = BlockedStatus("Error getting pod_env_config")
            return {}
        if isinstance(pod_env_config, set):
            self.unit.status = BlockedStatus(
                f"Waiting for {', '.join(sorted(pod_env_config))} relation(s)"
            )
            event.defer()
            return {}

        if pod_env_config:
            pebble_config["services"]["gunicorn"]["environment"] = pod_env_config
        return typing.cast(ops.pebble.LayerDict, pebble_config)

    def _on_config_changed(self, event: ops.framework.EventBase) -> None:
        """Handle the config changed event.

        Args:
            event: Event triggering this handler.
        """
        self._configure_workload(event)

    def _on_pebble_ready(self, event: ops.framework.EventBase) -> None:
        """Handle the workload ready event.

        Args:
            event: Event triggering this handler.
        """
        self._configure_workload(event)

    def _on_show_environment_context_action(self, event: ops.charm.ActionEvent) -> None:
        """Handle event for show-environment-context action.

        Args:
            event: Event triggering this handler.
        """
        logger.info("Action show-environment-context launched")
        ctx = self._get_context_from_relations()
        #  mypy ignores the cast to list
        ctx = list(self._flatten_dict(ctx).keys())  # type: ignore[assignment]
        ctx.sort()  # type: ignore[attr-defined]

        event.set_results({"available-variables": json.dumps(ctx, indent=4)})

    def _get_statsd_pebble_config(self) -> ops.pebble.LayerDict:
        """Handle the workload ready event.

        Returns:
            The statsd layer pebble configuration.
        """
        layer = {
            "summary": "Statsd prometheus exporter",
            "description": "Prometheus exporter for statsd",
            "services": {
                "statsd-exporter": {
                    "override": "replace",
                    "summary": "Statsd Exporter",
                    "command": ("statsd_exporter --statsd.mapping-config=/statsd.conf"),
                    "startup": "enabled",
                },
            },
            "checks": {
                "statsd-exporter-up": {
                    "override": "replace",
                    "level": "alive",
                    "http": {"url": "http://localhost:9102/metrics"},
                },
            },
        }
        return typing.cast(ops.pebble.LayerDict, layer)

    def _configure_workload(self, event: ops.charm.EventBase) -> None:
        """Configure the workload container.

        Args:
            event: Event triggering this handler.
        """
        gunicorn_pebble_config = self._get_gunicorn_pebble_config(event)
        statsd_pebble_config = self._get_statsd_pebble_config()
        if not gunicorn_pebble_config:
            # Charm will be in blocked status.
            return

        # Ensure the ingress relation has the external hostname.
        self.ingress.update_config(
            {
                "service-hostname": self._get_external_hostname(),
                "service-port": self.config["external_port"],
            }
        )

        gunicorn_container = self.unit.get_container("gunicorn")
        # pebble may not be ready, in which case we just return
        if not gunicorn_container.can_connect():
            self.unit.status = MaintenanceStatus("waiting for pebble to start")
            logger.debug("waiting for pebble to start")
            return
        gunicorn_container.push(
            "/statsd.conf",
            textwrap.dedent(
                """\
                mappings:
                  - match: gunicorn.request.status.*
                    name: gunicorn_response_code
                    labels:
                      status: $1
                """
            ),
        )
        logger.debug(
            "About to add_layer with pebble_config: %s", yaml.dump(gunicorn_pebble_config)
        )
        gunicorn_container.add_layer("gunicorn", gunicorn_pebble_config, combine=True)
        gunicorn_container.add_layer(
            "statsd-prometheus-exporter", statsd_pebble_config, combine=True
        )
        try:
            gunicorn_container.pebble.replan_services()
        except ops.pebble.ChangeError:
            self.unit.status = BlockedStatus(
                "Charm's startup command may be wrong, please check the config"
            )
            return

        self.unit.status = ActiveStatus()

    def _init_postgresql_relation(self) -> None:
        """Initialize related to the postgresql relation."""
        # mypy does not recognize the operand type
        if "pg" not in self._stored.reldata:  # type: ignore[operator]
            # pylint conflicts with "pg" but the name of the interface can't be changed.
            self._stored.reldata["pg"] = {}  # pylint: disable=invalid-name
        self.pg = pgsql.PostgreSQLClient(self, "pg")  # pylint: disable=invalid-name
        self.framework.observe(
            self.pg.on.database_relation_joined, self._on_database_relation_joined
        )
        self.framework.observe(self.pg.on.master_changed, self._on_master_changed)
        self.framework.observe(self.pg.on.standby_changed, self._on_standby_changed)

    def _on_database_relation_joined(self, event: pgsql.DatabaseRelationJoinedEvent) -> None:
        """Handle db-relation-joined.

        Args:
            event: Event triggering this handler.
        """
        if self.model.unit.is_leader():
            # Provide requirements to the PostgreSQL server.
            event.database = self.app.name  # Request database named like the Juju app
        elif event.database != self.app.name:
            # Leader has not yet set requirements. Defer, in case this unit
            # becomes leader and needs to perform that operation.
            event.defer()

    def _on_master_changed(self, event: pgsql.MasterChangedEvent) -> None:
        """Handle changes in the primary database unit.

        Args:
            event: Event triggering this handler.
        """
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
        """Handle changes in the secondary database unit(s).

        Args:
            event: Event triggering this handler.
        """
        if event.database != self.app.name:
            # Leader has not yet set requirements. Wait until next
            # event, or risk connecting to an incorrect database.
            return

        self._stored.reldata["pg"]["ro_uris"] = [c.uri for c in event.standbys]

        # TODO: Emit event when we add support for read replicas

    def _render_template(self, tmpl: str, ctx: dict) -> str:
        """Render a Jinja2 template.

        Args:
            tmpl: Jinja2 template.
            ctx: Context to render.

        Returns:
            A rendered Jinja2 template.
        """
        j2env = Environment(loader=BaseLoader(), autoescape=True)
        j2template = j2env.from_string(tmpl)

        return j2template.render(**ctx)

    def _get_context_from_relations(self) -> dict:
        """Build a template context from relation data. Used for Jinja2 template rendering.

        Returns:
            A dict with relation data that can be used as context for Jinja2 template rendering.
        """
        ctx = {}

        # Add variables from "special" relations
        for rel in self._stored.reldata:  # type: ignore[index, attr-defined]
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
                    unit = sorted(rel.units, key=lambda x: x.name)[0]

                    if len(rel.units) > 1:
                        logger.warning(
                            'Multiple units detected in the relation "%s:%s", '
                            "using only the first one (id: %s) for relation data.",
                            rel.name,
                            rel.id,
                            unit.name,
                        )
                    if rel.name not in ctx:  # can be present from the "special" relations above
                        ctx[rel.name] = {}
                    for key, value in rel.data[unit].items():
                        ctx[rel.name][key] = value

        return ctx

    def _validate_yaml(self, yaml_content: str, expected_type: type) -> Union[bool, None]:
        """Validate that the supplied YAML is parsed into the supplied type.

        Args:
            yaml_content: Yaml content to validate.
            expected_type: Expected yaml type.

        Returns:
            An error if the yaml is incorrect.
        """
        err = False
        parsed = None

        try:
            parsed = yaml.safe_load(yaml_content)
        except yaml.scanner.ScannerError as error:
            logger.error("Error when parsing the following YAML : %s : %s", yaml_content, error)
            err = True
        else:
            if not isinstance(parsed, expected_type):
                err = True
                logger.error(
                    "Expected type '%s' but got '%s' when parsing YAML : %s",
                    expected_type,
                    parsed.__class__,
                    yaml_content,
                )

        if err:
            return err

        return None

    def _make_pod_env(self) -> Union[dict, bool, set, str]:
        """Return an envConfig with some core configuration.

        Returns:
            A dictionary used for envConfig in podspec.
        """
        env = typing.cast(str, self.model.config["environment"])

        if not env:
            return {}

        ctx = self._get_context_from_relations()

        # Using BaseLoader without Optional[] throws a mypy error, we'll ignore it.
        j2env = Environment(loader=BaseLoader, autoescape=True)  # type: ignore[arg-type]
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

    def _flatten_dict_gen(self, dict_to_flatten, parent_key, sep):
        """Flatten a dictionary.

        Args:
            dict_to_flatten: Dictionary to flatten.
            parent_key: Parent key from the dict.
            sep: Key separator.

        Yields:
            Flattened key-value pairs.
        """
        for key, value in dict_to_flatten.items():
            new_key = parent_key + sep + key if parent_key else key
            if isinstance(value, MutableMapping):
                yield from self._flatten_dict(value, new_key, sep=sep).items()
            else:
                yield new_key, value

    def _flatten_dict(self, dict_to_flatten: MutableMapping, parent_key: str = "", sep: str = "."):
        """Flatten a dictionary.

        Args:
            dict_to_flatten: Dictionary to flatten.
            parent_key: Parent key from the dict.
            sep: Key separator.

        Returns:
            A flattened dict.
        """
        return dict(self._flatten_dict_gen(dict_to_flatten, parent_key, sep))


if __name__ == "__main__":  # pragma: no cover
    main(GunicornK8sCharm, use_juju_for_storage=True)
