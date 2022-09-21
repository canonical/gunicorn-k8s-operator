# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


def pytest_addoption(parser):
    parser.addoption("--gunicorn-image", action="store")
    parser.addoption("--statsd-prometheus-exporter-image", action="store")
