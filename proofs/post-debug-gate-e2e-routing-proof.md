# Post-Debug-Gate E2E Routing Proof

## Goal

Verify that after debug endpoint gating and router redeploy, the production-like `/v1/generate` path still works end-to-end.

## Path Verified

client -> router -> live backend /control metrics -> scorer /epp/pick -> Redis queue -> worker -> backend -> router response

## Environment

- kind cluster: hetroserve-dev
- namespace: hetroserve-demo
- router routing mode: redis_queue
- scorer mode: epp
- scorer endpoint: /epp/pick
- debug endpoints enabled for kind proof only

## Commands Used

```bash
curl -s http://localhost:8080/health | jq
