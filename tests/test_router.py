import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

from prometheus_client import REGISTRY


ROUTER_APP_PATH = Path(__file__).resolve().parents[1] / "router" / "app.py"


def clear_router_prometheus_collectors():
    for collector, names in list(REGISTRY._collector_to_names.items()):
        if any(name.startswith("hetroserve_router_") for name in names):
            REGISTRY.unregister(collector)


def load_router_module(monkeypatch):
    clear_router_prometheus_collectors()

    monkeypatch.setenv("SCORER_MODE", "epp")
    monkeypatch.setenv("ROUTING_MODE", "redis_queue")
    monkeypatch.setenv("SCORER_URL", "http://hetroserve-scorer:8080")
    monkeypatch.setenv("REDIS_URL", "redis://hetroserve-redis:6379/0")

    module_name = "router_app_under_test"
    sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, ROUTER_APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_epp_request_uses_live_control_metrics(monkeypatch):
    router = load_router_module(monkeypatch)

    def fake_get(url, timeout):
        response = Mock()
        response.raise_for_status = Mock()

        if "mock-nvidia" in url:
            response.json.return_value = {
                "backend": "nvidia",
                "vendor": "nvidia",
                "control": {
                    "latency_ms": 111.0,
                    "queue_depth": 3,
                    "cost_per_1k_tokens": 0.021,
                    "healthy": True,
                },
            }
        elif "mock-tenstorrent" in url:
            response.json.return_value = {
                "backend": "tenstorrent",
                "vendor": "tenstorrent",
                "control": {
                    "latency_ms": 222.0,
                    "queue_depth": 1,
                    "cost_per_1k_tokens": 0.006,
                    "healthy": True,
                },
            }
        else:
            raise AssertionError(f"unexpected url: {url}")

        return response

    monkeypatch.setattr(router.requests, "get", fake_get)

    payload = router.build_epp_request()
    endpoints = {endpoint["name"]: endpoint for endpoint in payload["endpoints"]}

    assert endpoints["nvidia"]["latency_ms"] == 111.0
    assert endpoints["nvidia"]["queue_depth"] == 3
    assert endpoints["nvidia"]["metrics_source"] == "live_control"

    assert endpoints["tenstorrent"]["latency_ms"] == 222.0
    assert endpoints["tenstorrent"]["queue_depth"] == 1
    assert endpoints["tenstorrent"]["metrics_source"] == "live_control"


def test_build_epp_request_falls_back_to_env_defaults(monkeypatch):
    router = load_router_module(monkeypatch)

    def fake_get(url, timeout):
        raise RuntimeError("control endpoint unavailable")

    monkeypatch.setattr(router.requests, "get", fake_get)

    payload = router.build_epp_request()
    endpoints = {endpoint["name"]: endpoint for endpoint in payload["endpoints"]}

    assert endpoints["nvidia"]["latency_ms"] == 120.0
    assert endpoints["nvidia"]["queue_depth"] == 2
    assert endpoints["nvidia"]["metrics_source"] == "env_fallback"

    assert endpoints["tenstorrent"]["latency_ms"] == 180.0
    assert endpoints["tenstorrent"]["queue_depth"] == 1
    assert endpoints["tenstorrent"]["metrics_source"] == "env_fallback"


def test_selected_from_scorer_accepts_epp_selected_shape(monkeypatch):
    router = load_router_module(monkeypatch)

    selected = router.selected_from_scorer(
        {
            "selected": {
                "name": "tenstorrent",
                "vendor": "tenstorrent",
                "url": "http://mock-tenstorrent:8000",
            }
        }
    )

    assert selected == {
        "name": "tenstorrent",
        "vendor": "tenstorrent",
        "url": "http://mock-tenstorrent:8000",
    }


def test_selected_from_scorer_accepts_winner_shape(monkeypatch):
    router = load_router_module(monkeypatch)

    selected = router.selected_from_scorer(
        {
            "winner": {
                "name": "nvidia",
                "vendor": "nvidia",
                "url": "http://mock-nvidia:8000",
            }
        }
    )

    assert selected == {
        "name": "nvidia",
        "vendor": "nvidia",
        "url": "http://mock-nvidia:8000",
    }


def test_redis_job_contract_uses_job_id_result_key(monkeypatch):
    router = load_router_module(monkeypatch)

    pushed = {}

    class FakeRedis:
        def rpush(self, queue_name, payload):
            pushed["queue_name"] = queue_name
            pushed["payload"] = json.loads(payload)

        def get(self, key):
            pushed["result_key"] = key
            return json.dumps(
                {
                    "job_id": pushed["payload"]["job_id"],
                    "backend": "tenstorrent",
                    "queue": pushed["queue_name"],
                    "response": {"text": "ok"},
                }
            )

        def delete(self, key):
            pushed["deleted_key"] = key

    class FakeRedisModule:
        class Redis:
            @staticmethod
            def from_url(url, decode_responses):
                pushed["redis_url"] = url
                pushed["decode_responses"] = decode_responses
                return FakeRedis()

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)

    response = router.call_backend_via_redis_queue(
        {
            "name": "tenstorrent",
            "vendor": "tenstorrent",
            "url": "http://mock-tenstorrent:8000",
        },
        prompt="hello",
        max_tokens=16,
    )

    payload = pushed["payload"]

    assert pushed["redis_url"] == "redis://hetroserve-redis:6379/0"
    assert pushed["decode_responses"] is True
    assert pushed["queue_name"] == "queue:tenstorrent"
    assert payload["job_id"].startswith("job-")
    assert payload["request_id"] == payload["job_id"]
    assert pushed["result_key"] == f"result:{payload['job_id']}"
    assert pushed["deleted_key"] == f"result:{payload['job_id']}"
    assert response["job_id"] == payload["job_id"]
