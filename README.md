# charm-k8s-gunicorn

## Description

A charm that allows you to deploy your gunicorn application in kubernetes.

## Usage

juju deploy cs:gunicorn my-awesome-app
juju config my-awesome-app image\_path=localhost:32000/myapp

### Scale Out Usage

juju add-unit my-awesome-app
