#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
# pylint: disable=protected-access

"""Test for the gunicorn charm."""

import unittest
from unittest.mock import MagicMock, patch

from ops import pebble, testing
from ops.model import ActiveStatus, BlockedStatus
from scenario import (  # pylint: disable=import-error
    JUJU_DEFAULT_CONFIG,
    TEST_PG_CONNSTR,
    TEST_PG_URI,
    TEST_RENDER_TEMPLATE,
)

from charm import GunicornK8sCharm


class TestGunicornK8sCharm(unittest.TestCase):  # pylint: disable=too-many-public-methods
    """Class for charm testing.

    Attrs:
        maxDiff: Full diff when there is an error.
    """

    maxDiff = None

    def setUp(self):
        """Setup the harness object."""
        self.harness = testing.Harness(GunicornK8sCharm)
        self.harness.begin()
        self.harness.add_oci_resource("gunicorn-image")

    def tearDown(self):
        """Cleanup the harness."""
        self.harness.cleanup()

    def test_init_postgresql_relation(self):
        """
        arrange: given the deployed charm
        act: initiate the postgresql relation
        assert: the relation data has the correct values
        """
        # We'll only test the case where _stored already
        # has content. _stored being empty is basically tested
        # by all the other functions
        with patch("charm.GunicornK8sCharm.__init__") as mock_init, patch(
            "test_charm.GunicornK8sCharm._stored"
        ) as mock_stored, patch("pgsql.PostgreSQLClient"), patch("test_charm.GunicornK8sCharm.on"):
            mock_stored.reldata = {"pg": "foo"}
            mock_init.return_value = None
            charm = GunicornK8sCharm(MagicMock())
            self.assertEqual(charm._stored.reldata, mock_stored.reldata)

    def test_on_database_relation_joined_unit_is_leader(self):
        """
        arrange: given the deployed charm
        act: handle the database relation joined event
        assert: the event is handled successfully
        """
        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(True)

        self.harness.charm._on_database_relation_joined(mock_event)

        self.assertEqual(mock_event.database, self.harness.charm.app.name)

    def test_on_database_relation_joined_unit_is_not_leader(self):
        """
        arrange: given the deployed charm
        act: handle the database relation joined event
        assert: the event is handled successfully
        """
        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(False)

        self.harness.charm._on_database_relation_joined(mock_event)

        mock_event.defer.assert_called_once()

        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(False)
        mock_event.database = self.harness.charm.app.name

        result = self.harness.charm._on_database_relation_joined(mock_event)
        self.assertEqual(result, None)

    def test_on_master_changed(self):
        """
        arrange: given the deployed charm
        act: execute on_master_changed with no database,
            with database but no master and
            with database that has a master.
        assert: the relation data is displayed with the correct values.
        """
        # No database
        mock_event = MagicMock()
        mock_event.database = None

        result = self.harness.charm._on_master_changed(mock_event)
        self.assertEqual(result, None)

        # Database but no master
        mock_event = MagicMock()
        mock_event.database = self.harness.charm.app.name
        mock_event.master = None

        result = self.harness.charm._on_master_changed(mock_event)
        reldata = self.harness.charm._stored.reldata
        self.assertEqual(reldata["pg"]["conn_str"], None)
        self.assertEqual(reldata["pg"]["db_uri"], None)
        self.assertEqual(result, None)

        # Database with master
        mock_event = MagicMock()
        mock_event.database = self.harness.charm.app.name
        mock_event.master.conn_str = TEST_PG_CONNSTR
        mock_event.master.uri = TEST_PG_URI
        with patch("charm.GunicornK8sCharm._on_config_changed") as on_config_changes:
            result = self.harness.charm._on_master_changed(mock_event)

            reldata = self.harness.charm._stored.reldata
            self.assertEqual(reldata["pg"]["conn_str"], mock_event.master.conn_str)
            self.assertEqual(reldata["pg"]["db_uri"], mock_event.master.uri)
            self.assertEqual(result, None)
            on_config_changes.assert_called_with(mock_event)

    def test_on_standby_changed_database_not_ready(self):
        """
        arrange: given the deployed charm
        act: execute on_standby_changed
        assert: there is no database
        """
        mock_event = MagicMock()
        mock_event.database = None

        result = self.harness.charm._on_standby_changed(mock_event)
        self.assertEqual(result, None)

    def test_on_standby_changed_database_ready(self):
        """
        arrange: given the deployed charm with a postgreSQL db
            in standby ready
        act: execute on_standby_changed
        assert: the database is now in the reldata
        """
        mock_event = MagicMock()
        mock_event.database = self.harness.charm.app.name

        mock_event.standbys = [MagicMock()]
        mock_event.standbys[0].uri = TEST_PG_URI

        self.harness.charm._on_standby_changed(mock_event)

        reldata = self.harness.charm._stored.reldata
        self.assertEqual(reldata["pg"]["ro_uris"], [TEST_PG_URI])

    def test_on_mongodb_client_relation_changed(self):
        """
        arrange: given the deployed charm
        act: mock a MongoDB object and call it
        assert: the object is referenced correctly in the reldata
        """

        class FakeMongoDB:  # pylint: disable=too-few-public-methods
            """Mock a MongoDB object."""

            def fetch_relation_data(self):
                """Fetch the relation data from MongoDB.

                Returns:
                    Relation data to mock a MongoDB relation.
                """
                return {
                    1: {
                        "database": "gunicorn-k8s",
                        "username": "someusername",
                        "password": "somepassword",
                        "endpoints": "someendpoint",
                    }
                }

        self.harness.charm.mongodb = FakeMongoDB()

        # Test nothing in StoredState related to MongoDB.
        self.assertEqual(self.harness.charm._stored.reldata, {"pg": {}})
        expected_data = {
            "mongodb": {
                "database": "gunicorn-k8s",
                "username": "someusername",
                "password": "somepassword",
                "endpoints": "someendpoint",
            },
            "pg": {},
        }
        mock_event = MagicMock()
        mock_event.relation.id = 1
        with patch("test_charm.GunicornK8sCharm._configure_workload") as mock_configure_workload:
            self.harness.charm._mongodb_client_relation_changed(mock_event)
            # Confirm we're configuring the workload because state has changed.
            mock_configure_workload.assert_called_once()
            self.assertEqual(self.harness.charm._stored.reldata, expected_data)

            # And now test it again to confirm what happens if mongodb is already
            # in StoredState.
            self.harness.charm._mongodb_client_relation_changed(mock_event)
            # Confirm configure workload has still only been called once, as
            # StoredState related to MongoDB hasn't changed.
            mock_configure_workload.assert_called_once()
            self.assertEqual(self.harness.charm._stored.reldata, expected_data)

    def test_render_template(self):
        """
        arrange: given a template
        act: render the template
        assert: the template is rendered successfully
        """
        for scenario, values in TEST_RENDER_TEMPLATE.items():
            with self.subTest(scenario=scenario):
                result = self.harness.charm._render_template(values["tmpl"], values["ctx"])
                self.assertEqual(result, values["expected"])

    def test_get_context_from_relations(self):
        """
        arrange: given the deployed charm with relations
        act: execute _get_content_from relations
        assert: the output and logs are correct
        """
        self.harness.disable_hooks()  # no need for hooks to fire for this test

        # Set up PG "special case" relation data
        reldata = self.harness.charm._stored.reldata
        reldata["pg"] = {"conn_str": TEST_PG_CONNSTR, "db_uri": TEST_PG_URI}

        # Set up PG "raw" relation data
        relation_id = self.harness.add_relation("pg", "postgresql")
        self.harness.add_relation_unit(relation_id, "postgresql/0")
        self.harness.update_relation_data(relation_id, "postgresql/0", {"version": "10"})

        # Set up random relation, with 2 units
        relation_id = self.harness.add_relation("myrel", "myapp")
        self.harness.add_relation_unit(relation_id, "myapp/0")
        self.harness.add_relation_unit(relation_id, "myapp/1")
        self.harness.update_relation_data(relation_id, "myapp/0", {"thing": "bli"})
        self.harness.update_relation_data(relation_id, "myapp/1", {"thing": "blo"})

        # Set up same relation but with a different app
        relation_id = self.harness.add_relation("myrel", "myapp2")
        self.harness.add_relation_unit(relation_id, "myapp2/0")
        self.harness.update_relation_data(relation_id, "myapp2/0", {"thing": "blu"})

        # Set up random relation, no unit (can happen during relation init)
        relation_id = self.harness.add_relation("myrel2", "myapp2")

        expected_ret = {
            "pg": {"conn_str": TEST_PG_CONNSTR, "db_uri": TEST_PG_URI, "version": "10"},
            "myrel": {"thing": "bli"},
        }
        expected_logger = [
            'WARNING:charm:Multiple relations of type "myrel" detected, '
            "using only the first one (id: 1) for relation data.",
            'WARNING:charm:Multiple units detected in the relation "myrel:1", '
            "using only the first one (id: myapp/0) for relation data.",
        ]

        with self.assertLogs(level="WARNING") as logger:
            result = self.harness.charm._get_context_from_relations()

        self.assertEqual(sorted(logger.output), sorted(expected_logger))
        self.assertEqual(result, expected_ret)

    def test_validate_yaml_proper_type_proper_yaml(self):
        """
        arrange: given a correct yaml
        act: execute _validate_yaml
        assert: the method is successfully executed
        """
        test_str = "a: b\n1: 2"
        expected_type = dict

        result = self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(result, None)

    def test_validate_yaml_incorrect_yaml(self):
        """
        arrange: given an incorrect yaml
        act: execute _validate_yaml
        assert: the error displayed is correct
        """
        test_str = "a: :"
        expected_type = dict
        expected_output = [
            "ERROR:charm:Error when parsing the following YAML : a: : : mapping values "
            "are not allowed here\n"
            '  in "<unicode string>", line 1, column 4:\n'
            "    a: :\n"
            "       ^"
        ]

        with self.assertLogs(level="ERROR") as logger:
            self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(sorted(logger.output), expected_output)

    def test_validate_yaml_incorrect_type_proper_yaml(self):
        """
        arrange: given an improper yaml
        act: execute _validate_yaml
        assert: the error displayed is correct
        """
        test_str = "a: b"
        expected_type = str
        expected_output = [
            "ERROR:charm:Expected type '<class 'str'>' but got '<class 'dict'>' when "
            "parsing YAML : a: b"
        ]

        with self.assertLogs(level="ERROR") as logger:
            self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(sorted(logger.output), expected_output)

    def test_get_external_hostname_not_empty(self):
        """
        arrange: given the deployed charm
        act: set the external hostname to a value
        assert: the external hostname has the set value
        """
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({"external_hostname": "123"})
        expected_ret = "123"

        result = self.harness.charm._get_external_hostname()
        self.assertEqual(result, expected_ret)

    def test_get_external_hostname_empty(self):
        """
        arrange: given the deployed charm
        act: set the external hostname to empty
        assert: the external hostname has the default value
        """
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({"external_hostname": ""})
        expected_ret = "gunicorn-k8s"

        result = self.harness.charm._get_external_hostname()
        self.assertEqual(result, expected_ret)

    def test_make_pod_env_empty_conf(self):
        """
        arrange: given the deployed charm
        act: try to update the config to an empty value
        assert: the output config is correct
        """
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({"environment": ""})
        expected_ret = {}

        result = self.harness.charm._make_pod_env()
        self.assertEqual(result, expected_ret, "No env")

    def test_make_pod_env_proper_env_no_temp_rel(self):
        """
        arrange: given the deployed charm
        act: try to update the config
        assert: the output config is correct
        """
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({"environment": "a: b"})
        expected_ret = {"a": "b"}

        result = self.harness.charm._make_pod_env()
        self.assertEqual(result, expected_ret)

    def test_make_pod_env_proper_env_temp_rel(self):
        """
        arrange: given the deployed charm
        act: try to update the config and add relations
        assert: the output config is correct
        """
        # Proper env with templating/relations
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({"environment": "DB: {{pg.db_uri}}\nTHING: {{myrel.thing}}}"})
        expected_ret = {"a": "b"}

        # Set up PG relation
        reldata = self.harness.charm._stored.reldata
        reldata["pg"] = {"conn_str": TEST_PG_CONNSTR, "db_uri": TEST_PG_URI}

        # Set up random relation
        self.harness.disable_hooks()  # no need for hooks to fire for this test
        relation_id = self.harness.add_relation("myrel", "myapp")
        self.harness.add_relation_unit(relation_id, "myapp/0")
        self.harness.update_relation_data(relation_id, "myapp/0", {"thing": "bli"})

        expected_ret = {"DB": TEST_PG_URI, "THING": "bli}"}

        result = self.harness.charm._make_pod_env()
        self.assertEqual(result, expected_ret)

    def test_make_pod_env_improper_env(self):
        """
        arrange: given the deployed charm
        act: try to update the config with an improper variable
        assert: the output message is correct
        """
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({"environment": "a: :"})
        expected_output = [
            "ERROR:charm:Error when parsing the following YAML : a: : : mapping values "
            "are not allowed here\n"
            '  in "<unicode string>", line 1, column 4:\n'
            "    a: :\n"
            "       ^"
        ]
        with self.assertLogs(level="ERROR") as logger:
            self.harness.charm._make_pod_env()
            self.assertEqual(logger.output, expected_output)

    def test_get_gunicorn_pebble_config(self):
        """
        arrange: given the deployed charm
        act: try to get pebble's config
        assert: the output config is correct
        """
        mock_event = MagicMock()
        expected_ret = {
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
                    "http": {"url": "http://127.0.0.1:8080"},
                },
            },
        }

        result = self.harness.charm._get_gunicorn_pebble_config(mock_event)
        self.assertEqual(result, expected_ret)

    def test_get_gunicorn_pebble_config_error(self):
        """
        arrange: given the deployed charm
        act: try to get pebble's config facing an error
        assert: the error and output messages are correct
        """
        expected_error = "Error getting pod_env_config"
        expected_ret = {}
        mock_event = MagicMock()
        with patch("charm.GunicornK8sCharm._make_pod_env") as make_pod_env:
            make_pod_env.return_value = True

            with self.assertLogs(level="ERROR") as logger:
                config_output = self.harness.charm._get_gunicorn_pebble_config(mock_event)
                self.assertEqual(config_output, expected_ret)
            self.assertTrue(expected_error in logger.output[0])

    def test_on_pebble_ready_no_problem(self):
        """
        arrange: given the gunicorn container
        act: mark it as ready
        assert: the event handler executes successfully
        """
        mock_event = MagicMock()
        expected_ret = None

        result = self.harness.charm._on_pebble_ready(mock_event)
        self.assertEqual(result, expected_ret)

    def test_configure_workload_no_problem(self):
        """
        arrange: given a mock event
        act: execute configure_workload
        assert: the method executes successfully
        """
        mock_event = MagicMock()
        expected_ret = None

        result = self.harness.charm._configure_workload(mock_event)
        self.assertEqual(result, expected_ret)

    def test_configure_workload_exception(self):
        """
        arrange: given the deployed charm's containers
        act: mark them as ready with a wrong command
        assert: the deployment must be blocked
        """
        with patch("ops.model.Container.pebble", return_value=MagicMock()) as pebble_mock:
            pebble_mock.replan_services.side_effect = pebble.ChangeError("abc", "def")
            self.harness.container_pebble_ready("gunicorn")
            self.assertEqual(
                self.harness.model.unit.status,
                BlockedStatus("Charm's startup command may be wrong, please check the config"),
            )

    def test_configure_workload(self):
        """
        arrange: given the deployed charm's containers
        act: mark them as ready
        assert: the deployment must be active
        """
        self.harness.container_pebble_ready("gunicorn")
        self.assertEqual(
            self.harness.model.unit.status,
            ActiveStatus(),
        )

    def test_flatten_dict(self):
        """
        arrange: given a dict
        act: when the flatten_dict function is ran on it
        assert: it returns a flattened dict
        """
        # Empty
        test_dict = {}
        expected_dict = test_dict

        self.assertEqual(self.harness.charm._flatten_dict(test_dict), expected_dict)

        # One level
        test_dict = {"a": 1}
        expected_dict = test_dict

        self.assertEqual(self.harness.charm._flatten_dict(test_dict), expected_dict)

        # One level array
        test_dict = {"a": [1, 2, 3]}
        expected_dict = test_dict

        self.assertEqual(self.harness.charm._flatten_dict(test_dict), expected_dict)

        # Two level
        test_dict = {"a": {"b": 1, "c": 1}, "a2": {"b2": 2, "c2": 2}}
        expected_dict = {"a.b": 1, "a.c": 1, "a2.b2": 2, "a2.c2": 2}

        self.assertEqual(self.harness.charm._flatten_dict(test_dict), expected_dict)

        # Three level
        test_dict = {"a": {"b": {"c": 1}}}
        expected_dict = {"a.b.c": 1}

        self.assertEqual(self.harness.charm._flatten_dict(test_dict), expected_dict)

    def test_flatten_dict_args(self):
        """
        arrange: given a dict
        act: when the flatten_dict_ function is ran on it
        assert: it returns a flattened dict
        """
        test_dict = {"a": {"b": {"c": 1}}}
        expected_dict = {"test._a_b_c": 1}

        self.assertEqual(
            self.harness.charm._flatten_dict(test_dict, parent_key="test.", sep="_"), expected_dict
        )

    def test_on_show_environment_context_action(self):
        """
        arrange: given the deployed charm
        act: when some environment variables are inserted via relations
        assert: the environment variables are available
        """
        self.harness.disable_hooks()  # no need for hooks to fire for this test

        # Set up PG "special case" relation data
        reldata = self.harness.charm._stored.reldata
        reldata["pg"] = {"conn_str": TEST_PG_CONNSTR, "db_uri": TEST_PG_URI}

        # Set up PG "raw" relation data
        relation_id = self.harness.add_relation("pg", "postgresql")
        self.harness.add_relation_unit(relation_id, "postgresql/0")
        self.harness.update_relation_data(relation_id, "postgresql/0", {"version": "10"})

        # Set up random relation, with 2 units
        relation_id = self.harness.add_relation("myrel", "myapp")
        self.harness.add_relation_unit(relation_id, "myapp/0")
        self.harness.update_relation_data(relation_id, "myapp/0", {"thing": "bli"})

        mock_event = MagicMock()
        expected = {
            "available-variables": '[\n    "myrel.thing",\n    "pg.conn_str",\n'
            '    "pg.db_uri",\n    "pg.version"\n]'
        }

        self.harness.charm._on_show_environment_context_action(mock_event)
        mock_event.set_results.assert_called_once_with(expected)


if __name__ == "__main__":
    unittest.main()
