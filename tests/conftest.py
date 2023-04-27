# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Gunicorn charm tests."""


def pytest_addoption(parser):
    """Add options to the pytest parser.

    Args:
        parser: Pytest parser.
    """
    parser.addoption("--gunicorn-image", action="store")
