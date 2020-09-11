#!/usr/bin/env python3

"""Test for the gunicorn charm."""

import unittest

from unittest.mock import MagicMock, patch

from charm import GunicornK8sCharm, GunicornK8sCharmJujuConfigError, GunicornK8sCharmYAMLError

from ops import testing
from ops.model import (
    ActiveStatus,
    BlockedStatus,
)

from scenario import (
    JUJU_DEFAULT_CONFIG,
    TEST_JUJU_CONFIG,
    TEST_CONFIGURE_POD,
    TEST_MAKE_POD_SPEC,
    TEST_MAKE_K8S_INGRESS,
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

    def tearDown(self):
        """Cleanup the harness."""
        self.harness.cleanup()

    def test_on_database_relation_joined(self):
        """Test the _on_database_relation_joined function."""

        # Unit is leader
        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(True)

        self.harness.charm._on_database_relation_joined(mock_event)

        self.assertEqual(mock_event.database, self.harness.charm.app.name)

        # Unit is not leader, DB not ready
        mock_event = MagicMock()
        self.harness.disable_hooks()  # we don't want leader-set to fire
        self.harness.set_leader(False)

        self.harness.charm._on_database_relation_joined(mock_event)

        mock_event.defer.assert_called_once()

        # Unit is leader, DB ready
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
        with patch('charm.GunicornK8sCharm._configure_pod') as configure_pod:
            r = self.harness.charm._on_master_changed(mock_event)

            reldata = self.harness.charm._stored.reldata
            self.assertEqual(reldata['pg']['conn_str'], mock_event.master.conn_str)
            self.assertEqual(reldata['pg']['db_uri'], mock_event.master.uri)
            self.assertEqual(r, None)
            configure_pod.assert_called_with(mock_event)

    def test_on_standby_changed(self):
        """Test the _on_standby_changed function."""

        # Database not ready
        mock_event = MagicMock()
        mock_event.database = None

        r = self.harness.charm._on_standby_changed(mock_event)
        self.assertEqual(r, None)

        # Database ready
        mock_event = MagicMock()
        mock_event.database = self.harness.charm.app.name

        mock_event.standbys = [MagicMock()]
        mock_event.standbys[0].uri = TEST_PG_URI

        r = self.harness.charm._on_standby_changed(mock_event)

        reldata = self.harness.charm._stored.reldata
        self.assertEqual(reldata['pg']['ro_uris'], [TEST_PG_URI])

    def test_check_juju_config(self):
        """Check the required juju settings."""
        self.harness.update_config(JUJU_DEFAULT_CONFIG)

        for scenario, values in TEST_JUJU_CONFIG.items():
            with self.subTest(scenario=scenario):
                self.harness.update_config(values['config'])
                if values['expected']:
                    with self.assertLogs(level='ERROR') as logger:
                        with self.assertRaises(GunicornK8sCharmJujuConfigError) as exc:
                            self.harness.charm._check_juju_config()
                    self.assertEqual(sorted(logger.output), sorted(values['logger']))
                    self.assertEqual(str(exc.exception), values['expected'])
                else:
                    self.assertEqual(self.harness.charm._check_juju_config(), None)

                # You need to clean the config after each run
                # See https://github.com/canonical/operator/blob/master/ops/testing.py#L415
                # The second argument is the list of key to reset
                self.harness.update_config(JUJU_DEFAULT_CONFIG)

    def test_make_k8s_ingress(self):
        """Check the crafting of the ingress part of the pod spec."""
        self.harness.update_config(JUJU_DEFAULT_CONFIG)

        for scenario, values in TEST_MAKE_K8S_INGRESS.items():
            with self.subTest(scenario=scenario):
                self.harness.update_config(values['config'])
                self.assertEqual(self.harness.charm._make_k8s_ingress(), values['expected'])
                self.harness.update_config(JUJU_DEFAULT_CONFIG)  # You need to clean the config after each run

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

        # Set up random relation, with a unit
        relation_id = self.harness.add_relation('myrel', 'myapp')
        self.harness.add_relation_unit(relation_id, 'myapp/0')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'thing': 'bli'})

        # Set up random relation, no unit (can happen during relation init)
        relation_id = self.harness.add_relation('myrel2', 'myapp2')

        expected_ret = {
            'pg': {'conn_str': TEST_PG_CONNSTR, 'db_uri': TEST_PG_URI, 'version': '10'},
            'myrel': {'thing': 'bli'},
        }

        r = self.harness.charm._get_context_from_relations()

        self.assertEqual(r, expected_ret)

    def test_validate_yaml(self):
        """Test the _validate_yaml function."""

        # Proper YAML and type
        test_str = "a: b\n1: 2"
        expected_type = dict

        r = self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(r, None)

        # Incorrect YAML
        test_str = "a: :"
        expected_type = dict
        expected_output = [
            'ERROR:charm:Error when parsing the following YAML : a: : : mapping values '
            'are not allowed here\n'
            '  in "<unicode string>", line 1, column 4:\n'
            '    a: :\n'
            '       ^'
        ]
        expected_exception = 'YAML parsing failed, please check "juju debug-log -l ERROR"'

        with self.assertLogs(level='ERROR') as logger:
            with self.assertRaises(GunicornK8sCharmYAMLError) as exc:
                self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(sorted(logger.output), expected_output)
        self.assertEqual(str(exc.exception), expected_exception)

        # Proper YAML, incorrect type
        test_str = "a: b"
        expected_type = str
        expected_output = [
            "ERROR:charm:Expected type '<class 'str'>' but got '<class 'dict'>' when " 'parsing YAML : a: b'
        ]

        expected_exception = 'YAML parsing failed, please check "juju debug-log -l ERROR"'

        with self.assertLogs(level='ERROR') as logger:
            with self.assertRaises(GunicornK8sCharmYAMLError) as exc:
                self.harness.charm._validate_yaml(test_str, expected_type)

        self.assertEqual(sorted(logger.output), expected_output)
        self.assertEqual(str(exc.exception), expected_exception)

    def test_make_pod_env(self):
        """Test the _make_pod_env function."""

        # No env
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({'environment': ''})
        expected_ret = {}

        r = self.harness.charm._make_pod_env()
        self.assertEqual(r, expected_ret)

        # Proper env, no templating/relation
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({'environment': 'a: b'})
        expected_ret = {'a': 'b'}

        r = self.harness.charm._make_pod_env()
        self.assertEqual(r, expected_ret)

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

        # Improper env
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config({'environment': 'a: :'})
        expected_ret = None
        expected_exception = (
            'Could not parse Juju config \'environment\' as a YAML dict - check "juju debug-log -l ERROR"'
        )

        with self.assertRaises(GunicornK8sCharmJujuConfigError) as exc:
            self.harness.charm._make_pod_env()

        self.assertEqual(str(exc.exception), expected_exception)

    @patch('pgsql.pgsql._leader_get')
    def test_configure_pod(self, mock_leader_get):
        """Test the pod configuration."""

        mock_event = MagicMock()
        self.harness.update_config(JUJU_DEFAULT_CONFIG)

        self.harness.set_leader(False)
        self.harness.charm.unit.status = BlockedStatus("Testing")
        self.harness.charm._configure_pod(mock_event)
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        self.harness.update_config(JUJU_DEFAULT_CONFIG)  # You need to clean the config after each run

        for scenario, values in TEST_CONFIGURE_POD.items():
            with self.subTest(scenario=scenario):
                mock_leader_get.return_value = values['_leader_get']
                self.harness.update_config(values['config'])
                self.harness.set_leader(True)
                self.harness.charm._configure_pod(mock_event)
                if values['expected']:
                    self.assertEqual(self.harness.charm.unit.status, BlockedStatus(values['expected']))
                else:
                    self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

                self.harness.update_config(JUJU_DEFAULT_CONFIG)  # You need to clean the config after each run

        # Test missing vars
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config(
            {
                'image_path': 'my_gunicorn_app:devel',
                'external_hostname': 'example.com',
                'environment': 'DB_URI: {{pg.uri}}',
            }
        )
        self.harness.set_leader(True)
        expected_status = 'Waiting for pg relation'

        self.harness.charm._configure_pod(mock_event)

        mock_event.defer.assert_called_once()
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus(expected_status))

        # Test no missing vars
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config(
            {
                'image_path': 'my_gunicorn_app:devel',
                'external_hostname': 'example.com',
                'environment': 'DB_URI: {{pg.uri}}',
            }
        )

        reldata = self.harness.charm._stored.reldata
        reldata['pg'] = {'conn_str': TEST_PG_CONNSTR, 'db_uri': TEST_PG_URI}
        self.harness.set_leader(True)
        # Set up random relation
        self.harness.disable_hooks()  # no need for hooks to fire for this test
        relation_id = self.harness.add_relation('myrel', 'myapp')
        self.harness.add_relation_unit(relation_id, 'myapp/0')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'thing': 'bli'})
        expected_status = 'Waiting for pg relation'

        self.harness.charm._configure_pod(mock_event)

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        # Test incorrect YAML
        self.harness.update_config(JUJU_DEFAULT_CONFIG)
        self.harness.update_config(
            {
                'image_path': 'my_gunicorn_app:devel',
                'external_hostname': 'example.com',
                'environment': 'a: :',
            }
        )
        self.harness.set_leader(True)
        expected_status = 'Could not parse Juju config \'environment\' as a YAML dict - check "juju debug-log -l ERROR"'

        self.harness.charm._configure_pod(mock_event)

        self.assertEqual(self.harness.charm.unit.status, BlockedStatus(expected_status))

    def test_make_pod_spec(self):
        """Check the crafting of the pod spec."""
        self.harness.update_config(JUJU_DEFAULT_CONFIG)

        for scenario, values in TEST_MAKE_POD_SPEC.items():
            with self.subTest(scenario=scenario):
                self.harness.update_config(values['config'])
                self.assertEqual(self.harness.charm._make_pod_spec(), values['pod_spec'])
                self.harness.update_config(JUJU_DEFAULT_CONFIG)  # You need to clean the config after each run


if __name__ == '__main__':
    unittest.main()
