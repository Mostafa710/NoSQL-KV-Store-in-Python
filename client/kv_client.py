"""
KV-Store client. Communicates with the server via HTTP JSON API.
All keys and values are bytes; the client base64-encodes them for transport.
"""
import base64
from typing import List, Optional, Tuple

import httpx


class KVClientError(Exception):
    """Raised when a request fails (connection, timeout, or server error)."""
    pass


class KVClient:
    """
    Client for the KV-Store HTTP API.
    - Get(key) -> value or None if not found; raises KVClientError on failure.
    - Set(key, value, debug=False) -> True on success.
    - Delete(key) -> True if key was deleted, False if not found.
    - BulkSet(items, debug=False) -> True on success.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 4000, timeout: float = 5.0):
        self._base_url = f"http://{host}:{port}"
        self._timeout = timeout

    def Get(self, key: str) -> Optional[bytes]:
        """
        Get value for key. Returns None if key is not found.
        Raises KVClientError on connection/timeout or server error.
        """
        key_b64 = base64.b64encode(key.encode("utf-8") if isinstance(key, str) else key).decode("ascii")
        try:
            r = httpx.get(f"{self._base_url}/get", params={"key": key_b64}, timeout=self._timeout)
            r.raise_for_status()
            data = r.json()
            if not data.get("found"):
                return None
            raw = data.get("value")
            if raw is None:
                return None
            return base64.b64decode(raw)
        except httpx.HTTPError as e:
            raise KVClientError(f"Get failed: {e}") from e

    def Set(self, key: str, value: bytes, debug: bool = False) -> bool:
        """
        Set key to value. Returns True on success.
        debug=True may induce simulated sync failures (skip fsync with probability).
        Raises KVClientError on failure.
        """
        key_b = key.encode("utf-8") if isinstance(key, str) else key
        key_b64 = base64.b64encode(key_b).decode("ascii")
        value_b64 = base64.b64encode(value).decode("ascii")
        try:
            r = httpx.post(
                f"{self._base_url}/set",
                json={"key": key_b64, "value": value_b64, "debug": debug},
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json().get("ok", False)
        except httpx.HTTPError as e:
            raise KVClientError(f"Set failed: {e}") from e

    def Delete(self, key: str) -> bool:
        """
        Delete key. Returns True if key was deleted, False if not found.
        Raises KVClientError on failure.
        """
        key_b = key.encode("utf-8") if isinstance(key, str) else key
        key_b64 = base64.b64encode(key_b).decode("ascii")
        try:
            r = httpx.post(
                f"{self._base_url}/delete",
                json={"key": key_b64},
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json().get("deleted", False)
        except httpx.HTTPError as e:
            raise KVClientError(f"Delete failed: {e}") from e

    def BulkSet(self, items: List[Tuple[str, bytes]], debug: bool = False) -> bool:
        """
        Atomically set multiple keys. items = [(key, value), ...].
        Returns True on success. debug=True may induce simulated sync failures.
        Raises KVClientError on failure.
        """
        encoded = []
        for k, v in items:
            k_b = k.encode("utf-8") if isinstance(k, str) else k
            encoded.append({
                "key": base64.b64encode(k_b).decode("ascii"),
                "value": base64.b64encode(v).decode("ascii"),
            })
        try:
            r = httpx.post(
                f"{self._base_url}/bulkset",
                json={"items": encoded, "debug": debug},
                timeout=self._timeout,
            )
            r.raise_for_status()
            return r.json().get("ok", False)
        except httpx.HTTPError as e:
            raise KVClientError(f"BulkSet failed: {e}") from e
