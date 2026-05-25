import importlib.util
import json
import sys
from pathlib import Path

from prometheus_client import REGISTRY


ROOT = Path(__file__).resolve().parents[1]
ROUTER_APP = ROOT / "router" / "app.py"


def clear_router_prometheus_collectors():
    collectors = list(REGISTRY._collector_to_names.keys())

    for collector in collectors:
        names = REGISTRY._collector_to_names.get(collector, [])
        if any(name.startswith("hetroserve_router_") for name in names):
            try:
                REGISTRY.unregister(collector)
            except KeyError:
                pass


def load_router_app(monkeypatch, **env):
    clear_router_prometheus_collectors()

    defaults = {
        "ROUTING_MODE": "redis_queue",
        "SCORER_MODE": "epp",
        "SCORER_URL": "http://hetroserve-scorer:8080",
        "REDIS_URL": "redis://hetroserve-redis:6379/0",
        "NVIDIA_BACKEND_URL": "http://mock-nvidia:8000",
        "TENSTORRENT_BACKEND_URL": "http://mock-tenstorrent:8000",
        "CONTROL_TIMEOUT_SECONDS": "1",
    }

    for key, value in {**defaults, **env}.items():
        monkeypatch.setenv(key, value)

    module_name = "router_app_under_test"
    sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, ROUTER_APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_build_epp_request_uses_live_control_metrics(monkeypatch):
    router = load_router_app(monkeypatch)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, timeout=1):
        if "mock-nvidia" in url:
            return FakeResponse(
                {
                    "backend": "nvidia",
                    "vendor": "nvidia",
                    "control": {
                        "latency_ms": 250,
                        "queue_depth": 4,
                        "cost_per_1k_tokens": 0.02,
                        "healthy": True,
                    },
                }
            )

        if "mock-tenstorrent" in url:
            return FakeResponse(
                {
                    "backend": "tenstorrent",
                    "vendor": "tenstorrent",
                    "control": {
                        "latency_ms": 100,
                        "queue_depth": 1,
                        "cost_per_1k_tokens": 0.005,
                        "healthy": True,
                    },
                }
            )

        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(router.requests, "get", fake_get)

    payload = router.build_epp_request()

    endpoints = {endpoint["name"]: endpoint for endpoint in payload["endpoints"]}

    assert endpoints["nvidia"]["latency_ms"] == 250
    assert endpoints["nvidia"]["queue_depth"] == 4
    assert endpoints["nvidia"]["metrics_source"] == "live_control"

    assert endpoints["tenstorrent"]["latency_ms"] == 100
    assert endpoints["tenstorrent"]["queue_depth"] == 1
    assert endpoints["tenstorrent"]["metrics_source"] == "live_control"


def test_build_epp_request_falls_back_to_env_defaults(monkeypatch):
    router = load_router_app(
        monkeypatch,
        NVIDIA_LATENCY_MS="900",
        NVIDIA_QUEUE_DEPTH="8",
        TENSTORRENT_LATENCY_MS="120",
        TENSTORRENT_QUEUE_DEPTH="2",
    )

    def fake_get(url, timeout=1):
        raise router.requests.RequestException("control unavailable")

    monkeypatch.setattr(router.requests, "get", fake_get)

    payload = router.build_epp_request()

    endpoints = {endpoint["name"]: endpoint for endpoint in payload["endpoints"]}

    assert endpoints["nvidia"]["latency_ms"] == 900.0
    assert endpoints["nvidia"]["queue_depth"] == 8
    assert endpoints["nvidia"]["metrics_source"] == "env_fallback"

    assert endpoints["tenstorrent"]["latency_ms"] == 120.0
    assert endpoints["tenstorrent"]["queue_depth"] == 2
    assert endpoints["tenstorrent"]["metrics_source"] == "env_fallback"


def test_call_scorer_posts_nested_epp_payload(monkeypatch):
    router = load_router_app(monkeypatch)

    captured = {}

    def fake_build_epp_request():
        return {
            "request_id": "router-epp-pick",
            "policy": "cost_latency_score",
            "latency_slo_ms": 800.0,
            "metrics_source": "live_control",
            "endpoints": [
                {
                    "name": "tenstorrent",
                    "url": "http://mock-tenstorrent:8000",
                    "vendor": "tenstorrent",
                    "model": "demo-model",
                    "latency_ms": 120,
                    "queue_depth": 1,
                    "cost_per_1k_tokens": 0.005,
                    "healthy": True,
                    "metrics_source": "live_control",
                }
            ],
        }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "winner": {
                    "name": "tenstorrent",
                    "url": "http://mock-tenstorrent:8000",
                    "vendor": "tenstorrent",
                }
            }

    def fake_post(url, json, timeout=5):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(router, "build_epp_request", fake_build_epp_request)
    monkeypatch.setattr(router.requests, "post", fake_post)

    scorer_response = router.call_scorer()

    assert captured["url"] == "http://hetroserve-scorer:8080/epp/pick"
    assert captured["json"]["endpoints"][0]["name"] == "tenstorrent"
    assert captured["json"]["endpoints"][0]["metrics"]["latency_ms"] == 120
    assert captured["json"]["endpoints"][0]["metrics"]["queue_depth"] == 1

    selected = router.selected_from_scorer(scorer_response)

    assert scorer_response["endpoint"] == "/epp/pick"
    assert selected["name"] == "tenstorrent"


def test_selected_from_scorer_accepts_winner_or_selected(monkeypatch):
    router = load_router_app(monkeypatch)

    winner_response = {
        "winner": {
            "name": "tenstorrent",
            "url": "http://mock-tenstorrent:8000",
            "vendor": "tenstorrent",
        }
    }

    selected_response = {
        "selected": {
            "name": "nvidia",
            "url": "http://mock-nvidia:8000",
            "vendor": "nvidia",
        }
    }

    assert router.selected_from_scorer(winner_response)["name"] == "tenstorrent"
    assert router.selected_from_scorer(selected_response)["name"] == "nvidia"


def test_redis_contract_uses_job_id_result_key(monkeypatch):
    router = load_router_app(monkeypatch)

    class FakeRedisClient:
        def __init__(self):
            self.pushed = []
            self.get_calls = []
            self.deleted = None

        def rpush(self, queue, value):
            self.pushed.append((queue, value))

        def get(self, key):
            self.get_calls.append(key)
            return json.dumps({"text": "ok", "backend": "tenstorrent"})

        def delete(self, key):
            self.deleted = key

    fake_client = FakeRedisClient()

    class FakeRedisModule:
        class Redis:
            @staticmethod
            def from_url(url, decode_responses=True):
                assert url == "redis://hetroserve-redis:6379/0"
                assert decode_responses is True
                return fake_client

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)

    selected_backend = {
        "name": "tenstorrent",
        "url": "http://mock-tenstorrent:8000",
        "vendor": "tenstorrent",
    }

    result = router.call_backend_via_redis_queue(
        selected_backend,
        prompt="hello",
        max_tokens=16,
    )

    queue, raw_job = fake_client.pushed[0]
    job = json.loads(raw_job)

    assert queue == "queue:tenstorrent"
    assert job["job_id"].startswith("job-")
    assert job["request_id"] == job["job_id"]
    assert fake_client.get_calls[0] == f"result:{job['job_id']}"
    assert fake_client.deleted == f"result:{job['job_id']}"
    assert result["text"] == "ok"
