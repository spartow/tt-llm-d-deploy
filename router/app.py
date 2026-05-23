import os
from typing import Any, Dict

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="HetroServe Router")

SCORER_URL = os.getenv(
    "SCORER_URL",
    "http://hetroserve-scorer:8080",
)

REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))


@app.get("/health")
def health() -> Dict[str, str]:
    return {
        "status": "ok",
        "service": "hetroserve-router",
        "runtime": "python-router",
    }


@app.post("/v1/generate")
async def generate(request: Request) -> JSONResponse:
    payload: Dict[str, Any] = await request.json()

    try:
        pick_response = requests.get(
            f"{SCORER_URL}/pick",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        pick_response.raise_for_status()
        pick_data = pick_response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to call scorer /pick: {exc}",
        )

    winner = pick_data.get("winner")
    if not winner:
        raise HTTPException(
            status_code=502,
            detail=f"Scorer response missing winner: {pick_data}",
        )

    backend_url = winner.get("url")
    if not backend_url:
        raise HTTPException(
            status_code=502,
            detail=f"Scorer winner missing url: {winner}",
        )

    generate_url = backend_url.rstrip("/") + "/generate"

    try:
        backend_response = requests.post(
            generate_url,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        backend_response.raise_for_status()
        backend_data = backend_response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to forward request to backend {generate_url}: {exc}",
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
