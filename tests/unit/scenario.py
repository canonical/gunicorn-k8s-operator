#!/usr/bin/env python3
"""Define tests scenarios."""

import logging
import os
import yaml

from pathlib import Path


logger = logging.getLogger(__name__)


def get_juju_config() -> list:
    """Return the list of juju settings as defined in config.yaml."""

    dir_path = os.path.dirname(os.path.realpath(__file__))
    config_yaml = Path(dir_path, '..', '..', 'config.yaml')
    with open(config_yaml, 'r') as config:
        loaded_config = yaml.safe_load(config.read())

    return list(loaded_config['options'].keys())


# List of all juju settings. Used to clear them between tests
JUJU_CONFIG = get_juju_config()

TEST_JUJU_CONFIG = {
    'missing_image_path': {
        'config': {},
        'logger': ["ERROR:charm:Required Juju config item not set : image_path"],
        'expected': 'Required Juju config item not set : image_path',
    },
    'env_not_yaml': {
        'config': {'image_path': 'my_gunicorn_app:devel', 'environment': 'badyaml: :',},
        'logger': ["ERROR:charm:Juju config item 'environment' is not YAML : mapping values are "
                   'not allowed here\n'
                   '  in "<unicode string>", line 1, column 10:\n'
                   '    badyaml: :\n'
                   '             ^'],
        'expected': 'YAML parsing failed on the Juju config item(s) : environment - check "juju debug-log -l ERROR"',
    },
    'env_yaml_not_dict': {
        'config': {'image_path': 'my_gunicorn_app:devel', 'environment': 'not_a_dict',},
        'logger': ["ERROR:charm:Juju config item 'environment' is not a YAML dict"],
        'expected': 'YAML parsing failed on the Juju config item(s) : environment - check "juju debug-log -l ERROR"',
    },
    'good_config': {'config': {'image_path': 'my_gunicorn_app:devel', 'environment': '',}, 'logger': [], 'expected': False,},
}

TEST_CONFIGURE_POD = {
    'bad_config': {'config': {'environment': ''}, 'expected': 'Required Juju config item not set : image_path',},
    'good_config': {'config': {'image_path': 'my_gunicorn_app:devel', 'environment': '',}, 'expected': False,},
}

TEST_MAKE_POD_SPEC = {
    'basic': {
        'config': {'image_path': 'my_gunicorn_app:devel', 'environment': '',},
        'pod_spec': {
            'version': 3,  # otherwise resources are ignored
            'containers': [
                {
                    'name': 'gunicorn',
                    'imageDetails': {'imagePath': 'my_gunicorn_app:devel',},
                    'imagePullPolicy': 'Always',
                    'ports': [{'containerPort': 80, 'protocol': 'TCP'}],
                    'envConfig': {},
                    'kubernetes': {'readinessProbe': {'httpGet': {'path': '/', 'port': 80}}},
                }
            ],
        },
    },
    'private_registry': {
        'config': {
            'image_path': 'my_gunicorn_app:devel',
            'image_username': 'foo',
            'image_password': 'bar',
            'environment': '',
        },
        'pod_spec': {
            'version': 3,  # otherwise resources are ignored
            'containers': [
                {
                    'name': 'gunicorn',
                    'imageDetails': {'imagePath': 'my_gunicorn_app:devel', 'username': 'foo', 'password': 'bar',},
                    'imagePullPolicy': 'Always',
                    'ports': [{'containerPort': 80, 'protocol': 'TCP'}],
                    'envConfig': {},
                    'kubernetes': {'readinessProbe': {'httpGet': {'path': '/', 'port': 80}}},
                }
            ],
        },
    },
}


TEST_MAKE_K8S_INGRESS = {
    'basic': {
        'config': {'image_path': 'my_gunicorn_app:devel',},
        'expected': [
            {
                'name': 'gunicorn-ingress',
                'spec': {
                    'rules': [
                        {
                            'host': 'example.com',
                            'http': {
                                'paths': [{'path': '/', 'backend': {'serviceName': 'gunicorn', 'servicePort': 80},},],
                            },
                        },
                    ],
                },
                'annotations': {'nginx.ingress.kubernetes.io/ssl-redirect': 'false',},
            },
        ],
    },
}
