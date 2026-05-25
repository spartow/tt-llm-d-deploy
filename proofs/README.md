# HetroServe Proof Milestones

This directory contains proof artifacts for HetroServe's local Kubernetes demo.

HetroServe is a vendor-neutral heterogeneous LLM inference platform that demonstrates:

- live backend telemetry collection
- EPP-based backend selection
- Redis queue dispatch
- worker-to-backend execution
- Prometheus/Grafana observability
- KEDA Redis autoscaling
- gated debug endpoints for local proof workflows

## Current Verified Path

```text
client
  -> router
  -> live backend /control metrics
  -> scorer /epp/pick
  -> Redis queue
  -> worker
  -> backend
  -> router response
