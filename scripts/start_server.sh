#!/usr/bin/env bash
# Start KV-Store server (Unix)
cd "$(dirname "$0")/.."
python3 -m server.main --host 127.0.0.1 --port 4000 --data-dir ./data "$@"
