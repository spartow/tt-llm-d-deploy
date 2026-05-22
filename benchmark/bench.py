import argparse
import csv
import statistics
import time
from pathlib import Path

import requests


ENDPOINTS = {
    "nvidia": "http://localhost:8101/generate",
    "tenstorrent": "http://localhost:8102/generate",
}


def call_endpoint(name: str, url: str, prompt: str, max_tokens: int):
    start = time.time()

    resp = requests.post(
        url,
        json={
            "prompt": prompt,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )

    elapsed_ms = int((time.time() - start) * 1000)
    resp.raise_for_status()

    data = resp.json()
    data["endpoint"] = name
    data["client_observed_latency_ms"] = elapsed_ms
    return data


def summarize(endpoint_name: str, rows: list[dict]):
    latencies = [r["client_observed_latency_ms"] for r in rows]
    output_tokens = [r["output_tokens"] for r in rows]
    costs = [r["estimated_cost"] for r in rows]

    return {
        "endpoint": endpoint_name,
        "requests": len(rows),
        "avg_latency_ms": round(statistics.mean(latencies), 2),
        "p50_latency_ms": round(statistics.median(latencies), 2),
        "max_latency_ms": max(latencies),
        "total_output_tokens": sum(output_tokens),
        "total_estimated_cost": round(sum(costs), 6),
    }


def write_csv(results: list[dict], output_file: str):
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "endpoint",
        "vendor",
        "model",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "client_observed_latency_ms",
        "tokens_per_second",
        "estimated_cost",
    ]

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for row in results:
            writer.writerow({field: row.get(field) for field in fields})


def run_benchmark(requests_count: int, max_tokens: int, output_file: str):
    prompt = "Explain heterogeneous LLM inference in simple English."

    all_results = []

    for endpoint_name, endpoint_url in ENDPOINTS.items():
        print(f"\nBenchmarking {endpoint_name}: {endpoint_url}")

        endpoint_results = []

        for i in range(requests_count):
            result = call_endpoint(
                endpoint_name,
                endpoint_url,
                prompt,
                max_tokens,
            )

            endpoint_results.append(result)
            all_results.append(result)

            print(
                f"{endpoint_name} request={i + 1} "
                f"latency_ms={result['client_observed_latency_ms']} "
                f"output_tokens={result['output_tokens']} "
                f"cost={result['estimated_cost']}"
            )

        summary = summarize(endpoint_name, endpoint_results)

        print(f"\nSummary for {endpoint_name}")
        print(f"  requests: {summary['requests']}")
        print(f"  avg_latency_ms: {summary['avg_latency_ms']}")
        print(f"  p50_latency_ms: {summary['p50_latency_ms']}")
        print(f"  max_latency_ms: {summary['max_latency_ms']}")
        print(f"  total_output_tokens: {summary['total_output_tokens']}")
        print(f"  total_estimated_cost: {summary['total_estimated_cost']}")

    write_csv(all_results, output_file)
    print(f"\nSaved benchmark result to: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--output-file", default="benchmark/results/latest.csv")

    args = parser.parse_args()

    run_benchmark(
        requests_count=args.requests,
        max_tokens=args.max_tokens,
        output_file=args.output_file,
    )
