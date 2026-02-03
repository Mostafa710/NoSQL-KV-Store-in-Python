#!/usr/bin/env python3
"""
Throughput benchmark: writes/sec and BulkSet items/sec with configurable concurrency.
Pre-populates DB with a dataset, then measures sustained write latency and throughput.
Outputs JSON and human-readable summary.
"""
import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client import KVClient


def run_single_writers(
    client_factory,
    num_ops: int,
    concurrency: int,
    key_prefix: str = "tw",
) -> tuple[list[float], float]:
    """Run num_ops Set operations across concurrency threads. Returns latencies and total time."""
    ops_per_thread = (num_ops + concurrency - 1) // concurrency
    latencies: list[float] = []
    lock = threading.Lock()

    def worker(thread_id: int):
        c = client_factory()
        for i in range(ops_per_thread):
            key = f"{key_prefix}_{thread_id}_{i}"
            t0 = time.perf_counter()
            try:
                c.Set(key, f"value_{thread_id}_{i}".encode())
            except Exception:
                pass
            t1 = time.perf_counter()
            with lock:
                latencies.append(t1 - t0)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    t_end = time.perf_counter()
    return latencies, t_end - t_start


def run_bulk_writers(
    client_factory,
    num_bulks: int,
    bulk_size: int,
    concurrency: int,
    key_prefix: str = "bw",
) -> tuple[list[float], float]:
    """Run num_bulks BulkSet operations (each with bulk_size items). Returns latencies and total time."""
    bulks_per_thread = (num_bulks + concurrency - 1) // concurrency
    latencies: list[float] = []
    lock = threading.Lock()

    def worker(thread_id: int):
        c = client_factory()
        for b in range(bulks_per_thread):
            items = [
                (f"{key_prefix}_{thread_id}_{b}_{i}", f"v_{thread_id}_{b}_{i}".encode())
                for i in range(bulk_size)
            ]
            t0 = time.perf_counter()
            try:
                c.BulkSet(items)
            except Exception:
                pass
            t1 = time.perf_counter()
            with lock:
                latencies.append(t1 - t0)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    t_end = time.perf_counter()
    return latencies, t_end - t_start


def stats(latencies: list[float]) -> dict:
    if not latencies:
        return {"mean_ms": 0, "median_ms": 0, "p95_ms": 0, "count": 0}
    lat_ms = [x * 1000 for x in latencies]
    lat_ms.sort()
    return {
        "mean_ms": statistics.mean(lat_ms),
        "median_ms": statistics.median(lat_ms),
        "p95_ms": lat_ms[int(len(lat_ms) * 0.95)] if len(lat_ms) > 1 else lat_ms[0],
        "count": len(lat_ms),
    }


def main():
    p = argparse.ArgumentParser(description="KV-Store throughput benchmark")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=4000)
    p.add_argument("--dataset-size", type=int, default=10_000, help="Pre-populate keys (e.g. 10k, 100k)")
    p.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8], help="Concurrency levels")
    p.add_argument("--ops", type=int, default=2000, help="Write ops per run")
    p.add_argument("--bulk-size", type=int, default=100, help="Items per BulkSet")
    p.add_argument("--out", default=None, help="Write JSON to file")
    args = p.parse_args()

    def client_factory():
        return KVClient(host=args.host, port=args.port, timeout=30.0)

    # Pre-populate
    print("Pre-populating...", end=" ", flush=True)
    c = client_factory()
    try:
        for i in range(0, args.dataset_size, 500):
            batch = [(f"pre_{i+j}", f"preval_{i+j}".encode()) for j in range(min(500, args.dataset_size - i))]
            c.BulkSet(batch)
    except Exception as e:
        print(f"Pre-populate failed: {e}. Is the server running on {args.host}:{args.port}?")
        sys.exit(1)
    print("done.")

    results = {"single_write": [], "bulk_write": []}

    for conc in args.concurrency:
        latencies, elapsed = run_single_writers(client_factory, args.ops, conc, key_prefix="sw")
        s = stats(latencies)
        writes_per_sec = len(latencies) / elapsed if elapsed else 0
        results["single_write"].append({
            "concurrency": conc,
            "writes_per_sec": round(writes_per_sec, 2),
            "elapsed_sec": round(elapsed, 3),
            **s,
        })
        print(f"Single Set concurrency={conc}: {writes_per_sec:.1f} writes/s, "
              f"median={s['median_ms']:.2f}ms p95={s['p95_ms']:.2f}ms")

    num_bulks = max(1, args.ops // args.bulk_size)
    for conc in args.concurrency:
        latencies, elapsed = run_bulk_writers(client_factory, num_bulks, args.bulk_size, conc, key_prefix="bw")
        s = stats(latencies)
        items = len(latencies) * args.bulk_size
        items_per_sec = items / elapsed if elapsed else 0
        results["bulk_write"].append({
            "concurrency": conc,
            "bulk_size": args.bulk_size,
            "items_per_sec": round(items_per_sec, 2),
            "bulks_per_sec": round(len(latencies) / elapsed, 2) if elapsed else 0,
            "elapsed_sec": round(elapsed, 3),
            **s,
        })
        print(f"BulkSet concurrency={conc} bulk_size={args.bulk_size}: {items_per_sec:.1f} items/s, "
              f"median={s['median_ms']:.2f}ms p95={s['p95_ms']:.2f}ms")

    out = {
        "benchmark": "throughput",
        "dataset_size": args.dataset_size,
        "results": results,
    }
    json_str = json.dumps(out, indent=2)
    if args.out:
        Path(args.out).write_text(json_str, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print("\n--- JSON ---\n" + json_str)


if __name__ == "__main__":
    main()
