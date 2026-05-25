#!/usr/bin/env bash
set -euo pipefail

ROUTER_URL="${ROUTER_URL:-http://localhost:8080}"

echo "Checking router health..."
curl -fsS "$ROUTER_URL/health" | jq

echo "Checking EPP request debug payload..."
curl -fsS "$ROUTER_URL/debug/epp-request" | jq

echo "Checking routing decision..."
curl -fsS "$ROUTER_URL/debug/routing-decision" | jq

echo "Debug routing proof completed."
