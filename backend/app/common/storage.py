"""File storage for uploads too large to live in a database row.

WHY THIS FILE EXISTS
    Logos are small enough to store inline as data URIs. A textbook chapter -- a
    20 MB PDF, or thirty phone photos plus a rendered image per page -- is not. The
    bytes go to storage; the database keeps a key.

RESPONSIBILITY
    `put / get / delete_prefix / path` over string keys. Keys are built by the
    caller from UUIDs only (`{org}/{school}/books/{book}/...`), never from a
    filename a user supplied, and `_resolve` refuses anything that escapes the root
    regardless.

INTERACTIONS
    * `modules/books` (chapter uploads, page images) and `modules/auth/avatar.py`
      (profile photos), each under its own root.
    * Local disk only. An S3-compatible backend is a second class with the same
      four methods and a config switch -- nothing upstream changes.
"""

from __future__ import annotations

import asyncio
import shutil
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings


class LocalFileStorage:
    """Files under one root directory, written atomically."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return path

    def path(self, key: str) -> Path:
        """The file on disk, for streaming it back with `FileResponse`."""
        return self._resolve(key)

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._put_sync, key, data)

    def _put_sync(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename, so a crash mid-write never leaves a truncated file
        # under a key the database already points at.
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._resolve(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._resolve(key).unlink, True)

    async def delete_prefix(self, prefix: str) -> None:
        """Remove a key "directory" -- a whole chapter or book -- if it exists."""
        path = self._resolve(prefix)
        await asyncio.to_thread(shutil.rmtree, path, True)


@lru_cache
def _storage_for(root: str) -> LocalFileStorage:
    return LocalFileStorage(root)


def get_storage(settings: Settings | None = None) -> LocalFileStorage:
    settings = settings or get_settings()
    return _storage_for(settings.BOOKS_STORAGE_PATH)


def get_avatar_storage(settings: Settings | None = None) -> LocalFileStorage:
    settings = settings or get_settings()
    return _storage_for(settings.AVATARS_STORAGE_PATH)
