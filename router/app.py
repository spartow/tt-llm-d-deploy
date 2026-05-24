import json
import os
import time
import uuid
from typing import Any

import redis
import requests
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

SCORER_URL = os.getenv("SCORER_URL", "http://hetroserve-scorer:8080")
SCORER_MODE = os.getenv("SCORER_MODE", "legacy").lower()
REDIS_HOST = os.getenv("REDIS_HOST", "hetroserve-redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
RESULT_TIMEOUT_SECONDS = float(os.getenv("RESULT_TIMEOUT_SECONDS", "30"))
RESULT_POLL_INTERVAL_SECONDS = float(os.getenv("RESULT_POLL_INTERVAL_SECONDS", "0.05"))

app = FastAPI(title="HetroServe Router")

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
)

router_requests = Counter(
    "hetroserve_router_requests_total",
    "Total router requests",
    ["endpoint"],
)

router_selected_backend = Counter(
    "hetroserve_router_selected_backend_total",
    "Total selected backend count",
    ["backend", "vendor"],
)

router_errors = Counter(
    "hetroserve_router_errors_total",
    "Total router errors",
    ["endpoint", "error_type"],
)

router_scorer_latency = Histogram(
    "hetroserve_router_scorer_latency_seconds",
    "Router scorer /pick latency",
)

router_queue_wait_latency = Histogram(
    "hetroserve_router_queue_wait_latency_seconds",
    "Time router waits for Redis worker result",
    ["backend", "vendor"],
)

router_enqueue_latency = Histogram(
    "hetroserve_router_enqueue_latency_seconds",
    "Time router spends pushing job to Redis",
    ["backend", "vendor", "queue"],
)


def extract_prompt_from_chat(body: dict[str, Any]) -> str:
    messages = body.get("messages", [])
    if not messages:
        return ""

    parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        parts.append(f"{role}: {content}")

    return "\n".join(parts)



def build_epp_request() -> dict:
    return {
        "request_id": "router-epp-pick",
        "model": "demo-llm",
        "tenant": "demo",
        "strategy": "cost_latency_score",
        "latency_slo_ms": float(os.getenv("LATENCY_SLO_MS", "800")),
        "endpoints": [
            {
                "name": "nvidia",
                "url": os.getenv("NVIDIA_URL", "http://mock-nvidia:8000"),
                "vendor": "nvidia",
                "model": "demo-llm",
                "metrics": {
                    "latency_ms": float(os.getenv("NVIDIA_LATENCY_MS", "120")),
                    "queue_depth": int(os.getenv("NVIDIA_QUEUE_DEPTH", "2")),
                    "cost_per_1k_tokens": float(os.getenv("NVIDIA_COST_PER_1K_TOKENS", "0.02")),
                    "healthy": os.getenv("NVIDIA_HEALTHY", "true").lower() == "true",
                },
            },
            {
                "name": "tenstorrent",
                "url": os.getenv("TENSTORRENT_URL", "http://mock-tenstorrent:8000"),
                "vendor": "tenstorrent",
                "model": "demo-llm",
                "metrics": {
                    "latency_ms": float(os.getenv("TENSTORRENT_LATENCY_MS", "180")),
                    "queue_depth": int(os.getenv("TENSTORRENT_QUEUE_DEPTH", "1")),
                    "cost_per_1k_tokens": float(os.getenv("TENSTORRENT_COST_PER_1K_TOKENS", "0.006")),
                    "healthy": os.getenv("TENSTORRENT_HEALTHY", "true").lower() == "true",
                },
            },
        ],
    }


def call_scorer() -> dict[str, Any]:
    started = time.time()
    try:
        if SCORER_MODE == "epp":
            response = requests.post(
                f"{SCORER_URL}/epp/pick",
                json=build_epp_request(),
                timeout=10,
            )
        else:
            response = requests.get(f"{SCORER_URL}/pick", timeout=10)
        response.raise_for_status()
        return response.json()
    finally:
        router_scorer_latency.observe(time.time() - started)


def parse_winner(scorer_response: dict[str, Any]) -> dict[str, str]:
    winner = scorer_response.get("winner", scorer_response)

    backend = (
        winner.get("name")
        or winner.get("backend")
        or winner.get("id")
        or winner.get("vendor")
    )

    vendor = winner.get("vendor") or backend

    if not backend:
        raise ValueError(f"scorer response missing winner backend: {scorer_response}")

    backend = str(backend).lower()
    vendor = str(vendor).lower()

    if "tenstorrent" in backend or "tenstorrent" in vendor:
        return {
            "backend": "tenstorrent",
            "vendor": "tenstorrent",
            "queue": "queue:tenstorrent",
        }

    if "nvidia" in backend or "nvidia" in vendor:
        return {
            "backend": "nvidia",
            "vendor": "nvidia",
            "queue": "queue:nvidia",
        }

    # Safe default for unknown scorer names.
    return {
        "backend": backend,
        "vendor": vendor,
        "queue": f"queue:{backend}",
    }


def wait_for_result(job_id: str, backend: str, vendor: str) -> dict[str, Any]:
    result_key = f"result:{job_id}"
    deadline = time.time() + RESULT_TIMEOUT_SECONDS
    started = time.time()

    while time.time() < deadline:
        raw = redis_client.get(result_key)
        if raw:
            router_queue_wait_latency.labels(backend, vendor).observe(time.time() - started)
            redis_client.delete(result_key)
            return json.loads(raw)

        time.sleep(RESULT_POLL_INTERVAL_SECONDS)

    router_queue_wait_latency.labels(backend, vendor).observe(time.time() - started)
    raise TimeoutError(f"timed out waiting for Redis result {result_key}")


def enqueue_job(queue_name: str, job: dict[str, Any], backend: str, vendor: str) -> None:
    started = time.time()
    redis_client.lpush(queue_name, json.dumps(job))
    router_enqueue_latency.labels(backend, vendor, queue_name).observe(time.time() - started)


def route_via_redis(endpoint: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    router_requests.labels(endpoint).inc()

    try:
        scorer_response = call_scorer()
        selected = parse_winner(scorer_response)

        backend = selected["backend"]
        vendor = selected["vendor"]
        queue_name = selected["queue"]

        router_selected_backend.labels(backend, vendor).inc()

        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "request": request_payload,
            "selected_backend": backend,
            "selected_vendor": vendor,
            "created_at": time.time(),
        }

        enqueue_job(queue_name, job, backend, vendor)
        worker_result = wait_for_result(job_id, backend, vendor)

        return {
            "router": "hetroserve-router",
            "routing_mode": "redis_queue",
            "job_id": job_id,
            "selected_backend": backend,
            "selected_vendor": vendor,
            "queue": queue_name,
            "scorer": scorer_response,
            "worker_result": worker_result,
        }

    except TimeoutError as exc:
        router_errors.labels(endpoint, "result_timeout").inc()
        raise HTTPException(status_code=504, detail=str(exc)) from exc

    except requests.RequestException as exc:
        router_errors.labels(endpoint, "scorer_error").inc()
        raise HTTPException(status_code=502, detail=f"scorer error: {exc}") from exc

    except Exception as exc:
        router_errors.labels(endpoint, "unknown").inc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "hetroserve-router",
        "routing_mode": "redis_queue",
        "redis": f"{REDIS_HOST}:{REDIS_PORT}",
        "scorer_url": SCORER_URL,
        "scorer_mode": SCORER_MODE,
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/generate")
async def generate(request: Request) -> dict[str, Any]:
    body = await request.json()

    request_payload = {
        "prompt": body.get("prompt", ""),
        "max_tokens": body.get("max_tokens", 64),
    }

    return route_via_redis("/v1/generate", request_payload)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, Any]:
    body = await request.json()

    prompt = extract_prompt_from_chat(body)

    request_payload = {
        "prompt": prompt,
        "max_tokens": body.get("max_tokens", 64),
    }

    routed = route_via_redis("/v1/chat/completions", request_payload)

    worker_response = routed.get("worker_result", {}).get("response", {})
    text = worker_response.get("text", "")

    return {
        "id": routed["job_id"],
        "object": "chat.completion",
        "model": worker_response.get("model", body.get("model", "hetroserve-routed-model")),
        "routing": {
            "mode": routed["routing_mode"],
            "selected_backend": routed["selected_backend"],
            "selected_vendor": routed["selected_vendor"],
            "queue": routed["queue"],
        },
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": "stop",
            }
        ],
        "hetroserve": routed,
    }
