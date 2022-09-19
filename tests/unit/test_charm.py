#!/usr/bin/env python3

"""Test for the gunicorn charm."""

import unittest

from unittest.mock import MagicMock, patch

from charm import GunicornK8sCharm

from ops import testing

from scenario import (
    JUJU_DEFAULT_CONFIG,
    TEST_JUJU_CONFIG,
    TEST_RENDER_TEMPLATE,
    TEST_PG_URI,
    TEST_PG_CONNSTR,
)


class TestGunicornK8sCharm(unittest.TestCase):

    maxDiff = None  # Full diff when there is an error

    def setUp(self):
        """Setup the harness object."""
        self.harness = testing.Harness(GunicornK8sCharm)
        self.harness.begin()
        self.harness.add_oci_resource('gunicorn-image')

    def tearDown(self):
        """Cleanup the harness."""
        self.harness.cleanup()

    def test_init_postgresql_relation(self):
        """Test the _init_postgresql_relation function."""

        # We'll only test the case where _stored already
        # has content. _stored being empty is basically tested
        # by all the other functions

        with patch('test_charm.GunicornK8sCharm._stored') as mock_stored:
            with patch('pgsql.PostgreSQLClient'):
                with patch('test_charm.GunicornK8sCharm.on'):
                    mock_stored.reldata = {'pg': 'foo'}
                    c = GunicornK8sCharm(MagicMock())
                    self.assertEqual(c._stored.reldata, mock_stored.reldata)

    def test_on_database_relation_joined_unit_is_leader(self):
        """Test the _on_database_relation_joined function."""

        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(True)

        self.harness.charm._on_database_relation_joined(mock_event)

        self.assertEqual(mock_event.database, self.harness.charm.app.name)

    def test_on_database_relation_joined_unit_is_not_leader(self):
        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(False)

        self.harness.charm._on_database_relation_joined(mock_event)

        mock_event.defer.assert_called_once()

        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(False)
        mock_event.database = self.harness.charm.app.name

        r = self.harness.charm._on_database_relation_joined(mock_event)
        self.assertEqual(r, None)

    def test_on_master_changed(self):
        """Test the _on_master_changed function."""

        # No database
        mock_event = MagicMock()
        mock_event.database = None

        r = self.harness.charm._on_master_changed(mock_event)
        self.assertEqual(r, None)

        # Database but no master
        mock_event = MagicMock()
        mock_event.database = self.harness.charm.app.name
        mock_event.master = None

        r = self.harness.charm._on_master_changed(mock_event)
        reldata = self.harness.charm._stored.reldata
        self.assertEqual(reldata['pg']['conn_str'], None)
        self.assertEqual(reldata['pg']['db_uri'], None)
        self.assertEqual(r, None)

        # Database with master
        mock_event = MagicMock()
        mock_event.database = self.harness.charm.app.name
        mock_event.master.conn_str = TEST_PG_CONNSTR
        mock_event.master.uri = TEST_PG_URI
        with patch('charm.GunicornK8sCharm._on_config_changed') as on_config_changes:
            r = self.harness.charm._on_master_changed(mock_event)

            reldata = self.harness.charm._stored.reldata
            self.assertEqual(reldata['pg']['conn_str'], mock_event.master.conn_str)
            self.assertEqual(reldata['pg']['db_uri'], mock_event.master.uri)
            self.assertEqual(r, None)
            on_config_changes.assert_called_with(mock_event)

    def test_on_standby_changed_database_not_ready(self):
        """Test the _on_standby_changed function."""

        mock_event = MagicMock()
        mock_event.database = None

        r = self.harness.charm._on_standby_changed(mock_event)
        self.assertEqual(r, None)

    def test_on_standby_changed_database_ready(self):
        """Test the _on_standby_changed function."""

        mock_event = MagicMock()
        mock_event.database = self.harness.charm.app.name

        mock_event.standbys = [MagicMock()]
        mock_event.standbys[0].uri = TEST_PG_URI

        self.harness.charm._on_standby_changed(mock_event)

        reldata = self.harness.charm._stored.reldata
        self.assertEqual(reldata['pg']['ro_uris'], [TEST_PG_URI])

    def test_on_mongodb_client_relation_changed(self):
        """Test the _on_mongodb_client_relation_changed function."""
        class FakeMongoDB(object):
            def fetch_relation_data(self):
                return {
                    1: {
                        "database": "gunicorn-k8s",
                        "username": "someusername",
                        "password": "somepassword",
                        "endpoints": "someendpoint",
                    }
                }

        self.harness.charm.mongodb = FakeMongoDB()

        # Test nothing in stored state related to MongoDB.
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
        self.harness.charm._on_mongodb_client_relation_changed(mock_event)
        self.assertEqual(self.harness.charm._stored.reldata, expected_data)

        # And now test it again to confirm what happens if mongodb is already
        # in StoredState.
        self.harness.charm._on_mongodb_client_relation_changed(mock_event)
        self.assertEqual(self.harness.charm._stored.reldata, expected_data)

    def test_check_juju_config(self):
        """Check the required juju settings."""
        self.harness.update_config(JUJU_DEFAULT_CONFIG)

        for scenario, values in TEST_JUJU_CONFIG.items():
            with self.subTest(scenario=scenario):
                self.harness.update_config(values['config'])
                if values['expected']:
                    with self.assertLogs(level='ERROR') as logger:
                        self.harness.charm._check_juju_config()
                    self.assertEqual(sorted(logger.output), sorted(values['logger']))
                else:
                    self.assertEqual(self.harness.charm._check_juju_config(), None)

                # You need to clean the config after each run
                # See https://github.com/canonical/operator/blob/master/ops/testing.py#L415
                # The second argument is the list of key to reset
                self.harness.update_config(JUJU_DEFAULT_CONFIG)

    def test_render_template(self):
        """Test template rendering."""

        for scenario, values in TEST_RENDER_TEMPLATE.items():
            with self.subTest(scenario=scenario):
                r = self.harness.charm._render_template(values['tmpl'], values['ctx'])
                self.assertEqual(r, values['expected'])

    def test_get_context_from_relations(self):
        """Test the _get_context_from_relations function."""

        self.harness.disable_hooks()  # no need for hooks to fire for this test

        # Set up PG "special case" relation data
        reldata = self.harness.charm._stored.reldata
        reldata['pg'] = {'conn_str': TEST_PG_CONNSTR, 'db_uri': TEST_PG_URI}

        # Set up PG "raw" relation data
        relation_id = self.harness.add_relation('pg', 'postgresql')
        self.harness.add_relation_unit(relation_id, 'postgresql/0')
        self.harness.update_relation_data(relation_id, 'postgresql/0', {'version': '10'})

        # Set up random relation, with 2 units
        relation_id = self.harness.add_relation('myrel', 'myapp')
        self.harness.add_relation_unit(relation_id, 'myapp/0')
        self.harness.add_relation_unit(relation_id, 'myapp/1')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'thing': 'bli'})
        self.harness.update_relation_data(relation_id, 'myapp/1', {'thing': 'blo'})

        # Set up same relation but with a different app
        relation_id = self.harness.add_relation('myrel', 'myapp2')
        self.harness.add_relation_unit(relation_id, 'myapp2/0')
        self.harness.update_relation_data(relation_id, 'myapp2/0', {'thing': 'blu'})

        # Set up random relation, no unit (can happen during relation init)
        relation_id = self.harness.add_relation('myrel2', 'myapp2')

        expected_ret = {
            'pg': {'conn_str': TEST_PG_CONNSTR, 'db_uri': TEST_PG_URI, 'version': '10'},
            'myrel': {'thing': 'bli'},
        }
        expected_logger = [
            'WARNING:charm:Multiple relations of type "myrel" detected, '
            'using only the first one (id: 1) for relation data.',
            'WARNING:charm:Multiple units detected in the relation "myrel:1", '
            'using only the first one (id: myapp/0) for relation data.',
        ]

        with self.assertLogs(level="WARNING") as logger:
            r = self.harness.charm._get_context_from_relations()

        self.assertEqual(sorted(logger.output), sorted(expected_logger))
        self.assertEqual(r, expected_ret)

    def test_validate_yaml_proper_type_proper_yaml(self):
        """Test the _validate_yaml function."""

        test_str = "a: b\n1: 2"
        expected_type = dict

        r = self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(r, None)

    def test_validate_yaml_incorrect_yaml(self):

        test_str = "a: :"
        expected_type = dict
        expected_output = [
            'ERROR:charm:Error when parsing the following YAML : a: : : mapping values '
            'are not allowed here\n'
            '  in "<unicode string>", line 1, column 4:\n'
            '    a: :\n'
            '       ^'
        ]

        with self.assertLogs(level='ERROR') as logger:
            self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(sorted(logger.output), expected_output)

    def test_validate_yaml_incorrect_type_proper_yaml(self):

        test_str = "a: b"
        expected_type = str
        expected_output = [
            "ERROR:charm:Expected type '<class 'str'>' but got '<class 'dict'>' when " 'parsing YAML : a: b'
        ]

        with self.assertLogs(level='ERROR') as logger:
            self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(sorted(logger.output), expected_output)

    def test_make_pod_env_empty_conf(self):
        """Test the _make_pod_env function."""

        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({'environment': ''})
        expected_ret = {}

        r = self.harness.charm._make_pod_env()
        self.assertEqual(r, expected_ret, "No env")

    def test_make_pod_env_proper_env_no_temp_rel(self):

        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({'environment': 'a: b'})
        expected_ret = {'a': 'b'}

        r = self.harness.charm._make_pod_env()
        self.assertEqual(r, expected_ret)

    def test_make_pod_env_proper_env_temp_rel(self):

        # Proper env with templating/relations
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({'environment': "DB: {{pg.db_uri}}\nTHING: {{myrel.thing}}}"})
        expected_ret = {'a': 'b'}

        # Set up PG relation
        reldata = self.harness.charm._stored.reldata
        reldata['pg'] = {'conn_str': TEST_PG_CONNSTR, 'db_uri': TEST_PG_URI}

        # Set up random relation
        self.harness.disable_hooks()  # no need for hooks to fire for this test
        relation_id = self.harness.add_relation('myrel', 'myapp')
        self.harness.add_relation_unit(relation_id, 'myapp/0')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'thing': 'bli'})

        expected_ret = {'DB': TEST_PG_URI, 'THING': 'bli}'}

        r = self.harness.charm._make_pod_env()
        self.assertEqual(r, expected_ret)

    def test_make_pod_env_improper_env(self):

        # Improper env
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({'environment': 'a: :'})
        expected_output = [
            'ERROR:charm:Error when parsing the following YAML : a: : : mapping values '
            'are not allowed here\n'
            '  in "<unicode string>", line 1, column 4:\n'
            '    a: :\n'
            '       ^'
        ]
        with self.assertLogs(level='ERROR') as logger:
            self.harness.charm._make_pod_env()
            self.assertEqual(logger.output, expected_output)

    def test_get_pebble_config(self):
        """Test the _get_pebble_config function."""
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
                    "http": {"url": "http://127.0.0.1:80"},
                },
            },
        }

        r = self.harness.charm._get_pebble_config(mock_event)
        self.assertEqual(r, expected_ret)

    def test_get_pebble_config_error(self):
        """Test the _get_pebble_config function when throwing an error."""
        expected_output = "ERROR:charm:Error getting pod_env_config: Could not parse Juju config 'environment' as a YAML dict - check \"juju debug-log -l ERROR\""  # noqa: E501
        expected_ret = {}
        mock_event = MagicMock()
        with patch('charm.GunicornK8sCharm._make_pod_env') as make_pod_env:
            make_pod_env.return_value = True

            with self.assertLogs(level='ERROR') as logger:
                r = self.harness.charm._get_pebble_config(mock_event)
                self.assertEqual(r, expected_ret)
            self.assertEqual(expected_output, logger.output[0])

    def test_on_gunicorn_pebble_ready_no_problem(self):
        """Test the _on_gunicorn_pebble_ready function."""

        mock_event = MagicMock()
        expected_ret = None

        r = self.harness.charm._on_gunicorn_pebble_ready(mock_event)
        self.assertEqual(r, expected_ret)

    def test_configure_workload_no_problem(self):
        """Test the _configure_workload function."""

        mock_event = MagicMock()
        expected_ret = None

        r = self.harness.charm._configure_workload(mock_event)
        self.assertEqual(r, expected_ret)

    def test_configure_workload_pebble_not_ready(self):

        mock_event = MagicMock()
        expected_ret = None
        expected_output = 'waiting for pebble to start'
        with patch('ops.model.Container.can_connect') as can_connect:
            can_connect.return_value = False

            with self.assertLogs(level='DEBUG') as logger:
                r = self.harness.charm._configure_workload(mock_event)
                self.assertEqual(r, expected_ret)
            self.assertTrue(expected_output in logger.output[0])


if __name__ == '__main__':
    unittest.main()
