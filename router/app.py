import os
import time
import uuid
from typing import Any, Dict, List

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="HetroServe Router")

SCORER_URL = os.getenv(
    "SCORER_URL",
    "http://hetroserve-scorer:8080",
)

REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))


def call_scorer_pick() -> Dict[str, Any]:
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

    return pick_data


def call_backend_generate(
    backend_url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    generate_url = backend_url.rstrip("/") + "/generate"

    try:
        backend_response = requests.post(
            generate_url,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        backend_response.raise_for_status()
        return backend_response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to forward request to backend {generate_url}: {exc}",
        )


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
    payload: Dict[str, Any] = await request.json()

    pick_data = call_scorer_pick()
    winner = pick_data["winner"]
    backend_url = winner["url"]

    backend_data = call_backend_generate(backend_url, payload)

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
    openai_payload: Dict[str, Any] = await request.json()

    messages = openai_payload.get("messages", [])
    if not messages:
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

    pick_data = call_scorer_pick()
    winner = pick_data["winner"]
    backend_url = winner["url"]

    backend_data = call_backend_generate(backend_url, backend_payload)
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
