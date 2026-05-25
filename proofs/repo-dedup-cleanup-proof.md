# Repo Deduplication Cleanup Proof

## Goal

Remove stale duplicate files so the repository has one clear source of truth for router, mock backend, Kubernetes manifests, and benchmark code.

## Removed stale paths

```text
apps/router/
apps/mock-endpoint/
mock-backend/app.py
k8s/router.yaml
k8s/mock-backends.yaml
benchmarks/
