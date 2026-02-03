"""
Write-Ahead Log (WAL) for durable key-value operations.
Binary format: type byte + length-prefixed key/value.
- 0x00 TX_START (bulk begin)
- 0x01 SET (key_len:4 BE, key, value_len:4 BE, value)
- 0x02 DEL (key_len:4 BE, key)
- 0x03 TX_END (bulk end)
"""
import os
import struct
import threading
from pathlib import Path
from typing import Callable, List, Tuple

WAL_MAGIC = b"KVWAL1"
TX_START = 0x00
SET = 0x01
DEL = 0x02
TX_END = 0x03


class WAL:
    def __init__(self, path: Path, skip_fsync_probability: float = 0.0):
        self._path = path
        self._skip_fsync_probability = skip_fsync_probability
        self._file = None
        self._lock = threading.Lock()
        self._ensure_open()

    def _ensure_open(self) -> None:
        if self._file is None or self._file.closed:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self._path, "ab")
            if self._path.stat().st_size == 0:
                self._file.write(WAL_MAGIC)
                self._file.flush()
                try:
                    os.fsync(self._file.fileno())
                except OSError:
                    pass

    def _fsync(self, skip_ok: bool = False) -> None:
        """Flush and fsync so that writes are durable. skip_ok=True allows debug skip."""
        import random
        if skip_ok and self._skip_fsync_probability > 0 and random.random() < self._skip_fsync_probability:
            return
        self._file.flush()
        try:
            os.fsync(self._file.fileno())
        except OSError:
            pass

    def _write_set(self, key: bytes, value: bytes) -> None:
        """Write SET record: op(1) + key_len(4) + value_len(4) + key + value (replay reads both lengths first)."""
        self._file.write(bytes([SET]))
        self._file.write(struct.pack(">II", len(key), len(value)))
        self._file.write(key)
        self._file.write(value)

    def _write_del(self, key: bytes) -> None:
        self._file.write(bytes([DEL]))
        self._file.write(struct.pack(">I", len(key)))
        self._file.write(key)

    def append_set(self, key: bytes, value: bytes, sync: bool = True, debug_skip_fsync: bool = False) -> None:
        with self._lock:
            self._ensure_open()
            self._write_set(key, value)
            if sync:
                self._fsync(skip_ok=debug_skip_fsync)

    def append_delete(self, key: bytes, sync: bool = True, debug_skip_fsync: bool = False) -> None:
        with self._lock:
            self._ensure_open()
            self._write_del(key)
            if sync:
                self._fsync(skip_ok=debug_skip_fsync)

    def append_bulk(self, items: List[Tuple[bytes, bytes]], sync: bool = True, debug_skip_fsync: bool = False) -> None:
        with self._lock:
            self._ensure_open()
            self._file.write(bytes([TX_START]))
            for key, value in items:
                self._write_set(key, value)
            self._file.write(bytes([TX_END]))
            if sync:
                self._fsync(skip_ok=debug_skip_fsync)

    def truncate(self) -> None:
        """Truncate WAL to empty (after checkpoint). Caller must hold exclusive access."""
        with self._lock:
            if self._file and not self._file.closed:
                self._file.close()
            self._file = open(self._path, "wb")
            self._file.write(WAL_MAGIC)
            self._file.flush()
            try:
                os.fsync(self._file.fileno())
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            if self._file and not self._file.closed:
                self._file.close()
                self._file = None

    @staticmethod
    def replay(path: Path, on_set: Callable[[bytes, bytes], None], on_del: Callable[[bytes], None]) -> None:
        """Replay WAL file into on_set/on_del. Only applies complete bulk transactions."""
        if not path.exists() or path.stat().st_size <= len(WAL_MAGIC):
            return
        with open(path, "rb") as f:
            data = f.read()
        if not data.startswith(WAL_MAGIC):
            return
        i = len(WAL_MAGIC)
        pending: List[Tuple[bytes, bytes] | Tuple[bytes]] = []  # (key, value) or (key,) for del
        in_bulk = False
        while i < len(data):
            if i >= len(data):
                break
            op = data[i]
            i += 1
            if op == TX_START:
                in_bulk = True
                pending = []
            elif op == SET:
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
                if in_bulk:
                    pending.append((key, value))
                else:
                    on_set(key, value)
            elif op == DEL:
                if i + 4 > len(data):
                    break
                klen, = struct.unpack(">I", data[i : i + 4])
                i += 4
                if i + klen > len(data):
                    break
                key = data[i : i + klen]
                i += klen
                if in_bulk:
                    pending.append((key,))  # delete marker
                else:
                    on_del(key)
            elif op == TX_END:
                for item in pending:
                    if len(item) == 2:
                        on_set(item[0], item[1])
                    else:
                        on_del(item[0])
                in_bulk = False
                pending = []
            else:
                break
