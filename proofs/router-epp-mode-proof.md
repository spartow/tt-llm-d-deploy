# HetroServe Router EPP Mode Proof

## Milestone

The HetroServe router now supports an EPP-style scorer path.

## Configuration

Router environment variable:

- SCORER_MODE=epp

When enabled, the router calls:

- POST http://hetroserve-scorer:8080/epp/pick

instead of the legacy:

- GET http://hetroserve-scorer:8080/pick

## Validated Kubernetes Path

Validated request path:

- client
- hetroserve-router /v1/generate
- hetroserve-scorer /epp/pick
- Redis queue
- queue worker
- mock backend
- router response

## Evidence

The router response included:

- routing_mode: redis_queue
- selected_backend: tenstorrent
- selected_vendor: tenstorrent
- queue: queue:tenstorrent
- scorer.endpoint: /epp/pick

## Result

Router EPP scorer mode is active and preserves the Redis queue worker path.
