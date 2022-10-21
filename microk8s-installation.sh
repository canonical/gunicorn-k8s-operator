#!/usr/bin/bash
sudo snap install microk8s --classic
sudo microk8s.status --wait-ready
sudo microk8s.enable dns hostpath-storage
sudo usermod -a -G microk8s $USER
sudo chown -f -R $USER ~/.kube
sudo microk8s.kubectl -n kube-system rollout status -w deployment/hostpath-provisioner
sudo microk8s.kubectl -n kube-system rollout status -w deployment/coredns
sg microk8s -c "juju bootstrap microk8s k8s-ctrl"
juju switch k8s-ctrl