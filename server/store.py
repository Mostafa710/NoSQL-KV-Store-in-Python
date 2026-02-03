"""
In-memory key-value store with WAL durability and snapshot checkpointing.
All mutations go through the store lock; BulkSet is atomic.
"""
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from .snapshot import read_snapshot, write_snapshot
from .wal import WAL


class KVStore:
    def __init__(
        self,
        data_dir: Path,
        wal_skip_fsync_probability: float = 0.0,
        checkpoint_interval_ops: Optional[int] = None,
    ):
        self._data_dir = Path(data_dir)
        self._index: dict[bytes, bytes] = {}
        self._lock = threading.RLock()
        self._wal = WAL(self._data_dir / "wal.dat", skip_fsync_probability=wal_skip_fsync_probability)
        self._checkpoint_interval = checkpoint_interval_ops or 10_000
        self._ops_since_checkpoint = 0
        self._load()

    def _load(self) -> None:
        snapshot_path = self._data_dir / "snapshot.dat"
        self._index = read_snapshot(snapshot_path)
        WAL.replay(
            self._data_dir / "wal.dat",
            on_set=self._index.__setitem__,
            on_del=lambda k: self._index.pop(k, None),
        )

    def get(self, key: bytes) -> Optional[bytes]:
        with self._lock:
            return self._index.get(key)

    def set(self, key: bytes, value: bytes, debug_skip_fsync: bool = False) -> None:
        with self._lock:
            self._wal.append_set(key, value, sync=True, debug_skip_fsync=debug_skip_fsync)
            self._index[key] = value
            self._maybe_checkpoint(1)

    def delete(self, key: bytes, debug_skip_fsync: bool = False) -> bool:
        with self._lock:
            if key not in self._index:
                return False
            self._wal.append_delete(key, sync=True, debug_skip_fsync=debug_skip_fsync)
            del self._index[key]
            self._maybe_checkpoint(1)
            return True

    def bulk_set(self, items: List[Tuple[bytes, bytes]], debug_skip_fsync: bool = False) -> None:
        if not items:
            return
        with self._lock:
            self._wal.append_bulk(items, sync=True, debug_skip_fsync=debug_skip_fsync)
            for key, value in items:
                self._index[key] = value
            self._maybe_checkpoint(len(items))

    def _maybe_checkpoint(self, ops: int) -> None:
        self._ops_since_checkpoint += ops
        if self._ops_since_checkpoint >= self._checkpoint_interval:
            self._checkpoint()

    def _checkpoint(self) -> None:
        snapshot_path = self._data_dir / "snapshot.dat"
        write_snapshot(snapshot_path, dict(self._index))
        self._wal.truncate()
        self._ops_since_checkpoint = 0

    def checkpoint_now(self) -> None:
        with self._lock:
            self._checkpoint()

    def close(self) -> None:
        with self._lock:
            self._wal.close()
