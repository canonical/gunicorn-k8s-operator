# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Gunicorn charm tests."""


def pytest_addoption(parser):
    """Add options to the pytest parser.

    Args:
        parser: Pytest parser.
    """
    parser.addoption("--charm-file", action="store")
    parser.addoption("--gunicorn-k8s-operator-image", action="store")
