# HetroServe EPP-Style Scorer Kubernetes Proof

## Milestone

Implemented and deployed an EPP-style scorer endpoint:

- POST /epp/pick

The legacy scorer endpoints remain backward compatible:

- GET /health
- GET /metrics
- GET /pick
- GET /score

## Kubernetes Validation

Namespace:

- hetroserve-demo

Updated service:

- hetroserve-scorer:8080

Validated path:

- client -> hetroserve-scorer -> /epp/pick

Regression validated existing path:

- client -> hetroserve-router
- router -> hetroserve-scorer /pick
- router -> Redis queue
- queue worker -> mock backend
- router returns response

## Result

The EPP-style scorer interface is available in Kubernetes while preserving the existing router behavior.
