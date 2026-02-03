"""
Snapshot file format for checkpointing.
Format: magic "KVSNAP1" + count (4 bytes BE) + for each: key_len(4) + key + value_len(4) + value.
"""
import os
import struct
from pathlib import Path
from typing import Dict, Iterator

SNAPSHOT_MAGIC = b"KVSNAP1"


def write_snapshot(path: Path, data: Dict[bytes, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(SNAPSHOT_MAGIC)
        f.write(struct.pack(">I", len(data)))
        for key, value in data.items():
            f.write(struct.pack(">I", len(key)))
            f.write(key)
            f.write(struct.pack(">I", len(value)))
            f.write(value)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass


def read_snapshot(path: Path) -> Dict[bytes, bytes]:
    if not path.exists() or path.stat().st_size < len(SNAPSHOT_MAGIC) + 4:
        return {}
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(SNAPSHOT_MAGIC):
        return {}
    i = len(SNAPSHOT_MAGIC)
    count, = struct.unpack(">I", data[i : i + 4])
    i += 4
    result = {}
    for _ in range(count):
        if i + 8 > len(data):
            break
        klen, vlen = struct.unpack(">II", data[i : i + 8])
        i += 8
        if i + klen + vlen > len(data):
            break
        key = data[i : i + klen]
        i += klen
        value = data[i : i + vlen]
        i += vlen
        result[key] = value
    return result


def iter_snapshot(path: Path) -> Iterator[tuple]:
    """Yield (key, value) pairs without loading all into memory (for large snapshots)."""
    if not path.exists() or path.stat().st_size < len(SNAPSHOT_MAGIC) + 4:
        return
    with open(path, "rb") as f:
        magic = f.read(len(SNAPSHOT_MAGIC))
        if magic != SNAPSHOT_MAGIC:
            return
        count_b = f.read(4)
        if len(count_b) < 4:
            return
        count, = struct.unpack(">I", count_b)
        for _ in range(count):
            kl = f.read(4)
            if len(kl) < 4:
                return
            klen, = struct.unpack(">I", kl)
            key = f.read(klen)
            if len(key) < klen:
                return
            vl = f.read(4)
            if len(vl) < 4:
                return
            vlen, = struct.unpack(">I", vl)
            value = f.read(vlen)
            if len(value) < vlen:
                return
            yield (key, value)
