import json
import os
import threading
import time
from typing import Any

import redis
import requests
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REDIS_HOST = os.getenv("REDIS_HOST", "hetroserve-redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
QUEUE_NAME = os.getenv("QUEUE_NAME", "queue:nvidia")
BACKEND_NAME = os.getenv("BACKEND_NAME", "nvidia")
BACKEND_VENDOR = os.getenv("BACKEND_VENDOR", BACKEND_NAME)
BACKEND_URL = os.getenv("BACKEND_URL", "http://mock-nvidia:8000")
RESULT_TTL_SECONDS = int(os.getenv("RESULT_TTL_SECONDS", "300"))

app = FastAPI(title="HetroServe Queue Worker")

r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
)

jobs_consumed = Counter(
    "hetroserve_worker_jobs_consumed_total",
    "Total jobs consumed by queue worker",
    ["backend", "vendor", "queue"],
)

jobs_succeeded = Counter(
    "hetroserve_worker_jobs_succeeded_total",
    "Total jobs successfully processed by queue worker",
    ["backend", "vendor", "queue"],
)

jobs_failed = Counter(
    "hetroserve_worker_jobs_failed_total",
    "Total jobs failed by queue worker",
    ["backend", "vendor", "queue", "error_type"],
)

backend_latency = Histogram(
    "hetroserve_worker_backend_latency_seconds",
    "Worker backend /generate latency",
    ["backend", "vendor"],
)

queue_depth = Gauge(
    "hetroserve_worker_queue_depth",
    "Current Redis queue depth seen by worker",
    ["backend", "vendor", "queue"],
)

last_success_timestamp = Gauge(
    "hetroserve_worker_last_success_timestamp_seconds",
    "Unix timestamp of last successful job",
    ["backend", "vendor", "queue"],
)


def normalize_backend_payload(job: dict[str, Any]) -> dict[str, Any]:
    if isinstance(job.get("request"), dict):
        return job["request"]

    prompt = job.get("prompt") or job.get("input") or "hello from hetroserve queue worker"

    return {
        "prompt": prompt,
        "max_tokens": job.get("max_tokens", 64),
    }


def store_result(job_id: str, result: dict[str, Any]) -> None:
    key = f"result:{job_id}"
    r.setex(key, RESULT_TTL_SECONDS, json.dumps(result))


def process_job(raw_job: str) -> None:
    job = json.loads(raw_job)
    job_id = job.get("job_id", f"job-{int(time.time() * 1000)}")

    jobs_consumed.labels(BACKEND_NAME, BACKEND_VENDOR, QUEUE_NAME).inc()

    payload = normalize_backend_payload(job)

    started = time.time()
    response = requests.post(
        f"{BACKEND_URL}/generate",
        json=payload,
        timeout=30,
    )
    elapsed = time.time() - started

    backend_latency.labels(BACKEND_NAME, BACKEND_VENDOR).observe(elapsed)
    response.raise_for_status()

    result = {
        "job_id": job_id,
        "backend": BACKEND_NAME,
        "vendor": BACKEND_VENDOR,
        "queue": QUEUE_NAME,
        "latency_seconds": elapsed,
        "response": response.json(),
    }

    store_result(job_id, result)

    jobs_succeeded.labels(BACKEND_NAME, BACKEND_VENDOR, QUEUE_NAME).inc()
    last_success_timestamp.labels(BACKEND_NAME, BACKEND_VENDOR, QUEUE_NAME).set(time.time())

    print(json.dumps({"event": "job_processed", **result}), flush=True)


def worker_loop() -> None:
    print(
        json.dumps(
            {
                "event": "worker_started",
                "redis": f"{REDIS_HOST}:{REDIS_PORT}",
                "queue": QUEUE_NAME,
                "backend": BACKEND_NAME,
                "backend_url": BACKEND_URL,
            }
        ),
        flush=True,
    )

    while True:
        try:
            depth = r.llen(QUEUE_NAME)
            queue_depth.labels(BACKEND_NAME, BACKEND_VENDOR, QUEUE_NAME).set(depth)

            item = r.brpop(QUEUE_NAME, timeout=5)
            if item is None:
                continue

            _, raw_job = item
            process_job(raw_job)

        except json.JSONDecodeError:
            jobs_failed.labels(BACKEND_NAME, BACKEND_VENDOR, QUEUE_NAME, "bad_json").inc()
            print('{"event":"job_failed","error_type":"bad_json"}', flush=True)

        except requests.RequestException as exc:
            jobs_failed.labels(BACKEND_NAME, BACKEND_VENDOR, QUEUE_NAME, "backend_error").inc()
            print(
                json.dumps(
                    {
                        "event": "job_failed",
                        "error_type": "backend_error",
                        "error": str(exc),
                    }
                ),
                flush=True,
            )

        except Exception as exc:
            jobs_failed.labels(BACKEND_NAME, BACKEND_VENDOR, QUEUE_NAME, "unknown").inc()
            print(
                json.dumps(
                    {
                        "event": "job_failed",
                        "error_type": "unknown",
                        "error": str(exc),
                    }
                ),
                flush=True,
            )

        time.sleep(0.1)


@app.on_event("startup")
def startup_event() -> None:
    thread = threading.Thread(target=worker_loop, daemon=True)
    thread.start()


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "hetroserve-queue-worker",
        "backend": BACKEND_NAME,
        "queue": QUEUE_NAME,
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
