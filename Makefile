KIND_CLUSTER ?= hetroserve-dev
NAMESPACE ?= hetroserve-demo
ROUTER_IMAGE ?= hetroserve-router:local
ROUTER_SERVICE ?= hetroserve-router
ROUTER_DEPLOYMENT ?= hetroserve-router

.PHONY: help test build-router load-router restart-router port-forward-router health-router enable-debug disable-debug router-logs status

help:
	@echo "HetroServe deploy commands"
	@echo ""
	@echo "make test                 Run local tests"
	@echo "make build-router         Build local router Docker image"
	@echo "make load-router          Load router image into kind"
	@echo "make restart-router       Restart router deployment"
	@echo "make port-forward-router  Port-forward router service to localhost:8080"
	@echo "make health-router        Curl router health endpoint"
	@echo "make enable-debug         Enable router debug endpoints"
	@echo "make disable-debug        Disable router debug endpoints"
	@echo "make router-logs          Tail router logs"
	@echo "make status               Show pods and git status"

test:
	pytest -q

build-router:
	docker build -t $(ROUTER_IMAGE) -f router/Dockerfile .

load-router:
	kind load docker-image $(ROUTER_IMAGE) --name $(KIND_CLUSTER)

restart-router:
	kubectl rollout restart deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)
	kubectl rollout status deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)

port-forward-router:
	pkill -f "kubectl port-forward.*$(ROUTER_SERVICE)" || true
	kubectl port-forward -n $(NAMESPACE) svc/$(ROUTER_SERVICE) 8080:8080

health-router:
	curl -s http://localhost:8080/health | jq

enable-debug:
	kubectl set env deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE) ENABLE_DEBUG_ENDPOINTS=true
	kubectl rollout status deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)

disable-debug:
	kubectl set env deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE) ENABLE_DEBUG_ENDPOINTS=false
	kubectl rollout status deployment/$(ROUTER_DEPLOYMENT) -n $(NAMESPACE)

router-logs:
	ROUTER_POD=$$(kubectl get pods -n $(NAMESPACE) -l app=$(ROUTER_DEPLOYMENT) -o jsonpath='{.items[0].metadata.name}'); \
	kubectl logs -n $(NAMESPACE) "$$ROUTER_POD" --tail=100

status:
	kubectl get pods -n $(NAMESPACE)
	git status --short
