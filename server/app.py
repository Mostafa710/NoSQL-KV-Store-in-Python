"""
HTTP JSON API for the KV store.
Endpoints: GET /get, POST /set, POST /delete, POST /bulkset.
Values are base64-encoded in JSON.
"""
import base64
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .replication import Replicator
from .store import KVStore

_store: Optional[KVStore] = None
_replicator: Optional[Replicator] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if _store is not None:
        _store.close()


app = FastAPI(title="KV-Store", version="1.0.0", lifespan=lifespan)


def get_store() -> KVStore:
    if _store is None:
        raise RuntimeError("Store not initialized")
    return _store


def init_store(
    data_dir: str,
    wal_skip_fsync_probability: float = 0.0,
    secondary_urls: Optional[List[str]] = None,
) -> None:
    global _store, _replicator
    _store = KVStore(
        Path(data_dir),
        wal_skip_fsync_probability=wal_skip_fsync_probability,
    )
    _replicator = Replicator(secondary_urls or [], timeout=10.0) if secondary_urls else None


class SetBody(BaseModel):
    key: str  # base64
    value: str  # base64
    debug: bool = False


class DeleteBody(BaseModel):
    key: str  # base64


class BulkItem(BaseModel):
    key: str  # base64
    value: str  # base64


class BulkSetBody(BaseModel):
    items: List[BulkItem]
    debug: bool = False


@app.get("/get")
def get(key: str) -> JSONResponse:
    """Query param key is base64-encoded."""
    try:
        key_b = base64.b64decode(key)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid key encoding")
    store = get_store()
    value = store.get(key_b)
    if value is None:
        return JSONResponse(content={"found": False, "value": None})
    return JSONResponse(content={"found": True, "value": base64.b64encode(value).decode("ascii")})


@app.post("/set")
def set(body: SetBody) -> JSONResponse:
    try:
        key_b = base64.b64decode(body.key)
        value_b = base64.b64decode(body.value)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid key/value encoding")
    store = get_store()
    store.set(key_b, value_b, debug_skip_fsync=body.debug)
    if _replicator and not _replicator.replicate_set(body.key, body.value, body.debug):
        raise HTTPException(status_code=503, detail="replication failed")
    return JSONResponse(content={"ok": True})


@app.post("/delete")
def delete(body: DeleteBody) -> JSONResponse:
    try:
        key_b = base64.b64decode(body.key)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid key encoding")
    store = get_store()
    deleted = store.delete(key_b)
    if _replicator and not _replicator.replicate_delete(body.key, False):
        raise HTTPException(status_code=503, detail="replication failed")
    return JSONResponse(content={"ok": True, "deleted": deleted})


@app.post("/bulkset")
def bulkset(body: BulkSetBody) -> JSONResponse:
    items = []
    try:
        for it in body.items:
            items.append((base64.b64decode(it.key), base64.b64decode(it.value)))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid key/value encoding")
    if not items:
        return JSONResponse(content={"ok": True})
    store = get_store()
    store.bulk_set(items, debug_skip_fsync=body.debug)
    if _replicator:
        items_b64 = [{"key": it.key, "value": it.value} for it in body.items]
        if not _replicator.replicate_bulk(items_b64, body.debug):
            raise HTTPException(status_code=503, detail="replication failed")
    return JSONResponse(content={"ok": True})


class ReplicateBody(BaseModel):
    op: str  # set | delete | bulkset
    key: Optional[str] = None
    value: Optional[str] = None
    items: Optional[List[BulkItem]] = None
    debug: bool = False


@app.post("/replicate")
def replicate(body: ReplicateBody) -> JSONResponse:
    """Apply a replicated op from primary. Used by secondaries."""
    store = get_store()
    try:
        if body.op == "set" and body.key is not None and body.value is not None:
            store.set(base64.b64decode(body.key), base64.b64decode(body.value), debug_skip_fsync=body.debug)
        elif body.op == "delete" and body.key is not None:
            store.delete(base64.b64decode(body.key), debug_skip_fsync=body.debug)
        elif body.op == "bulkset" and body.items:
            items = [(base64.b64decode(it.key), base64.b64decode(it.value)) for it in body.items]
            store.bulk_set(items, debug_skip_fsync=body.debug)
        else:
            raise HTTPException(status_code=400, detail="invalid replicate payload")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(content={"ok": True})


@app.post("/checkpoint")
def checkpoint() -> JSONResponse:
    get_store().checkpoint_now()
    return JSONResponse(content={"ok": True})


@app.get("/debug")
def debug() -> JSONResponse:
    """Return data_dir and key count for tests (do not use in production)."""
    store = get_store()
    return JSONResponse(content={
        "data_dir": str(store._data_dir),
        "key_count": len(store._index),
    })
