import os
import time
from typing import Dict

from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response


BACKEND_NAME = os.getenv("BACKEND_NAME", "unknown")
VENDOR = os.getenv("VENDOR", "unknown")

app = FastAPI(title=f"HetroServe Mock Backend - {BACKEND_NAME}")


class GenerateRequest(BaseModel):
    prompt: str = "hello"
    max_tokens: int = 32


class ControlRequest(BaseModel):
    latency_ms: float | None = None
    queue_depth: int | None = None
    cost_per_1k_tokens: float | None = None
    healthy: bool | None = None


state: Dict[str, float | int | bool] = {
    "latency_ms": float(os.getenv("BASE_LATENCY_MS", "120")),
    "queue_depth": int(os.getenv("QUEUE_DEPTH", "0")),
    "cost_per_1k_tokens": float(os.getenv("COST_PER_1K_TOKENS", "0.01")),
    "healthy": True,
}


REQUESTS = Counter(
    "hetroserve_backend_requests_total",
    "Total backend generate requests",
    ["backend", "vendor"],
)

GENERATE_LATENCY = Histogram(
    "hetroserve_backend_generate_latency_seconds",
    "Backend generate latency in seconds",
    ["backend", "vendor"],
)

COST = Gauge(
    "hetroserve_backend_cost_per_1k_tokens",
    "Backend cost per 1K tokens",
    ["backend", "vendor"],
)

QUEUE_DEPTH = Gauge(
    "hetroserve_backend_queue_depth",
    "Backend queue depth",
    ["backend", "vendor"],
)

HEALTH = Gauge(
    "hetroserve_backend_health",
    "Backend health status. 1 healthy, 0 unhealthy",
    ["backend", "vendor"],
)


def update_gauges() -> None:
    COST.labels(BACKEND_NAME, VENDOR).set(float(state["cost_per_1k_tokens"]))
    QUEUE_DEPTH.labels(BACKEND_NAME, VENDOR).set(int(state["queue_depth"]))
    HEALTH.labels(BACKEND_NAME, VENDOR).set(1 if bool(state["healthy"]) else 0)


@app.on_event("startup")
def startup() -> None:
    update_gauges()


@app.get("/health")
def health():
    update_gauges()
    if not bool(state["healthy"]):
        return {
            "status": "unhealthy",
            "backend": BACKEND_NAME,
            "vendor": VENDOR,
        }

    return {
        "status": "ok",
        "backend": BACKEND_NAME,
        "vendor": VENDOR,
    }


@app.get("/metrics-json")
def metrics_json():
    update_gauges()
    return {
        "backend": BACKEND_NAME,
        "vendor": VENDOR,
        "latency_ms": float(state["latency_ms"]),
        "queue_depth": int(state["queue_depth"]),
        "cost_per_1k_tokens": float(state["cost_per_1k_tokens"]),
        "healthy": bool(state["healthy"]),
    }


@app.post("/control")
def set_control(req: ControlRequest):
    if req.latency_ms is not None:
        state["latency_ms"] = req.latency_ms

    if req.queue_depth is not None:
        state["queue_depth"] = req.queue_depth

    if req.cost_per_1k_tokens is not None:
        state["cost_per_1k_tokens"] = req.cost_per_1k_tokens

    if req.healthy is not None:
        state["healthy"] = req.healthy

    update_gauges()

    return {
        "status": "updated",
        "backend": BACKEND_NAME,
        "vendor": VENDOR,
        "control": state,
    }


@app.get("/control")
def get_control():
    update_gauges()
    return {
        "backend": BACKEND_NAME,
        "vendor": VENDOR,
        "control": state,
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    update_gauges()

    if not bool(state["healthy"]):
        return {
            "error": "backend_unhealthy",
            "backend": BACKEND_NAME,
            "vendor": VENDOR,
        }

    REQUESTS.labels(BACKEND_NAME, VENDOR).inc()

    latency_seconds = float(state["latency_ms"]) / 1000.0

    with GENERATE_LATENCY.labels(BACKEND_NAME, VENDOR).time():
        time.sleep(latency_seconds)

    return {
        "backend": BACKEND_NAME,
        "vendor": VENDOR,
        "model": f"{VENDOR}-mock-model",
        "text": f"Response from {BACKEND_NAME}: {req.prompt}",
        "latency_ms": float(state["latency_ms"]),
        "queue_depth": int(state["queue_depth"]),
        "cost_per_1k_tokens": float(state["cost_per_1k_tokens"]),
    }


@app.get("/metrics")
def metrics():
    update_gauges()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
