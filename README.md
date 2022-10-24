# Gunicorn-k8s Operator

A Juju charm deploying docker images using gunicorn as default. 

This charm simplifies docker image deployment management, 
allowing us to inject variables to the environment as we see fit. It allows for deployment on
many different Kubernetes platforms, from [MicroK8s](https://microk8s.io) to
[Charmed Kubernetes](https://ubuntu.com/kubernetes) to public cloud Kubernetes
offerings.

As such, the charm makes it easy for those looking to take control of their docker images, 
use them in a juju environment without having to write a charm from scratch and gives them the
freedom to deploy on the Kubernetes platform of their choice.

For DevOps or SRE teams this charm will make docker image testing easier and more manageable. 
It will allow easy deployment into multiple environments for testing of changes,
and supports scaling out for enterprise deployments.

## Deployment options overview

For overall concepts related to using Juju
[see the Juju overview page](https://juju.is/). For easy local testing we
recommend
[this how to on using MicroK8s with Juju](https://juju.is/docs/microk8s-cloud).

## How to deploy this charm (quick guide)

To deploy the charm and relate it to
[the PostgreSQL K8s charm](https://charmhub.io/postgresql-k8s) within a Juju Kubernetes model:

    juju deploy postgresql-k8s
    juju deploy gunicorn-k8s
    juju relate postgresql-k8s:db gunicorn-k8s:pg
    
The charm also supports the `ingress` relation, which can be used with
[nginx-ingress-integrator](https://charmhub.io/nginx-ingress-integrator/).

    juju deploy nginx-ingress-integrator
    juju relate gunicorn-k8s:ingress nginx-ingress-integrator:ingress

Once the deployment has completed and the "gunicorn-k8s" workload state in
`juju status` has changed to "active" you can visit `http://gunicorn` in
a browser (assuming `gunicorn` resolves to the IP(s) of your k8s ingress) or the juju unit's
(gunicorn-k8s) assigned IP, and you'll be presented with a screen
that details all the environment variables used by the deployed docker image.

## Using your own image

You can, of course, supply our own OCI image. To do so, specify 
`--resource gunicorn-image='image-location'` at deploy time,
or use `juju attach-resource` if you want to switch images after
initial deployment. Gunicorn is expected to listen on
port 8080 by default, but you can configure your own port if needed via
the juju config `external_port` option.

For further details,
[see the charm's detailed documentation](https://charmhub.io/gunicorn-k8s/docs).
