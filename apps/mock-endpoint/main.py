import os
import time
import random
from fastapi import FastAPI
from pydantic import BaseModel

VENDOR = os.getenv("VENDOR", "unknown")
MODEL_NAME = os.getenv("MODEL_NAME", "mock-model")
BASE_LATENCY_MS = int(os.getenv("BASE_LATENCY_MS", "100"))
TOKENS_PER_SECOND = float(os.getenv("TOKENS_PER_SECOND", "50"))
COST_PER_1K_TOKENS = float(os.getenv("COST_PER_1K_TOKENS", "0.01"))

app = FastAPI(title=f"HetroServe Mock {VENDOR} Endpoint")


class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 64


@app.get("/health")
def health():
    return {
        "status": "ok",
        "vendor": VENDOR,
        "model": MODEL_NAME,
    }


@app.get("/metrics-json")
def metrics_json():
    return {
        "vendor": VENDOR,
        "model": MODEL_NAME,
        "base_latency_ms": BASE_LATENCY_MS,
        "tokens_per_second": TOKENS_PER_SECOND,
        "cost_per_1k_tokens": COST_PER_1K_TOKENS,
        "queue_depth": random.randint(0, 5),
        "kv_cache_utilization": round(random.uniform(0.10, 0.85), 2),
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    output_tokens = min(req.max_tokens, random.randint(16, req.max_tokens))

    latency_ms = BASE_LATENCY_MS + int((output_tokens / TOKENS_PER_SECOND) * 1000)
    latency_ms += random.randint(0, 40)

    time.sleep(latency_ms / 1000)

    return {
        "vendor": VENDOR,
        "model": MODEL_NAME,
        "prompt": req.prompt,
        "completion": f"Mock response from {VENDOR} for prompt: {req.prompt}",
        "input_tokens": len(req.prompt.split()),
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "tokens_per_second": TOKENS_PER_SECOND,
        "estimated_cost": round((output_tokens / 1000) * COST_PER_1K_TOKENS, 6),
    }
