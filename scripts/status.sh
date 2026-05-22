#!/usr/bin/env bash
set -euo pipefail

echo "Current context:"
kubectl config current-context

echo
echo "Namespace:"
kubectl get ns hetroserve-demo

echo
echo "Pods:"
kubectl get pods -n hetroserve-demo -o wide

echo
echo "Services:"
kubectl get svc -n hetroserve-demo

echo
echo "Mock NVIDIA health from inside cluster:"
kubectl run curl-nvidia-check \
  -n hetroserve-demo \
  --image=curlimages/curl \
  --rm -i \
  --restart=Never \
  -- curl -s http://mock-nvidia:8000/health

echo
echo
echo "Mock Tenstorrent health from inside cluster:"
kubectl run curl-tt-check \
  -n hetroserve-demo \
  --image=curlimages/curl \
  --rm -i \
  --restart=Never \
  -- curl -s http://mock-tenstorrent:8000/health

echo
