#!/usr/bin/env python3
"""
Durability benchmark: writer + killer, report acknowledged keys lost after restarts.
Outputs JSON and human-readable summary. Optionally vary WAL/fsync (debug param).
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client import KVClient

# Portable SIGKILL for killer thread
try:
    import signal
    SIGKILL = getattr(signal, "SIGKILL", None)
except Exception:
    SIGKILL = None


def wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    import socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((host, port))
            s.close()
            return True
        except OSError:
            time.sleep(0.05)
    return False


def main():
    p = argparse.ArgumentParser(description="KV-Store durability benchmark")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=4001)
    p.add_argument("--data-dir", default=None, help="Server data dir (temp if not set)")
    p.add_argument("--duration", type=float, default=20.0, help="Seconds to run writer+killer")
    p.add_argument("--debug-fsync", action="store_true", help="Use debug=True on Set (simulate fsync skip)")
    p.add_argument("--out", default=None, help="Write JSON to file")
    args = p.parse_args()

    if args.data_dir is None:
        import tempfile
        data_dir = tempfile.mkdtemp(prefix="kv_bench_durability_")
    else:
        data_dir = args.data_dir

    server_proc = [None]
    acknowledged: list[tuple[str, bytes]] = []
    ack_lock = threading.Lock()
    run_writer = [True]
    run_killer = [True]

    def start_server():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "server.main",
                "--host", args.host, "--port", str(args.port),
                "--data-dir", data_dir,
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for_port(args.host, args.port):
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError("Server did not start")
        return proc

    def writer():
        seq = 0
        while run_writer[0]:
            try:
                proc = server_proc[0]
                if proc is None or proc.poll() is not None:
                    time.sleep(0.1)
                    continue
                c = KVClient(host=args.host, port=args.port, timeout=3.0)
                key = f"durability_key_{seq}"
                value = f"durability_val_{seq}".encode()
                c.Set(key, value, debug=args.debug_fsync)
                with ack_lock:
                    acknowledged.append((key, value))
                seq += 1
            except Exception:
                time.sleep(0.02)

    def killer():
        while run_killer[0]:
            time.sleep(0.3 + (os.urandom(1)[0] / 255.0) * 0.2)
            proc = server_proc[0]
            if proc is not None and proc.poll() is None:
                if SIGKILL is not None:
                    try:
                        os.kill(proc.pid, SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass
                else:
                    proc.kill()
                time.sleep(0.2)

    def restarter():
        while run_killer[0] or run_writer[0]:
            p = server_proc[0]
            if p is not None and p.poll() is not None:
                time.sleep(0.4)
                server_proc[0] = start_server()
            time.sleep(0.2)

    server_proc[0] = start_server()
    wt = threading.Thread(target=writer)
    kt = threading.Thread(target=killer)
    rt = threading.Thread(target=restarter)
    wt.start()
    kt.start()
    rt.start()
    deadline = time.monotonic() + args.duration
    while time.monotonic() < deadline:
        time.sleep(0.5)
    run_writer[0] = False
    time.sleep(0.5)
    run_killer[0] = False
    rt.join(timeout=3)
    wt.join(timeout=3)
    kt.join(timeout=3)
    if server_proc[0] and server_proc[0].poll() is not None:
        server_proc[0] = start_server()
    time.sleep(0.5)

    with ack_lock:
        total_acked = len(acknowledged)
    missing = []
    try:
        client = KVClient(host=args.host, port=args.port, timeout=10.0)
        with ack_lock:
            for key, value in acknowledged:
                got = client.Get(key)
                if got != value:
                    missing.append((key, value, got))
    except Exception as e:
        missing = [("error", None, str(e))]

    if server_proc[0] and server_proc[0].poll() is None:
        try:
            server_proc[0].kill()
            server_proc[0].wait(timeout=5)
        except Exception:
            pass

    lost = len(missing)
    out = {
        "benchmark": "durability",
        "total_acknowledged": total_acked,
        "lost": lost,
        "lost_keys_sample": [m[0] for m in missing[:10]],
        "debug_fsync": args.debug_fsync,
        "duration_sec": args.duration,
    }
    json_str = json.dumps(out, indent=2)
    if args.out:
        Path(args.out).write_text(json_str, encoding="utf-8")
        print(f"Wrote {args.out}")

    print(f"\nDurability: total_acknowledged={total_acked} lost={lost}")
    if lost > 0:
        print(f"  Lost keys (sample): {out['lost_keys_sample']}")
    print("\n--- JSON ---\n" + json_str)
    return 0 if lost == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
