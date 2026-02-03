"""
Pytest fixtures: start/stop KV server in subprocess, provide KVClient.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Add project root so we can import client and run server
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import KVClient


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
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


@pytest.fixture(scope="module")
def data_dir():
    d = tempfile.mkdtemp(prefix="kvstore_test_")
    yield d
    import shutil
    try:
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture(scope="module")
def server_port():
    return 19400  # avoid clashes with default 4000


@pytest.fixture(scope="module")
def kv_server(data_dir, server_port):
    """Start server in subprocess; stop on teardown."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "server.app:app",
            "--host", "127.0.0.1", "--port", str(server_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # We need to pass data_dir to the server; uvicorn doesn't support our custom args.
    # So we need to run server.main instead of uvicorn directly.
    proc.terminate()
    proc.wait(timeout=5)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "server.main",
            "--host", "127.0.0.1", "--port", str(server_port),
            "--data-dir", data_dir,
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_for_port("127.0.0.1", server_port):
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail("Server did not start in time")
    yield proc
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


@pytest.fixture(scope="module")
def client(server_port):
    return KVClient(host="127.0.0.1", port=server_port, timeout=5.0)


@pytest.fixture
def kv_client_and_server(kv_server, client):
    """Per-test: ensure server is running and return client (uses module-scoped server)."""
    return client


@pytest.fixture(scope="module")
def fresh_data_dir(data_dir):
    """Return data_dir path; used by tests that need to restart server with same dir."""
    return data_dir


def start_server(data_dir: str, port: int, wal_skip_fsync_prob: float = 0.0) -> subprocess.Popen:
    """Start KV server in subprocess. Caller must terminate when done."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "server.main",
            "--host", "127.0.0.1", "--port", str(port),
            "--data-dir", data_dir,
            "--wal-skip-fsync-prob", str(wal_skip_fsync_prob),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_for_port("127.0.0.1", port, timeout=15.0):
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError("Server did not start")
    return proc


# Portable "force kill": SIGKILL on Unix, proc.kill() on Windows
SIGKILL = getattr(signal, "SIGKILL", None)


def stop_server(proc: subprocess.Popen, sig: int = None) -> None:
    if sig is None:
        sig = signal.SIGTERM
    try:
        if SIGKILL is not None and sig == SIGKILL:
            proc.send_signal(sig)
        else:
            proc.kill()
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, ProcessLookupError, AttributeError, OSError):
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
