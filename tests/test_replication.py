"""
Replication tests: primary replicates to secondaries; secondaries have identical data.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from conftest import start_server, stop_server
from client import KVClient


@pytest.fixture(scope="module")
def repl_port_base():
    return 19500


@pytest.mark.timeout(60)
def test_primary_replicates_to_secondaries(repl_port_base):
    """Start primary (with 2 secondaries) and 2 secondary servers; write to primary; assert secondaries have data."""
    data_dirs = [tempfile.mkdtemp(prefix="kv_repl_") for _ in range(3)]
    ports = [repl_port_base, repl_port_base + 1, repl_port_base + 2]
    secondary_urls = [f"http://127.0.0.1:{ports[1]}", f"http://127.0.0.1:{ports[2]}"]
    try:
        # Start secondaries first (no --secondaries)
        s1 = start_server(data_dirs[1], ports[1])
        s2 = start_server(data_dirs[2], ports[2])
        time.sleep(0.3)
        # Start primary with --secondaries
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        primary_proc = __import__("subprocess").Popen(
            [
                sys.executable, "-m", "server.main",
                "--host", "127.0.0.1", "--port", str(ports[0]),
                "--data-dir", data_dirs[0],
                "--secondaries", ",".join(secondary_urls),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=__import__("subprocess").DEVNULL,
            stderr=__import__("subprocess").DEVNULL,
        )
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(("127.0.0.1", ports[0]))
                s.close()
                break
            except OSError:
                time.sleep(0.05)
        else:
            primary_proc.kill()
            primary_proc.wait(timeout=5)
            pytest.fail("Primary did not start")
        client = KVClient(host="127.0.0.1", port=ports[0], timeout=10.0)
        client.Set("repl_key", b"repl_value")
        client.BulkSet([("repl_k1", b"repl_v1"), ("repl_k2", b"repl_v2")])
        time.sleep(0.2)
        c1 = KVClient(host="127.0.0.1", port=ports[1], timeout=5.0)
        c2 = KVClient(host="127.0.0.1", port=ports[2], timeout=5.0)
        assert c1.Get("repl_key") == b"repl_value"
        assert c2.Get("repl_key") == b"repl_value"
        assert c1.Get("repl_k1") == b"repl_v1"
        assert c2.Get("repl_k2") == b"repl_v2"
        stop_server(primary_proc)
        stop_server(s1)
        stop_server(s2)
    finally:
        import shutil
        for d in data_dirs:
            shutil.rmtree(d, ignore_errors=True)
