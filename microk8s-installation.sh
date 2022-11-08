#!/usr/bin/bash
sudo snap install microk8s --classic
sudo microk8s status --wait-ready
sudo microk8s enable dns hostpath-storage registry
sudo usermod -a -G microk8s $USER
sudo chown -f -R $USER ~/.kube
sudo microk8s kubectl -n kube-system rollout status -w deployment/hostpath-provisioner
sudo microk8s kubectl -n kube-system rollout status -w deployment/coredns
sudo microk8s kubectl -n container-registry rollout status -w deployment/registry
sg microk8s -c "juju bootstrap microk8s k8s-ctrl"
juju add-model testing
for image_name in $(echo '${{ needs.get-images.outputs.images }}' | jq -cr '.[]'); do
    docker load --input ${image_name}/${image_name}.tar
    docker push localhost:32000/${image_name}:latest
done