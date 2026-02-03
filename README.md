# KV-Store — Persistent NoSQL Key-Value Store

A file-based, self-contained key-value store with a TCP (HTTP) server, Python client, WAL durability, atomic bulk writes, tests, and benchmarks. No external databases (no Redis, Postgres, etc.).

## Stack

- **Language:** Python 3.10+
- **Transport:** HTTP (FastAPI) with JSON API; configurable TCP port (default 4000).
- **Dependencies:** FastAPI, uvicorn, httpx, pytest, pytest-timeout (see `requirements.txt`).

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Start server (data in ./data)
python -m server.main --host 127.0.0.1 --port 4000 --data-dir ./data

# Or use scripts (from repo root)
# Windows: scripts\start_server.bat
# Unix:    ./scripts/start_server.sh

# Client example (other terminal)
python scripts/client_example.py set mykey myvalue
python scripts/client_example.py get mykey
python scripts/client_example.py delete mykey
```

## API (HTTP JSON)

- **GET /get?key=&lt;base64&gt;** — get value; returns `{"found": true|false, "value": "<base64>"}`.
- **POST /set** — body `{"key": "<base64>", "value": "<base64>", "debug": false}`.
- **POST /delete** — body `{"key": "<base64>"}`; returns `{"ok": true, "deleted": true|false}`.
- **POST /bulkset** — body `{"items": [{"key":"<b64>","value":"<b64>"}, ...], "debug": false}`.

Keys and values are sent as base64-encoded strings. The client (`KVClient`) encodes/decodes for you.

## Client Interface

```python
from client import KVClient, KVClientError

client = KVClient(host="127.0.0.1", port=4000, timeout=5.0)

# Get(key: str) -> Optional[bytes]
value = client.Get("mykey")  # None if not found

# Set(key: str, value: bytes, debug: bool = False) -> bool
client.Set("mykey", b"myvalue")

# Delete(key: str) -> bool
deleted = client.Delete("mykey")

# BulkSet(items: List[Tuple[str, bytes]], debug: bool = False) -> bool
client.BulkSet([("k1", b"v1"), ("k2", b"v2")])
```

On failure (connection/timeout/server error), the client raises `KVClientError`.

## ACID Guarantees and Trade-offs

- **Atomicity:** `BulkSet` is atomic: either all keys in the bulk are applied, or none. Implemented by a single WAL transaction (TX_START, all SETs, TX_END) and one fsync before ack.
- **Consistency:** Get returns the last committed Set/BulkSet/Delete; basic invariants are preserved.
- **Isolation:** A single global lock protects the in-memory index and WAL writes. Concurrent clients are serialized at the server; no partial interleaving of two Bulks.
- **Durability:** After a write is acknowledged, it is persisted by appending to a Write-Ahead Log (WAL) and calling `fsync` before returning. Restart recovers from snapshot + WAL replay. **Trade-off:** No group-commit; every write pays one fsync (configurable via `--wal-skip-fsync-prob` for testing only).

**Debug parameter:** `Set(..., debug=True)` and `BulkSet(..., debug=True)` allow the server to randomly skip fsync (e.g. 1% probability) to simulate power-loss; WAL writes still occur, but durability is not guaranteed when skip happens. Default is `debug=False`.

## Persistence and Durability

- **WAL:** Append-only binary log (`wal.dat`). Format: magic, then records (SET, DEL, TX_START, TX_END). Each write is flushed and fsync’d before ack (unless debug skip).
- **Snapshot:** Checkpoint file `snapshot.dat` (key/value dump). Created periodically (after N ops, configurable) and on demand via `POST /checkpoint`. After checkpoint, WAL is truncated.
- **Recovery:** On startup, load snapshot then replay WAL; only complete bulk transactions (TX_START … TX_END) are applied.

## Running Tests

```bash
# All tests (functional, ACID/concurrency, durability)
python -m pytest tests -v --tb=short

# Or
# Windows: scripts\run_tests.bat
# Unix:    ./scripts/run_tests.sh
```

Tests use only the `KVClient` API and start/stop the server in subprocesses. They cover:

- Set/Get, Set/Delete/Get, Get missing key, Set/Set/Get, BulkSet/Get.
- Set then graceful shutdown then restart then Get (durability).
- Concurrent BulkSet on same keys (atomicity / linearizability).
- Bulk write then kill server (SIGKILL or equivalent); restart and check full or no application.
- Durability under random kills: writer + killer + restarter; assert 0 acknowledged keys lost.

## Running Benchmarks

1. **Throughput** (server must be running on the given port):

   ```bash
   python benchmarks/bench_throughput.py --port 4000 --dataset-size 10000 --concurrency 1 4 8 --out benchmarks/throughput.json
   ```

   Reports writes/sec and BulkSet items/sec, mean/median/p95 latency; outputs JSON and a short summary.

2. **Durability** (starts its own server on the given port):

   ```bash
   python benchmarks/bench_durability.py --port 4001 --duration 20 --out benchmarks/durability.json
   ```

   Reports total acknowledged writes and how many were lost after restarts; JSON + summary.

Scripts:

- **Windows:** `scripts\run_benchmarks.bat` (throughput on 4000, then durability on 4001).
- **Unix:** `./scripts/run_benchmarks.sh`

## Project Layout

- **server/** — FastAPI app, WAL, snapshot, in-memory store.
- **client/** — `KVClient` and `KVClientError`.
- **tests/** — pytest (functional, ACID/concurrency, durability).
- **benchmarks/** — throughput and durability benchmarks (JSON + summary).
- **scripts/** — start server, run tests, run benchmarks, sample client.

## Server Options

```text
python -m server.main --host 127.0.0.1 --port 4000 --data-dir ./data [--wal-skip-fsync-prob 0]
```

- `--data-dir`: Directory for `wal.dat` and `snapshot.dat` (default `./data`).
- `--wal-skip-fsync-prob`: Probability to skip fsync (debug only; default 0).

## GitHub and CI

To push to GitHub:

1. Create a new repo on GitHub (e.g. `kv-store`).
2. From the project root, either run the script (Unix):

   ```bash
   GITHUB_USER=your_username ./scripts/git_push.sh
   ```

   or do it manually:

   ```bash
   git init
   git add .
   git commit -m "Initial commit: KV-Store with WAL, tests, benchmarks"
   git remote add origin https://github.com/YOUR_USER/kv-store.git
   git branch -M main
   git push -u origin main
   ```

Optional: add a GitHub Actions workflow under `.github/workflows/` to run `pytest tests` on push.

## Replication (3-node cluster)

Synchronous replication: one **primary** and two **secondaries**. Writes go only to the primary; the primary replicates each write to all secondaries and acks the client only when all have persisted (sync replication).

- **Starting the cluster:** start the two secondaries first, then the primary with `--secondaries`:

  ```bash
  # Terminal 1 & 2: secondaries (data in ./data1 and ./data2)
  python -m server.main --port 4001 --data-dir ./data1
  python -m server.main --port 4002 --data-dir ./data2

  # Terminal 3: primary (replicates to 4001, 4002)
  python -m server.main --port 4000 --data-dir ./data0 --secondaries http://127.0.0.1:4001,http://127.0.0.1:4002
  ```

  Clients talk only to the primary (port 4000). Reads can be served from any node; for consistency the client in this repo targets the primary.

- **Failover:** if the primary is killed, one of the secondaries must be promoted to primary and clients pointed to it. A simple approach: (1) stop the old primary, (2) choose a secondary (e.g. the one with the most keys or a fixed order), (3) restart that node with `--secondaries` pointing to the other secondary, and (4) restart the other node without `--secondaries` (as secondary). No automatic election is implemented; you can add a heartbeat and majority-vote election (e.g. Raft-like) if required.

- **Replication protocol:** primary sends `POST /replicate` to each secondary with the same op (set, delete, bulkset) and payload; secondaries apply and return 200. Primary acks the client only when all secondaries return 200; otherwise it returns 503.

## License

MIT. See [LICENSE](LICENSE).
