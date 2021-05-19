# Gunicorn Operator

## Description

A charm that allows you to deploy your gunicorn application in kubernetes.

## Usage

By default, the charm will deploy a simple [OCI](https://opencontainers.org/)
image that contains a gunicorn app that displays a short message and its
environment variables. The image is built using an OCI Recipe on Launchpad and
published to dockerhub [here](https://hub.docker.com/r/gunicorncharmers/gunicorn-app).
```
juju deploy gunicorn-k8s my-awesome-app
```

### Scale Out Usage

```
juju add-unit my-awesome-app
```

## OCI image

### Using your own image

You can, of course, supply our own OCI image. gunicorn is expected to listen on
port 80. To do so, specify `--resource gunicorn-image='image-location'` at
deploy time, or use `juju attach-resource` if you want to switch images after
initial deployment.

---

For more details, [see here](https://charmhub.io/gunicorn-k8s/docs).
