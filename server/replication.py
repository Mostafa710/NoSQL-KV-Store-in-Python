"""
Synchronous replication: primary forwards each write to all secondaries and acks only when all ack.
Secondaries accept POST /replicate and apply the same op.
"""
import base64
from typing import List, Optional, Tuple

import httpx


class Replicator:
    """Synchronous replication to a list of secondary URLs. Call after applying locally on primary."""

    def __init__(self, secondary_urls: List[str], timeout: float = 5.0):
        self._urls = [u.rstrip("/") for u in secondary_urls]
        self._timeout = timeout

    def replicate_set(self, key_b64: str, value_b64: str, debug: bool = False) -> bool:
        for url in self._urls:
            try:
                r = httpx.post(
                    f"{url}/replicate",
                    json={"op": "set", "key": key_b64, "value": value_b64, "debug": debug},
                    timeout=self._timeout,
                )
                if r.status_code != 200:
                    return False
            except Exception:
                return False
        return True

    def replicate_delete(self, key_b64: str, debug: bool = False) -> bool:
        for url in self._urls:
            try:
                r = httpx.post(
                    f"{url}/replicate",
                    json={"op": "delete", "key": key_b64, "debug": debug},
                    timeout=self._timeout,
                )
                if r.status_code != 200:
                    return False
            except Exception:
                return False
        return True

    def replicate_bulk(self, items_b64: List[dict], debug: bool = False) -> bool:
        for url in self._urls:
            try:
                r = httpx.post(
                    f"{url}/replicate",
                    json={"op": "bulkset", "items": items_b64, "debug": debug},
                    timeout=self._timeout,
                )
                if r.status_code != 200:
                    return False
            except Exception:
                return False
        return True
