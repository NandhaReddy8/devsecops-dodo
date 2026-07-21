#!/usr/bin/env bash
set -e
sudo systemctl start docker >/dev/null 2>&1 || true
if ! docker inspect dodo-devsecops-control-plane >/dev/null 2>&1; then
  echo "kind containers missing entirely, nothing to restart"
  exit 1
fi
STATUS=$(docker inspect -f "{{.State.Status}}" dodo-devsecops-control-plane)
if [ "$STATUS" != "running" ]; then
  docker start dodo-devsecops-control-plane dodo-devsecops-worker >/dev/null
  sleep 6
fi
kind export kubeconfig --name dodo-devsecops >/dev/null
for i in $(seq 1 30); do
  kubectl get nodes >/dev/null 2>&1 && break
  sleep 2
done
kubectl get nodes
