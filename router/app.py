import json
import logging
import os
import time
import uuid
from typing import Any, Dict

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response


app = FastAPI(title="HetroServe Router", version="0.1.0")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("hetroserve-router")

def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True))


LAST_EPP_REQUEST: Dict[str, Any] = {}

SCORER_URL = os.getenv("SCORER_URL", "http://hetroserve-scorer:8080")
SCORER_MODE = os.getenv("SCORER_MODE", "legacy").lower()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
ROUTING_MODE = os.getenv("ROUTING_MODE", "direct").lower()

NVIDIA_URL = os.getenv("NVIDIA_URL", "http://mock-nvidia:8000")
TENSTORRENT_URL = os.getenv("TENSTORRENT_URL", "http://mock-tenstorrent:8000")

CONTROL_TIMEOUT_SECONDS = float(os.getenv("CONTROL_TIMEOUT_SECONDS", "2"))
ENABLE_DEBUG_ENDPOINTS = os.getenv("ENABLE_DEBUG_ENDPOINTS", "false").lower() == "true"

REQUEST_COUNT = Counter(
    "hetroserve_router_requests_total",
    "Total router requests",
    ["endpoint", "selected_backend", "selected_vendor"],
)

REQUEST_LATENCY = Histogram(
    "hetroserve_router_request_latency_seconds",
    "Router request latency",
    ["endpoint", "selected_backend", "selected_vendor"],
)


class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 64


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionsRequest(BaseModel):
    model: str = "hetroserve-auto"
    messages: list[ChatMessage]
    max_tokens: int = 64


def require_debug_enabled() -> None:
    if not ENABLE_DEBUG_ENDPOINTS:
        raise HTTPException(
            status_code=404,
            detail="Not Found",
        )


def backend_env_defaults() -> Dict[str, Dict[str, Any]]:
    return {
        "nvidia": {
            "name": "nvidia",
            "url": NVIDIA_URL,
            "vendor": "nvidia",
            "model": os.getenv("NVIDIA_MODEL", "demo-llm"),
            "latency_ms": float(os.getenv("NVIDIA_LATENCY_MS", "120")),
            "queue_depth": int(os.getenv("NVIDIA_QUEUE_DEPTH", "2")),
            "cost_per_1k_tokens": float(os.getenv("NVIDIA_COST_PER_1K_TOKENS", "0.02")),
            "healthy": os.getenv("NVIDIA_HEALTHY", "true").lower() == "true",
            "metrics_source": "env_fallback",
        },
        "tenstorrent": {
            "name": "tenstorrent",
            "url": TENSTORRENT_URL,
            "vendor": "tenstorrent",
            "model": os.getenv("TENSTORRENT_MODEL", "demo-llm"),
            "latency_ms": float(os.getenv("TENSTORRENT_LATENCY_MS", "180")),
            "queue_depth": int(os.getenv("TENSTORRENT_QUEUE_DEPTH", "1")),
            "cost_per_1k_tokens": float(os.getenv("TENSTORRENT_COST_PER_1K_TOKENS", "0.006")),
            "healthy": os.getenv("TENSTORRENT_HEALTHY", "true").lower() == "true",
            "metrics_source": "env_fallback",
        },
    }


def fetch_backend_control(name: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch live backend metrics from /control.

    Expected backend response:
    {
      "backend": "tenstorrent",
      "vendor": "tenstorrent",
      "control": {
        "latency_ms": 180.0,
        "queue_depth": 1,
        "cost_per_1k_tokens": 0.006,
        "healthy": true
      }
    }

    If /control fails or is malformed, return env fallback defaults.
    """
    try:
        response = requests.get(
            f"{defaults['url']}/control",
            timeout=CONTROL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        control = payload.get("control", {})
        if not isinstance(control, dict):
            raise ValueError("control payload is not an object")

        return {
            "name": payload.get("backend", defaults["name"]),
            "url": defaults["url"],
            "vendor": payload.get("vendor", defaults["vendor"]),
            "model": defaults["model"],
            "latency_ms": float(control.get("latency_ms", defaults["latency_ms"])),
            "queue_depth": int(control.get("queue_depth", defaults["queue_depth"])),
            "cost_per_1k_tokens": float(
                control.get("cost_per_1k_tokens", defaults["cost_per_1k_tokens"])
            ),
            "healthy": bool(control.get("healthy", defaults["healthy"])),
            "metrics_source": "live_control",
        }

    except Exception as exc:
        fallback = dict(defaults)
        fallback["control_error"] = str(exc)
        fallback["metrics_source"] = "env_fallback"
        return fallback


def build_epp_request() -> Dict[str, Any]:
    defaults = backend_env_defaults()

    nvidia = fetch_backend_control("nvidia", defaults["nvidia"])
    tenstorrent = fetch_backend_control("tenstorrent", defaults["tenstorrent"])

    return {
        "request_id": str(uuid.uuid4()),
        "timestamp_ms": int(time.time() * 1000),
        "policy": "cost_latency_score",
        "latency_slo_ms": float(os.getenv("LATENCY_SLO_MS", "800")),
        "endpoints": [
            nvidia,
            tenstorrent,
        ],
    }


def call_scorer() -> Dict[str, Any]:
    global LAST_EPP_REQUEST

    if SCORER_MODE == "epp":
        epp_request = build_epp_request()
        LAST_EPP_REQUEST = epp_request

        logger.info(
            "EPP request payload: %s",
            json.dumps(epp_request, sort_keys=True),
        )

        scorer_payload = {
            "request_id": epp_request.get("request_id", "router-epp-pick"),
            "model": "demo-llm",
            "tenant": "demo",
            "strategy": epp_request.get("policy", "cost_latency_score"),
            "latency_slo_ms": epp_request.get("latency_slo_ms", 800.0),
            "endpoints": [
                {
                    "name": endpoint["name"],
                    "url": endpoint["url"],
                    "vendor": endpoint["vendor"],
                    "model": endpoint.get("model", "demo-llm"),
                    "metrics": {
                        "latency_ms": endpoint.get("latency_ms", 9999.0),
                        "queue_depth": endpoint.get("queue_depth", 9999),
                        "cost_per_1k_tokens": endpoint.get("cost_per_1k_tokens", 1.0),
                        "healthy": endpoint.get("healthy", False),
                    },
                }
                for endpoint in epp_request.get("endpoints", [])
            ],
        }

        response = requests.post(
            f"{SCORER_URL}/epp/pick",
            json=scorer_payload,
            timeout=10,
        )
        response.raise_for_status()
        scorer_response = response.json()
        scorer_response["endpoint"] = "/epp/pick"
        return scorer_response

    response = requests.get(f"{SCORER_URL}/pick", timeout=10)
    response.raise_for_status()
    scorer_response = response.json()
    scorer_response["endpoint"] = "/pick"
    return scorer_response


def selected_from_scorer(scorer_response: Dict[str, Any]) -> Dict[str, Any]:
    selected = (
        scorer_response.get("selected")
        or scorer_response.get("winner")
        or {}
    )

    return {
        "name": selected.get("name", "unknown"),
        "vendor": selected.get("vendor", "unknown"),
        "url": selected.get("url"),
    }


def call_backend_generate(backend: Dict[str, Any], prompt: str, max_tokens: int) -> Dict[str, Any]:
    backend_url = backend.get("url")
    if not backend_url:
        raise RuntimeError("Selected backend did not include url")

    response = requests.post(
        f"{backend_url}/generate",
        json={"prompt": prompt, "max_tokens": max_tokens},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def queue_name_for_backend(backend_name: str) -> str:
    return f"queue:{backend_name}"


def call_backend_via_redis_queue(
    backend: Dict[str, Any],
    prompt: str,
    max_tokens: int,
) -> Dict[str, Any]:
    import redis

    backend_name = backend.get("name", "unknown")
    job_id = f"job-{int(time.time() * 1000)}"
    request_id = job_id
    queue_name = queue_name_for_backend(backend_name)
    response_key = f"result:{job_id}"

    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    job = {
        "job_id": job_id,
        "request_id": request_id,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "backend": backend_name,
        "backend_url": backend.get("url", ""),
    }

    log_event(
        "redis_job_created",
        selected_backend=backend_name,
        selected_vendor=backend.get("vendor", "unknown"),
        queue=queue_name,
        job_id=job_id,
        request_id=request_id,
        result_key=response_key,
    )

    client.rpush(queue_name, json.dumps(job))

    deadline = time.time() + 30
    while time.time() < deadline:
        raw = client.get(response_key)
        if raw:
            log_event(
                "redis_job_completed",
                selected_backend=backend_name,
                selected_vendor=backend.get("vendor", "unknown"),
                queue=queue_name,
                job_id=job_id,
                request_id=request_id,
                result_key=response_key,
            )
            client.delete(response_key)
            return json.loads(raw)
        time.sleep(0.1)

    raise TimeoutError(f"Timed out waiting for worker response on {response_key}")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "hetroserve-router",
        "routing_mode": ROUTING_MODE,
        "scorer_mode": SCORER_MODE,
        "scorer_url": SCORER_URL,
    }


@app.get("/debug/epp-request")
def debug_epp_request() -> Dict[str, Any]:
    require_debug_enabled()

    """
    Returns the latest EPP request payload generated by the router.

    This is for local/kind proof only. In production, this should be protected,
    disabled, or removed.
    """
    if not LAST_EPP_REQUEST:
        return {
            "status": "empty",
            "message": "No EPP request has been generated yet.",
        }

    return {
        "status": "ok",
        "latest_epp_request": LAST_EPP_REQUEST,
    }


@app.get("/debug/routing-decision")
def debug_routing_decision() -> Dict[str, Any]:
    require_debug_enabled()

    """
    Preview the full router decision path without enqueueing a Redis job.

    Shows:
    - raw debug EPP payload generated from live/fallback backend metrics
    - scorer-compatible nested EPP payload
    - scorer response
    - selected backend/vendor
    - queue name that would be used
    """
    raw_payload = build_epp_request()

    scorer_compatible_payload = {
        "request": {
            "request_id": raw_payload.get("request_id"),
            "model": raw_payload.get("model"),
            "prompt_tokens": raw_payload.get("prompt_tokens"),
            "max_tokens": raw_payload.get("max_tokens"),
        },
        "endpoints": [],
    }

    for endpoint in raw_payload.get("endpoints", []):
        scorer_compatible_payload["endpoints"].append(
            {
                "name": endpoint.get("name"),
                "url": endpoint.get("url"),
                "vendor": endpoint.get("vendor"),
                "model": endpoint.get("model"),
                "metrics": {
                    "latency_ms": endpoint.get("latency_ms"),
                    "queue_depth": endpoint.get("queue_depth"),
                    "cost_per_1k_tokens": endpoint.get("cost_per_1k_tokens"),
                    "healthy": endpoint.get("healthy"),
                    "metrics_source": endpoint.get("metrics_source"),
                },
            }
        )

    scorer_endpoint = "/pick"

    if SCORER_MODE == "epp":
        scorer_endpoint = "/epp/pick"
        scorer_http_response = requests.post(
            f"{SCORER_URL.rstrip('/')}{scorer_endpoint}",
            json=scorer_compatible_payload,
            timeout=5,
        )
    else:
        scorer_http_response = requests.get(
            f"{SCORER_URL.rstrip('/')}{scorer_endpoint}",
            timeout=5,
        )

    scorer_http_response.raise_for_status()
    scorer_response = scorer_http_response.json()

    selected_backend = selected_from_scorer(scorer_response)
    queue = queue_name_for_backend(selected_backend["name"])

    return {
        "status": "ok",
        "routing_mode": ROUTING_MODE,
        "scorer_mode": SCORER_MODE,
        "scorer_url": SCORER_URL,
        "scorer_endpoint": scorer_endpoint,
        "raw_debug_epp_payload": raw_payload,
        "scorer_compatible_payload": scorer_compatible_payload,
        "scorer_response": scorer_response,
        "selected_backend": selected_backend["name"],
        "selected_vendor": selected_backend["vendor"],
        "queue": queue,
        "would_enqueue": ROUTING_MODE == "redis_queue",
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/generate")
def generate(request: GenerateRequest) -> Dict[str, Any]:
    start = time.time()
    scorer_response = call_scorer()
    selected_backend = selected_from_scorer(scorer_response)

    scorer_endpoint = "/epp/pick" if SCORER_MODE == "epp" else "/pick"
    planned_queue = (
        queue_name_for_backend(selected_backend["name"])
        if ROUTING_MODE == "redis_queue"
        else None
    )

    log_event(
        "routing_decision",
        routing_mode=ROUTING_MODE,
        scorer_mode=SCORER_MODE,
        scorer_endpoint=scorer_endpoint,
        selected_backend=selected_backend["name"],
        selected_vendor=selected_backend["vendor"],
        queue=planned_queue,
    )

    if ROUTING_MODE == "redis_queue":
        backend_response = call_backend_via_redis_queue(
            selected_backend,
            request.prompt,
            request.max_tokens,
        )
        queue = queue_name_for_backend(selected_backend["name"])
    else:
        backend_response = call_backend_generate(
            selected_backend,
            request.prompt,
            request.max_tokens,
        )
        queue = None

    elapsed = time.time() - start

    REQUEST_COUNT.labels(
        endpoint="/v1/generate",
        selected_backend=selected_backend["name"],
        selected_vendor=selected_backend["vendor"],
    ).inc()

    REQUEST_LATENCY.labels(
        endpoint="/v1/generate",
        selected_backend=selected_backend["name"],
        selected_vendor=selected_backend["vendor"],
    ).observe(elapsed)

    return {
        "id": str(uuid.uuid4()),
        "object": "text_completion",
        "selected_backend": selected_backend["name"],
        "selected_vendor": selected_backend["vendor"],
        "queue": queue,
        "scorer": scorer_response,
        "backend_response": backend_response,
    }


@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionsRequest) -> Dict[str, Any]:
    prompt = "\n".join([f"{m.role}: {m.content}" for m in request.messages])

    generate_response = generate(
        GenerateRequest(prompt=prompt, max_tokens=request.max_tokens)
    )

    return {
        "id": generate_response["id"],
        "object": "chat.completion",
        "model": request.model,
        "selected_backend": generate_response["selected_backend"],
        "selected_vendor": generate_response["selected_vendor"],
        "queue": generate_response["queue"],
        "scorer": generate_response["scorer"],
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": str(generate_response["backend_response"]),
                },
                "finish_reason": "stop",
            }
        ],
    }
