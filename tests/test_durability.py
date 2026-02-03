"""
Durability tests: acknowledged writes must survive SIGKILL and restart.
- Writer records acknowledged keys; killer randomly SIGKILLs server; after restart, 0 lost.
"""
import os
import tempfile
import threading
import time

import pytest

from conftest import SIGKILL, start_server, stop_server
from client import KVClient


@pytest.fixture(scope="module")
def durability_port_base():
    return 19430


@pytest.mark.timeout(120)
def test_durability_under_random_kills(durability_port_base):
    """
    Writer thread: repeatedly Set() or BulkSet(), records acknowledged keys (only after success).
    Killer thread: random short sleep then SIGKILL server.
    After final restart: every acknowledged key must be present (0 lost).
    """
    data_dir = tempfile.mkdtemp(prefix="kv_durability_")
    port = durability_port_base
    acknowledged: list[tuple[str, bytes]] = []
    ack_lock = threading.Lock()
    server_proc = [None]
    run_killer = [True]
    run_writer = [True]

    def writer():
        seq = 0
        while run_writer[0]:
            try:
                proc = server_proc[0]
                if proc is None or proc.poll() is not None:
                    time.sleep(0.1)
                    continue
                c = KVClient(host="127.0.0.1", port=port, timeout=2.0)
                key = f"ack_key_{seq}"
                value = f"ack_val_{seq}".encode()
                c.Set(key, value)
                with ack_lock:
                    acknowledged.append((key, value))
                seq += 1
            except Exception:
                time.sleep(0.05)

    def killer():
        while run_killer[0]:
            time.sleep(0.2 + (os.urandom(1)[0] / 255.0) * 0.3)
            proc = server_proc[0]
            if proc is not None and proc.poll() is None:
                try:
                    if SIGKILL is not None:
                        os.kill(proc.pid, SIGKILL)
                    else:
                        proc.kill()
                except (ProcessLookupError, OSError):
                    pass
                time.sleep(0.2)

    try:
        proc = start_server(data_dir, port)
        server_proc[0] = proc
        writer_t = threading.Thread(target=writer)
        killer_t = threading.Thread(target=killer)
        writer_t.start()
        killer_t.start()
        # Run for a few seconds: writer writes, killer kills, we restart server in writer loop
        # But writer doesn't restart server - we need to restart in a separate loop or here.
        def restarter():
            while run_killer[0] or run_writer[0]:
                p = server_proc[0]
                if p is not None and p.poll() is not None:
                    time.sleep(0.3)
                    server_proc[0] = start_server(data_dir, port)
                time.sleep(0.2)

        restarter_t = threading.Thread(target=restarter)
        restarter_t.start()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            time.sleep(0.5)
        run_writer[0] = False
        time.sleep(0.5)
        run_killer[0] = False
        restarter_t.join(timeout=3)
        run_killer[0] = False
        writer_t.join(timeout=5)
        killer_t.join(timeout=5)
        # Ensure server is running for final check
        if server_proc[0] is None or server_proc[0].poll() is not None:
            server_proc[0] = start_server(data_dir, port)
        time.sleep(0.5)
        client = KVClient(host="127.0.0.1", port=port, timeout=10.0)
        with ack_lock:
            missing = []
            for key, value in acknowledged:
                got = client.Get(key)
                if got != value:
                    missing.append((key, value, got))
        assert not missing, (
            f"Acknowledged keys missing after restart: {len(missing)} lost. "
            f"First few: {missing[:5]}"
        )
    finally:
        run_writer[0] = False
        run_killer[0] = False
        if server_proc[0] and server_proc[0].poll() is None:
            try:
                server_proc[0].kill()
                server_proc[0].wait(timeout=5)
            except Exception:
                pass
        import shutil
        shutil.rmtree(data_dir, ignore_errors=True)
