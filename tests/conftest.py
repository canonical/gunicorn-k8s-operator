# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
# flake8: noqa

"""Fixtures for Gunicorn charm tests."""


def pytest_addoption(parser):
    parser.addoption("--gunicorn-image", action="store")
