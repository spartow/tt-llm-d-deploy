import os
import requests
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="HetroServe Router")

SCORER_URL = os.getenv("SCORER_URL", "http://hetroserve-scorer:8080")


class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 64


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "hetroserve-router",
    }


@app.post("/v1/generate")
def generate(req: GenerateRequest):
    pick_response = requests.get(f"{SCORER_URL}/pick", timeout=5)
    pick_response.raise_for_status()

    pick = pick_response.json()
    winner = pick["winner"]

    backend_url = winner["url"]

    backend_response = requests.post(
        f"{backend_url}/generate",
        json={
            "prompt": req.prompt,
            "max_tokens": req.max_tokens,
        },
        timeout=60,
    )
    backend_response.raise_for_status()

    backend_data = backend_response.json()

    return {
        "router": "hetroserve-router",
        "selected_backend": {
            "name": winner["name"],
            "vendor": winner["vendor"],
            "model": winner["model"],
            "score": winner["score"],
            "estimated_latency_ms": winner["estimated_latency_ms"],
            "estimated_cost": winner["estimated_cost"],
        },
        "scoring_policy": pick["policy"],
        "response": backend_data,
    }
