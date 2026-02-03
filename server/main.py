"""
Run the KV-Store HTTP server.
Usage: python -m server.main [--host 0.0.0.0] [--port 4000] [--data-dir ./data] [--secondaries url1,url2]
"""
import argparse
import uvicorn

from .app import init_store


def main() -> None:
    p = argparse.ArgumentParser(description="KV-Store HTTP server")
    p.add_argument("--host", default="127.0.0.1", help="Bind host")
    p.add_argument("--port", type=int, default=4000, help="Bind port")
    p.add_argument("--data-dir", default="./data", help="Data directory for WAL and snapshot")
    p.add_argument("--wal-skip-fsync-prob", type=float, default=0.0, help="Probability to skip fsync (debug)")
    p.add_argument("--secondaries", default="", help="Comma-separated secondary URLs for sync replication")
    args = p.parse_args()
    secondary_list = [u.strip() for u in args.secondaries.split(",") if u.strip()]
    init_store(
        args.data_dir,
        wal_skip_fsync_probability=args.wal_skip_fsync_prob,
        secondary_urls=secondary_list if secondary_list else None,
    )
    uvicorn.run("server.app:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
