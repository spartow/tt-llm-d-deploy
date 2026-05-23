import os
import time
import uuid
from typing import Any, Dict, List

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = FastAPI(title="HetroServe Router")

SCORER_URL = os.getenv(
    "SCORER_URL",
    "http://hetroserve-scorer:8080",
)

REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))


REQUESTS_TOTAL = Counter(
    "hetroserve_router_requests_total",
    "Total requests handled by HetroServe router",
    ["endpoint"],
)

SELECTED_BACKEND_TOTAL = Counter(
    "hetroserve_router_selected_backend_total",
    "Total routing selections by backend",
    ["backend", "vendor"],
)

ERRORS_TOTAL = Counter(
    "hetroserve_router_errors_total",
    "Total router errors",
    ["endpoint", "error_type"],
)

SCORER_LATENCY_SECONDS = Histogram(
    "hetroserve_router_scorer_latency_seconds",
    "Latency for scorer /pick calls",
)

BACKEND_LATENCY_SECONDS = Histogram(
    "hetroserve_router_backend_latency_seconds",
    "Latency for selected backend /generate calls",
    ["backend", "vendor"],
)


@app.get("/metrics")
def metrics() -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


def call_scorer_pick(endpoint: str) -> Dict[str, Any]:
    start = time.time()

    try:
        pick_response = requests.get(
            f"{SCORER_URL}/pick",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        pick_response.raise_for_status()
        pick_data = pick_response.json()
    except Exception as exc:
        ERRORS_TOTAL.labels(endpoint=endpoint, error_type="scorer_pick_failed").inc()
        raise HTTPException(
            status_code=502,
            detail=f"Failed to call scorer /pick: {exc}",
        )

    finally:
        SCORER_LATENCY_SECONDS.observe(time.time() - start)

    winner = pick_data.get("winner")
    if not winner:
        ERRORS_TOTAL.labels(endpoint=endpoint, error_type="missing_winner").inc()
        raise HTTPException(
            status_code=502,
            detail=f"Scorer response missing winner: {pick_data}",
        )

    backend_url = winner.get("url")
    if not backend_url:
        ERRORS_TOTAL.labels(endpoint=endpoint, error_type="missing_backend_url").inc()
        raise HTTPException(
            status_code=502,
            detail=f"Scorer winner missing url: {winner}",
        )

    backend_name = str(winner.get("name", "unknown"))
    backend_vendor = str(winner.get("vendor", "unknown"))

    SELECTED_BACKEND_TOTAL.labels(
        backend=backend_name,
        vendor=backend_vendor,
    ).inc()

    return pick_data


def call_backend_generate(
    endpoint: str,
    backend_url: str,
    winner: Dict[str, Any],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    backend_name = str(winner.get("name", "unknown"))
    backend_vendor = str(winner.get("vendor", "unknown"))

    generate_url = backend_url.rstrip("/") + "/generate"

    start = time.time()

    try:
        backend_response = requests.post(
            generate_url,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        backend_response.raise_for_status()
        return backend_response.json()
    except Exception as exc:
        ERRORS_TOTAL.labels(endpoint=endpoint, error_type="backend_generate_failed").inc()
        raise HTTPException(
            status_code=502,
            detail=f"Failed to forward request to backend {generate_url}: {exc}",
        )

    finally:
        BACKEND_LATENCY_SECONDS.labels(
            backend=backend_name,
            vendor=backend_vendor,
        ).observe(time.time() - start)


def messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    lines = []

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            content = " ".join(text_parts)

        lines.append(f"{role}: {content}")

    lines.append("assistant:")
    return "\n".join(lines)


def extract_text_from_backend_response(data: Dict[str, Any]) -> str:
    if "text" in data:
        return str(data["text"])

    if "response" in data:
        return str(data["response"])

    if "generated_text" in data:
        return str(data["generated_text"])

    if "output" in data:
        return str(data["output"])

    if "message" in data:
        return str(data["message"])

    return str(data)


@app.get("/health")
def health() -> Dict[str, str]:
    return {
        "status": "ok",
        "service": "hetroserve-router",
        "runtime": "python-router",
    }


@app.post("/v1/generate")
async def generate(request: Request) -> JSONResponse:
    endpoint = "/v1/generate"
    REQUESTS_TOTAL.labels(endpoint=endpoint).inc()

    payload: Dict[str, Any] = await request.json()

    pick_data = call_scorer_pick(endpoint)
    winner = pick_data["winner"]
    backend_url = winner["url"]

    backend_data = call_backend_generate(
        endpoint=endpoint,
        backend_url=backend_url,
        winner=winner,
        payload=payload,
    )

    return JSONResponse(
        {
            "router": "hetroserve-router",
            "policy": pick_data.get("policy"),
            "selected_backend": {
                "name": winner.get("name"),
                "vendor": winner.get("vendor"),
                "model": winner.get("model"),
                "url": backend_url,
                "score": winner.get("score"),
            },
            "backend_response": backend_data,
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    endpoint = "/v1/chat/completions"
    REQUESTS_TOTAL.labels(endpoint=endpoint).inc()

    openai_payload: Dict[str, Any] = await request.json()

    messages = openai_payload.get("messages", [])
    if not messages:
        ERRORS_TOTAL.labels(endpoint=endpoint, error_type="missing_messages").inc()
        raise HTTPException(
            status_code=400,
            detail="Missing required field: messages",
        )

    model = openai_payload.get("model", "hetroserve-auto")
    max_tokens = openai_payload.get("max_tokens", 128)
    temperature = openai_payload.get("temperature", 0.7)

    prompt = messages_to_prompt(messages)

    backend_payload = {
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "model": model,
    }

    pick_data = call_scorer_pick(endpoint)
    winner = pick_data["winner"]
    backend_url = winner["url"]

    backend_data = call_backend_generate(
        endpoint=endpoint,
        backend_url=backend_url,
        winner=winner,
        payload=backend_payload,
    )

    generated_text = extract_text_from_backend_response(backend_data)

    response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    return JSONResponse(
        {
            "id": response_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "hetroserve": {
                "router": "hetroserve-router",
                "policy": pick_data.get("policy"),
                "selected_backend": {
                    "name": winner.get("name"),
                    "vendor": winner.get("vendor"),
                    "backend_model": winner.get("model"),
                    "url": backend_url,
                    "score": winner.get("score"),
                },
            },
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": generated_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
    )
