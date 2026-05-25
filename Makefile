.RECIPEPREFIX := >

KIND_CLUSTER ?= hetroserve-dev
NAMESPACE ?= hetroserve-demo
ROUTER_IMAGE ?= hetroserve-router:local
ROUTER_SERVICE ?= hetroserve-router
ROUTER_DEPLOYMENT ?= hetroserve-router
PYTEST ?= $(shell if [ -x .venv/bin/pytest ]; then echo .venv/bin/pytest; else echo pytest; fi)

.PHONY: help test build-router load-router restart-router stop-port-forward-router port-forward-router health-router enable-debug disable-debug router-logs status route-lowest-cost route-lowest-latency route-slo-cost

help:
> @echo "HetroServe deploy commands"
> @echo "make test"
> @echo "make build-router"
> @echo "make load-router"
> @echo "make restart-router"
> @echo "make stop-port-forward-router"
> @echo "make port-forward-router"
> @echo "make health-router"
> @echo "make enable-debug"
> @echo "make disable-debug"
> @echo "make router-logs"
> @echo "make status"

test:
> $(PYTEST) -q

build-router:
> docker build -t $(ROUTER_IMAGE) -f router/Dockerfile router

load-router:
> kind load docker-image $(ROUTER_IMAGE) --name $(KIND_CLUSTER)

restart-router:
> kubectl rollout restart deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)
> kubectl rollout status deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)

stop-port-forward-router:
> -pkill -f "kubectl port-forward -n $(NAMESPACE) svc/$(ROUTER_SERVICE) 8080:8080"

port-forward-router:
> kubectl port-forward -n $(NAMESPACE) svc/$(ROUTER_SERVICE) 8080:8080

health-router:
> curl -s http://localhost:8080/health | jq

enable-debug:
> kubectl set env deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE) ENABLE_DEBUG_ENDPOINTS=true
> kubectl rollout status deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)

disable-debug:
> kubectl set env deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE) ENABLE_DEBUG_ENDPOINTS=false
> kubectl rollout status deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)

router-logs:
> ROUTER_POD=$$(kubectl get pods -n $(NAMESPACE) -l app=$(ROUTER_DEPLOYMENT) -o jsonpath='{.items[0].metadata.name}'); kubectl logs -n $(NAMESPACE) "$$ROUTER_POD" --tail=100

status:
> kubectl get pods -n $(NAMESPACE)
> git status --short

route-lowest-cost:
> python benchmark/route_decision.py --policy lowest-cost --input-file benchmark/results/latest.csv

route-lowest-latency:
> python benchmark/route_decision.py --policy lowest-latency --input-file benchmark/results/latest.csv

route-slo-cost:
> python benchmark/route_decision.py --policy slo-aware-cost --latency-slo-ms 800 --input-file benchmark/results/latest.csv
