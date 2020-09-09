#!/usr/bin/env python3
"""Define tests scenarios."""

import logging
import os
import yaml

from pathlib import Path


logger = logging.getLogger(__name__)


def get_juju_default_config() -> dict:
    """Return the list of juju settings as defined in config.yaml."""

    dir_path = os.path.dirname(os.path.realpath(__file__))
    config_yaml = Path(dir_path, '..', '..', 'config.yaml')
    with open(config_yaml, 'r') as config:
        loaded_config = yaml.safe_load(config.read())

    ret = {}

    for k, v in loaded_config['options'].items():
        ret[k] = v['default']

    return ret


JUJU_DEFAULT_CONFIG = get_juju_default_config()

TEST_PG_URI = 'postgresql://usr:pwd@1.2.3.4:5432/gunicorn'
TEST_PG_CONNSTR = 'dbname=gunicorn host=1.2.3.4 password=pwd port=5432 user=usr'

TEST_JUJU_CONFIG = {
    'defaults': {
        'config': {},
        'logger': [
            "ERROR:charm:Required Juju config item not set : image_path",
            'ERROR:charm:Required Juju config item not set : external_hostname',
        ],
        'expected': 'Required Juju config item(s) not set : external_hostname, image_path',
    },
    'missing_image_path': {
        'config': {
            'external_hostname': 'example.com',
        },
        'logger': ["ERROR:charm:Required Juju config item not set : image_path"],
        'expected': 'Required Juju config item(s) not set : image_path',
    },
    'missing_external_hostname': {
        'config': {
            'image_path': 'my_gunicorn_app:devel',
        },
        'logger': ["ERROR:charm:Required Juju config item not set : external_hostname"],
        'expected': 'Required Juju config item(s) not set : external_hostname',
    },
    'good_config_no_env': {
        'config': {'image_path': 'my_gunicorn_app:devel', 'external_hostname': 'example.com'},
        'logger': [],
        'expected': False,
    },
    'good_config_with_env': {
        'config': {
            'image_path': 'my_gunicorn_app:devel',
            'environment': 'MYENV: foo',
            'external_hostname': 'example.com',
        },
        'logger': [],
        'expected': False,
    },
}

TEST_CONFIGURE_POD = {
    'bad_config': {
        'config': {
            'external_hostname': 'example.com',
        },
        '_leader_get': "5:\n  database: gunicorn\n  extensions: ''\n  roles: ''",
        'expected': 'Required Juju config item(s) not set : image_path',
    },
    'good_config_no_env': {
        'config': {
            'image_path': 'my_gunicorn_app:devel',
            'external_hostname': 'example.com',
        },
        '_leader_get': "5:\n  database: gunicorn\n  extensions: ''\n  roles: ''",
        'expected': False,
    },
    'good_config_with_env': {
        'config': {
            'image_path': 'my_gunicorn_app:devel',
            'external_hostname': 'example.com',
            'environment': 'MYENV: foo',
        },
        '_leader_get': "5:\n  database: gunicorn\n  extensions: ''\n  roles: ''",
        'expected': False,
    },
}

TEST_MAKE_POD_SPEC = {
    'basic_no_env': {
        'config': {
            'image_path': 'my_gunicorn_app:devel',
            'external_hostname': 'example.com',
        },
        'pod_spec': {
            'version': 3,  # otherwise resources are ignored
            'containers': [
                {
                    'name': 'gunicorn',
                    'imageDetails': {
                        'imagePath': 'my_gunicorn_app:devel',
                    },
                    'imagePullPolicy': 'Always',
                    'ports': [{'containerPort': 80, 'protocol': 'TCP'}],
                    'envConfig': {},
                    'kubernetes': {'readinessProbe': {'httpGet': {'path': '/', 'port': 80}}},
                }
            ],
        },
    },
    'basic_with_env': {
        'config': {
            'image_path': 'my_gunicorn_app:devel',
            'external_hostname': 'example.com',
            'environment': 'MYENV: foo',
        },
        'pod_spec': {
            'version': 3,  # otherwise resources are ignored
            'containers': [
                {
                    'name': 'gunicorn',
                    'imageDetails': {
                        'imagePath': 'my_gunicorn_app:devel',
                    },
                    'imagePullPolicy': 'Always',
                    'ports': [{'containerPort': 80, 'protocol': 'TCP'}],
                    'envConfig': {'MYENV': 'foo'},
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
            'external_hostname': 'example.com',
        },
        'pod_spec': {
            'version': 3,  # otherwise resources are ignored
            'containers': [
                {
                    'name': 'gunicorn',
                    'imageDetails': {
                        'imagePath': 'my_gunicorn_app:devel',
                        'username': 'foo',
                        'password': 'bar',
                    },
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
        'config': {
            'image_path': 'my_gunicorn_app:devel',
            'external_hostname': 'example.com',
        },
        'expected': [
            {
                'name': 'gunicorn-ingress',
                'spec': {
                    'rules': [
                        {
                            'host': 'example.com',
                            'http': {
                                'paths': [
                                    {
                                        'path': '/',
                                        'backend': {'serviceName': 'gunicorn', 'servicePort': 80},
                                    },
                                ],
                            },
                        },
                    ],
                },
                'annotations': {
                    'nginx.ingress.kubernetes.io/ssl-redirect': 'false',
                },
            },
        ],
    },
}

TEST_RENDER_TEMPLATE = {
    'working': {
        'tmpl': "test {{db.x}}",
        'ctx': {'db': {'x': 'foo'}},
        'expected': "test foo",
    }
}
