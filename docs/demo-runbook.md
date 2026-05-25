# HetroServe Demo Runbook

This runbook demonstrates HetroServe as a vendor-neutral heterogeneous LLM inference routing platform.

## Goal

Show that HetroServe can:

1. Accept an OpenAI-style generation request.
2. Build a scorer-compatible routing decision.
3. Use live backend control metrics.
4. Select a backend queue.
5. Enqueue through Redis.
6. Receive a worker result.
7. Run in production-safe mode with debug endpoints disabled.

## Environment

- kind cluster: `hetroserve-dev`
- kubectl context: `kind-hetroserve-dev`
- namespace: `hetroserve-demo`
- router service: `hetroserve-router`
- scorer service: `hetroserve-scorer`
- Redis service: `hetroserve-redis`

## Router Configuration

Expected router environment:

```text
ROUTING_MODE=redis_queue
SCORER_MODE=epp
SCORER_URL=http://hetroserve-scorer:8080
REDIS_URL=redis://hetroserve-redis:6379/0
ENABLE_DEBUG_ENDPOINTS=false
