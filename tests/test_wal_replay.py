"""Unit test for WAL replay with known bytes."""
import struct
import tempfile
from pathlib import Path

import pytest
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.wal import WAL, WAL_MAGIC, SET


def test_wal_replay_single_set():
    """Replay a minimal WAL with one SET record."""
    key = b"persistent_key"
    value = b"persistent_value"
    buf = (
        WAL_MAGIC
        + bytes([SET])
        + struct.pack(">II", len(key), len(value))
        + key
        + value
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wal") as f:
        f.write(buf)
        path = Path(f.name)
    try:
        applied = []
        WAL.replay(
            path,
            on_set=lambda k, v: applied.append((k, v)),
            on_del=lambda k: applied.append((k, None)),
        )
        assert len(applied) == 1
        assert applied[0][0] == key
        assert applied[0][1] == value
    finally:
        path.unlink(missing_ok=True)
