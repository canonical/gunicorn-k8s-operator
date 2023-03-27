#!/usr/bin/env python3
# flake8: noqa
"""Define tests scenarios."""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def get_juju_default_config() -> dict:
    """Return the list of juju settings as defined in config.yaml."""

    dir_path = os.path.dirname(os.path.realpath(__file__))
    config_yaml = Path(dir_path, "..", "..", "config.yaml")
    with open(config_yaml, "r") as config:
        loaded_config = yaml.safe_load(config.read())

    ret = {}

    for k, v in loaded_config["options"].items():
        ret[k] = v["default"]

    return ret


JUJU_DEFAULT_CONFIG = get_juju_default_config()

TEST_PG_URI = "postgresql://usr:pwd@1.2.3.4:5432/gunicorn"
TEST_PG_CONNSTR = "dbname=gunicorn host=1.2.3.4 password=pwd port=5432 user=usr"

TEST_JUJU_CONFIG = {
    "defaults": {
        "config": {},
        "logger": [],
        "expected": False,
    },
    "missing_external_hostname": {
        "config": {
            "external_hostname": "",
        },
        "logger": ["ERROR:charm:Required Juju config item not set : external_hostname"],
        "expected": "Required Juju config item(s) not set : external_hostname",
    },
    "good_config_no_env": {
        "config": {"external_hostname": "example.com"},
        "logger": [],
        "expected": False,
    },
    "good_config_with_env": {
        "config": {
            "environment": "MYENV: foo",
            "external_hostname": "example.com",
        },
        "logger": [],
        "expected": False,
    },
}

TEST_CONFIGURE_POD = {
    "good_config_no_env": {
        "config": {
            "external_hostname": "example.com",
        },
        "_leader_get": "5:\n  database: gunicorn\n  extensions: ''\n  roles: ''",
        "expected": False,
    },
    "good_config_with_env": {
        "config": {
            "external_hostname": "example.com",
            "environment": "MYENV: foo",
        },
        "_leader_get": "5:\n  database: gunicorn\n  extensions: ''\n  roles: ''",
        "expected": False,
    },
}

TEST_RENDER_TEMPLATE = {
    "working": {
        "tmpl": "test {{db.x}}",
        "ctx": {"db": {"x": "foo"}},
        "expected": "test foo",
    }
}
