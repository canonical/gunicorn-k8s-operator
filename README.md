# charm-k8s-gunicorn

## Description

A charm that allows you to deploy your gunicorn application in kubernetes.

## Usage

By default, the charm will deploy a simple docker image that contains a
gunicorn app that displays a short message and its environment variables. The
image is built using an OCI Recipe on Launchpad and published to dockerhub
[here](https://hub.docker.com/r/gunicorncharmers/gunicorn-app).
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

### Using gunicorn-base to build an image

If you have a gunicorn app that's not available via a Docker image, you can use
the provided `gunicorn-base` image, which is published to dockerhub as
`gunicorncharmers/gunicorn-base:20.0.4-20.04_edge`. You can use this as a
base for other images, and there's an example of that in the `docker/app`
directory.

This example app will simply display all the environment variables given to
your pods. It can be helpful to see what's available and to debug problems
related to environment variables.

## Environment variables and relations

This charm has been designed to easily allow you to pass information coming
from relation data to your pods. This is done by using the `environment` config
option. This config option is a Jinja2 template for a YAML dict that will be
added to the environment of your pods.

The context used to render the Jinja2 template is constructed from relation
data. For example, if you're relating with influxdb, you could do the following :
```
juju deploy gunicorn-k8s my-awesome-app
juju config my-awesome-app environment="INFLUXDB_HOST: {{influxdb.hostname}}"
```

The charm will notice that you're trying to use data from the `influxdb` relation,
and will block until such a relation is added. Once the relation is added, the
charm will get the `hostname` from the relation, and will make it available to
your pod as the `INFLUXDB_HOST` environment variable.

If you want the charm to handle more "basic" relations such as the `influxdb`
one described above, all you have to do is add the relation to metadata.yaml
and rebuild the charm (see below).

Some relations, such as the `postgresql` relation, are a bit more complex, in
that they're managed by a library. Instead of using raw relation data, you use
the library to get useful and usable information out of the relation. If you
want to use such a relation, you will need to add a bit more code to make the
information provided by the library available to the Jinja2 context. An example
is provided in the charm with the `postgresql` relation implementation.

## Building the charm

It's as easy as running :
```
make
```

This will lint and format your code, then run unit tests, and then build the
charm.
