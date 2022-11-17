#!/usr/bin/bash

# This charm uses both LXC and microk8s for the integration tests
# The workflow is configured with lxc provider, therefore we need
# to install microk8s manually in this script
sudo snap install microk8s --classic
sudo microk8s status --wait-ready
sudo microk8s enable dns hostpath-storage
sudo usermod -a -G microk8s "$USER"
sudo chown -f -R "$USER" ~/.kube
sudo microk8s kubectl -n kube-system rollout status -w deployment/hostpath-provisioner
sudo microk8s kubectl -n kube-system rollout status -w deployment/coredns
# Adding authentication for ghcr.io for containerd as per https://microk8s.io/docs/registry-private
# Note: containerd has to be restarted for the changes to take effect
# (https://github.com/containerd/cri/blob/master/docs/registry.md)
sudo cat << "EOF"
[plugins."io.containerd.grpc.v1.cri".registry.configs."ghcr.io".auth]
username = "${GITHUB_ACTOR}"
password = "${GITHUB_TOKEN}"
EOF >> /var/snap/microk8s/current/args/containerd-template.toml
cat /var/snap/microk8s/current/args/containerd-template.toml
sudo systemctl restart snap.microk8s.daemon-containerd.service
microk8s status --wait-ready
sg microk8s -c "juju bootstrap microk8s k8s-ctrl"
juju add-model testing
