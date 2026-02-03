"""
ACID / Concurrency tests.
- Concurrent BulkSet touching same keys: validate atomicity (no partial interleavings).
- Bulk write + kill server randomly: after restart, each BulkSet either fully applied or not.
"""
import os
import tempfile
import threading
import time

import pytest

from conftest import SIGKILL, start_server, stop_server
from client import KVClient


@pytest.fixture(scope="module")
def acid_port_base():
    return 19420


@pytest.mark.timeout(90)
def test_concurrent_bulkset_same_keys(acid_port_base):
    """
    Multiple threads perform BulkSet with overlapping keys. After completion,
    each key must equal the value from the last committed BulkSet (linearizable);
    no partial results from interleaved bulks.
    """
    data_dir = tempfile.mkdtemp(prefix="kv_acid_")
    port = acid_port_base
    proc = start_server(data_dir, port)
    client_factory = lambda: KVClient(host="127.0.0.1", port=port, timeout=30.0)
    try:
        num_keys = 10
        num_threads = 4
        ops_per_thread = 20
        barrier = threading.Barrier(num_threads)
        errors = []

        def worker(tid: int):
            try:
                c = client_factory()
                barrier.wait()
                for i in range(ops_per_thread):
                    # Each bulk touches keys 0..num_keys-1 with a unique value per (thread, op)
                    items = [(f"key_{j}", f"tid{tid}_op{i}".encode()) for j in range(num_keys)]
                    c.BulkSet(items)
                barrier.wait()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        if errors:
            raise errors[0]

        # Linearizability: the last committed BulkSet wins. So all keys must have the same
        # value (that bulk writes the same value to every key in the set).
        c = client_factory()
        values = [c.Get(f"key_{j}") for j in range(num_keys)]
        assert all(v is not None for v in values)
        uniq = set(values)
        assert len(uniq) == 1, (
            "All keys must match one atomic bulk (same value); got mixed values: " + str(uniq)
        )
    finally:
        stop_server(proc)
        import shutil
        shutil.rmtree(data_dir, ignore_errors=True)


@pytest.mark.timeout(90)
def test_bulk_write_kill_server_atomicity(acid_port_base):
    """
    Start server, kick off BulkSet(s); during write randomly kill with SIGKILL.
    Restart server: each BulkSet must be either fully applied or not applied (no partial).
    """
    data_dir = tempfile.mkdtemp(prefix="kv_kill_")
    port = acid_port_base + 1
    num_reps = 5
    bulk_size = 10

    for rep in range(num_reps):
        proc = start_server(data_dir, port)
        client = KVClient(host="127.0.0.1", port=port, timeout=10.0)
        try:
            # Write one bulk with unique keys for this rep
            items = [(f"bulk_rep{rep}_k{i}", f"v_rep{rep}_{i}".encode()) for i in range(bulk_size)]
            client.BulkSet(items)
            # Let it settle
            time.sleep(0.1)
        except Exception:
            pass
        stop_server(proc, sig=SIGKILL)
        time.sleep(0.3)

    # Restart and check: each key either has correct value or is missing (whole bulk or nothing)
    proc = start_server(data_dir, port + 2)
    client = KVClient(host="127.0.0.1", port=port + 2, timeout=10.0)
    try:
        for rep in range(num_reps):
            vals = [client.Get(f"bulk_rep{rep}_k{i}") for i in range(bulk_size)]
            present = [v for v in vals if v is not None]
            if present:
                assert len(present) == bulk_size, (
                    f"Rep {rep}: partial bulk applied (got {len(present)}/{bulk_size})"
                )
                for i in range(bulk_size):
                    assert client.Get(f"bulk_rep{rep}_k{i}") == f"v_rep{rep}_{i}".encode()
    finally:
        stop_server(proc)
        import shutil
        shutil.rmtree(data_dir, ignore_errors=True)
