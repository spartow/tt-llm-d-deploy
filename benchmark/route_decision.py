import argparse
import csv
from collections import defaultdict


def load_results(path: str):
    rows = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["client_observed_latency_ms"] = float(row["client_observed_latency_ms"])
            row["estimated_cost"] = float(row["estimated_cost"])
            row["output_tokens"] = int(row["output_tokens"])
            rows.append(row)

    return rows


def summarize(rows):
    grouped = defaultdict(list)

    for row in rows:
        grouped[row["endpoint"]].append(row)

    summaries = {}

    for endpoint, items in grouped.items():
        avg_latency = sum(i["client_observed_latency_ms"] for i in items) / len(items)
        total_cost = sum(i["estimated_cost"] for i in items)
        total_tokens = sum(i["output_tokens"] for i in items)

        summaries[endpoint] = {
            "endpoint": endpoint,
            "vendor": items[0]["vendor"],
            "model": items[0]["model"],
            "requests": len(items),
            "avg_latency_ms": round(avg_latency, 2),
            "total_cost": round(total_cost, 6),
            "total_output_tokens": total_tokens,
        }

    return summaries


def choose_backend(summaries, policy, latency_slo_ms):
    candidates = list(summaries.values())

    if policy == "lowest-cost":
        return min(candidates, key=lambda x: x["total_cost"])

    if policy == "lowest-latency":
        return min(candidates, key=lambda x: x["avg_latency_ms"])

    if policy == "slo-aware-cost":
        healthy = [
            c for c in candidates
            if c["avg_latency_ms"] <= latency_slo_ms
        ]

        if healthy:
            return min(healthy, key=lambda x: x["total_cost"])

        return min(candidates, key=lambda x: x["avg_latency_ms"])

    raise ValueError(f"Unknown policy: {policy}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", default="benchmark/results/latest.csv")
    parser.add_argument(
        "--policy",
        choices=["lowest-cost", "lowest-latency", "slo-aware-cost"],
        default="slo-aware-cost",
    )
    parser.add_argument("--latency-slo-ms", type=float, default=800)

    args = parser.parse_args()

    rows = load_results(args.input_file)
    summaries = summarize(rows)
    winner = choose_backend(summaries, args.policy, args.latency_slo_ms)

    print("\nEndpoint summaries:")
    for endpoint, summary in summaries.items():
        print(
            f"  {endpoint}: "
            f"avg_latency_ms={summary['avg_latency_ms']} "
            f"total_cost={summary['total_cost']} "
            f"tokens={summary['total_output_tokens']}"
        )

    print("\nRouting policy:")
    print(f"  policy: {args.policy}")
    print(f"  latency_slo_ms: {args.latency_slo_ms}")

    print("\nSelected backend:")
    print(f"  endpoint: {winner['endpoint']}")
    print(f"  vendor: {winner['vendor']}")
    print(f"  model: {winner['model']}")
    print(f"  avg_latency_ms: {winner['avg_latency_ms']}")
    print(f"  total_cost: {winner['total_cost']}")


if __name__ == "__main__":
    main()
