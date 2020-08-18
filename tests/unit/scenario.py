#!/usr/bin/env python3
"""Define tests scenarios."""

import os
import logging

from pathlib import Path

import yaml

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
        'logger': ["ERROR:charm:Required Juju config not set : image_path"],
        'expected': 'Required Juju config not set : image_path',
    },
    'good_config': {'config': {'image_path': 'my_gunicorn_app:devel'}, 'logger': [], 'expected': False,},
}

TEST_CONFIGURE_POD = {
    'bad_config': {'config': {}, 'expected': 'Required Juju config not set : image_path',},
    'good_config': {'config': {'image_path': 'my_gunicorn_app:devel'}, 'expected': False,},
}

TEST_MAKE_POD_SPEC = {
    'basic': {
        'config': {'image_path': 'my_gunicorn_app:devel',},
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
        'config': {'image_path': 'my_gunicorn_app:devel', 'image_username': 'foo', 'image_password': 'bar',},
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


TEST_UPDATE_POD_SPEC_AND_INGRESS = {
    'basic': {
        'config': {'image_path': 'my_gunicorn_app:devel',},
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
            'kubernetesResources': {
                'ingressResources': [
                    {
                        'name': 'gunicorn-ingress',
                        'spec': {
                            'rules': [
                                {
                                    'host': 'example.com',
                                    'http': {
                                        'paths': [
                                            {'path': '/', 'backend': {'serviceName': 'gunicorn', 'servicePort': 80},},
                                        ],
                                    },
                                },
                            ],
                        },
                        'annotations': {'nginx.ingress.kubernetes.io/ssl-redirect': 'false',},
                    },
                ],
            },
        },
    },
    #    'ssl': {
    #        'config': {
    #            'image_path': 'my_gunicorn_app:devel',
    #            'my_gunicorn_app_cfg': 'foo',
    #            'ingress_whitelist_source_range': '10.0.69.0/24',
    #            'tls_secret_name': 'my_gunicorn_app_secret',
    #        },
    #        'pod_spec': {
    #            'version': 3,  # otherwise resources are ignored
    #            'containers': [
    #                {
    #                    'name': 'gunicorn',
    #                    'imageDetails': {'imagePath': 'my_gunicorn_app:devel',},
    #                    'imagePullPolicy': 'Always',
    #                    'ports': [{'containerPort': 80, 'protocol': 'TCP'}],
    #                    'envConfig': {},
    #                }
    #            ],
    #            'kubernetesResources': {
    #                'ingressResources': [
    #                    {
    #                        'name': 'gunicorn-ingress',
    #                        'spec': {
    #                            'rules': [
    #                                {
    #                                    'host': 'example.com',
    #                                    'http': {
    #                                        'paths': [
    #                                            {
    #                                                'path': '/',
    #                                                'backend': {'serviceName': 'gunicorn', 'servicePort': 80},
    #                                            },
    #                                        ],
    #                                    },
    #                                },
    #                            ],
    #                            'tls': [{'hosts': ['example.com'], 'secretName': 'my_gunicorn_app_secret',},],
    #                        },
    #                        'annotations': {'nginx.ingress.kubernetes.io/whitelist-source-range': '10.0.69.0/24',},
    #                    },
    #                ],
    #            },
    #        },
    #    },
}
