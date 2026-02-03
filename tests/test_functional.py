"""
Functional tests using KVClient only.
- Set then Get
- Set then Delete then Get
- Get without setting
- Set then Set (same key) then Get
- Set then graceful exit then Get (durability across restart)
"""
import os
import tempfile
import time

import pytest

from conftest import start_server, stop_server
from client import KVClient


@pytest.fixture(scope="module")
def server_port_base():
    return 19410


def test_set_then_get(kv_client_and_server):
    """Set a single key, then Get -> value matches."""
    c = kv_client_and_server
    c.Set("k1", b"v1")
    assert c.Get("k1") == b"v1"


def test_set_then_delete_then_get(kv_client_and_server):
    """Set key, Delete key, Get -> returns None / not found."""
    c = kv_client_and_server
    c.Set("k2", b"v2")
    assert c.Get("k2") == b"v2"
    c.Delete("k2")
    assert c.Get("k2") is None


def test_get_without_setting(kv_client_and_server):
    """Get a key that was never set -> returns None."""
    c = kv_client_and_server
    assert c.Get("nonexistent_key_xyz") is None


def test_set_then_set_same_key_then_get(kv_client_and_server):
    """Set(k, v1), Set(k, v2), Get(k) -> v2."""
    c = kv_client_and_server
    c.Set("k3", b"v3a")
    c.Set("k3", b"v3b")
    assert c.Get("k3") == b"v3b"


def test_set_then_graceful_exit_then_get(server_port_base):
    """Set a key, gracefully stop server, restart server, Get -> value still present."""
    from pathlib import Path
    import shutil
    root = Path(__file__).resolve().parent.parent
    data_dir = str(root / "test_data_restart")
    shutil.rmtree(data_dir, ignore_errors=True)
    os.makedirs(data_dir, exist_ok=True)
    # Use unique port to avoid clashes with other tests
    port = server_port_base
    proc = start_server(data_dir, port)
    client = KVClient(host="127.0.0.1", port=port, timeout=5.0)
    client.Set("persistent_key", b"persistent_value")
    stop_server(proc, sig=__import__("signal").SIGTERM)
    time.sleep(0.5)
    # Verify WAL was written (durability)
    wal_path = os.path.join(data_dir, "wal.dat")
    assert os.path.exists(wal_path), "WAL file should exist after Set"
    wal_size = os.path.getsize(wal_path)
    assert wal_size > 6, "WAL should contain data"
    # One SET record = 1 + 4 + 14 + 4 + 16 = 39 bytes after 6-byte magic
    assert wal_size >= 45, f"WAL should have full SET record (got {wal_size} bytes)"
    # Verify replay works on the file we have
    from server.wal import WAL
    applied = []
    WAL.replay(Path(wal_path), on_set=lambda k, v: applied.append((k, v)), on_del=lambda k: applied.append((k, None)))
    assert len(applied) >= 1, f"Replay should apply at least one SET (applied={applied}, wal_size={wal_size})"
    proc2 = start_server(data_dir, port + 1)
    client2 = KVClient(host="127.0.0.1", port=port + 1, timeout=5.0)
    try:
        got = client2.Get("persistent_key")
        assert got == b"persistent_value", f"Expected b'persistent_value', got {got!r}"
    finally:
        stop_server(proc2)
    shutil.rmtree(data_dir, ignore_errors=True)


def test_bulkset_then_get(kv_client_and_server):
    """BulkSet then Get each key."""
    c = kv_client_and_server
    items = [("bk1", b"bv1"), ("bk2", b"bv2"), ("bk3", b"bv3")]
    c.BulkSet(items)
    assert c.Get("bk1") == b"bv1"
    assert c.Get("bk2") == b"bv2"
    assert c.Get("bk3") == b"bv3"


def test_delete_returns_false_when_key_missing(kv_client_and_server):
    """Delete on missing key returns False."""
    c = kv_client_and_server
    assert c.Delete("missing") is False
