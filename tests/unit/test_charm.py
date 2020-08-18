#!/usr/bin/env python3

"""Test for the gunicorn charm."""

import unittest

from unittest.mock import MagicMock

from charm import (
    GunicornK8sCharm,
    GunicornK8sCharmJujuConfigError,
)

from ops import testing
from ops.model import (
    ActiveStatus,
    BlockedStatus,
)

from scenario import (
    JUJU_CONFIG,
    TEST_JUJU_CONFIG,
    TEST_CONFIGURE_POD,
    TEST_MAKE_POD_SPEC,
    TEST_UPDATE_POD_SPEC_AND_INGRESS,
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

    def test_check_juju_config(self):
        """Check the required juju settings."""
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
            self.harness.update_config({}, JUJU_CONFIG)

    def test_configure_pod(self):
        """Test the pod configuration."""
        mock_event = MagicMock()

        self.harness.set_leader(False)
        self.harness.charm.unit.status = BlockedStatus("Testing")
        self.harness.charm.configure_pod(mock_event)
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        self.harness.update_config({}, JUJU_CONFIG)  # You need to clean the config after each run

        for scenario, values in TEST_CONFIGURE_POD.items():
            with self.subTest(scenario=scenario):
                self.harness.update_config(values['config'])
                self.harness.set_leader(True)
                self.harness.charm.configure_pod(mock_event)
                if values['expected']:
                    self.assertEqual(self.harness.charm.unit.status, BlockedStatus(values['expected']))
                else:
                    self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

                self.harness.update_config({}, JUJU_CONFIG)  # You need to clean the config after each run

    def test_make_pod_spec(self):
        """Check the crafting of the pod spec."""
        for scenario, values in TEST_MAKE_POD_SPEC.items():
            with self.subTest(scenario=scenario):
                self.harness.update_config(values['config'])
                self.assertEqual(self.harness.charm._make_pod_spec(), values['pod_spec'])
                self.harness.update_config({}, JUJU_CONFIG)  # You need to clean the config after each run

    def test_update_pod_spec_for_k8s_ingress(self):
        """Check the crafting of the ingress part of the pod spec."""
        for scenario, values in TEST_UPDATE_POD_SPEC_AND_INGRESS.items():
            with self.subTest(scenario=scenario):
                self.harness.update_config(values['config'])
                pod_spec = self.harness.charm._make_pod_spec()
                self.harness.charm._update_pod_spec_for_k8s_ingress(pod_spec)
                self.assertEqual(pod_spec, values['pod_spec'])
                self.harness.update_config({}, JUJU_CONFIG)  # You need to clean the config after each run


if __name__ == '__main__':
    unittest.main()
