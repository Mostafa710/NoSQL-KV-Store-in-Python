#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
echo "=== Throughput (ensure server is running: ./scripts/start_server.sh) ==="
python3 benchmarks/bench_throughput.py --port 4000 --out benchmarks/throughput.json
echo ""
echo "=== Durability (starts server on 4001) ==="
python3 benchmarks/bench_durability.py --port 4001 --duration 15 --out benchmarks/durability.json
