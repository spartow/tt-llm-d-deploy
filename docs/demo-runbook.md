# HetroServe Demo Runbook

This runbook reproduces the local HetroServe demo on WSL2, Docker, kind, and Kubernetes.

HetroServe demonstrates vendor-neutral heterogeneous LLM inference routing across multiple backend classes using:

- Router API
- EPP-style scorer
- Redis queue
- Queue workers
- KEDA Redis autoscaling
- Mock NVIDIA backend
- Mock Tenstorrent backend
- Prometheus/Grafana observability

## 1. Environment

Expected local environment:

```text
OS: WSL2
Container runtime: Docker
Kubernetes: kind
kind cluster: hetroserve-dev
kubectl context: kind-hetroserve-dev
namespace: hetroserve-demo
deploy repo: ~/hetroserve/tt-llm-d-deploy
scorer repo: ~/hetroserve/tt-llm-d-scorer
GitHub branch: main
