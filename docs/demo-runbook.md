# HetroServe Local Demo Runbook

This runbook verifies the local Kubernetes demo path:

```text
client -> router -> live /control metrics -> scorer /epp/pick -> Redis queue -> worker -> backend -> router response
