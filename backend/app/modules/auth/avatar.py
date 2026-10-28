"""Profile photos: what a member uploads becomes a small square WebP on disk.

WHY THIS FILE EXISTS
    `users.avatar_url` was on the model from the start, but nothing wrote it. Every
    member -- whatever their role -- may set their own photo, so the routes sit
    beside `/auth/me` behind `CurrentAuth`, not behind a permission: it is their
    face, not the organization's data.

RESPONSIBILITY
    * `normalize_avatar`: bytes in, an upright square WebP out. Pure, CPU-bound.
    * `store_avatar`: write the new file and point the row at it. The caller
      commits, THEN deletes the previous file (see the router).
    * `avatar_key`: map a served filename back to its storage key, refusing
      anything this module did not write.

WHY RE-ENCODE RATHER THAN STORE THE UPLOAD
    * A phone photo carries EXIF, often GPS coordinates -- where a teacher lives.
      Re-encoding drops all of it; storing the original would hand it to every
      colleague whose screen shows the photo.
    * Only a successful decode proves the bytes are an image. The magic bytes are
      checked first so a PDF gets a clear message rather than a Pillow error.
    * A 6 MB original drawn as a 36 px circle is 6 MB on every page load.

WHERE THE FILE LIVES
    `{AVATARS_STORAGE_PATH}/{user_id}/{random}.webp`, served at
    `/auth/avatars/{user_id}/{random}.webp` -- which is what `avatar_url` holds,
    relative to `/api/v1`. A NEW name on every upload, so the response can be
    cached as `immutable` and a replaced photo is a new URL, never a stale cache.
    The random part also means knowing a user's id is not enough to fetch it.
"""

from __future__ import annotations

import asyncio
import io
import re
from uuid import UUID, uuid4

from PIL import Image, ImageOps

from app.common.storage import LocalFileStorage
from app.core.exceptions import ValidationError
from app.modules.auth.models import User

AVATAR_EDGE = 512
"""Twice the largest size the UI draws it at, for high-density screens."""
WEBP_QUALITY = 85
AVATAR_MEDIA_TYPE = "image/webp"
AVATAR_URL_PREFIX = "/auth/avatars/"

_FILENAME_RE = re.compile(r"[0-9a-f]{32}\.webp")


class UnsupportedImageError(ValueError):
    """The bytes are not a JPEG, PNG or WebP, or cannot be decoded."""


def _is_supported(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def normalize_avatar(data: bytes) -> bytes:
    """Upright (EXIF orientation applied), centre-cropped square, at most
    `AVATAR_EDGE` px, as WebP with no metadata. Transparency is kept."""
    if not _is_supported(data):
        raise UnsupportedImageError("Upload a JPEG, PNG or WebP image.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            upright = ImageOps.exif_transpose(img)
            has_alpha = upright.mode in ("RGBA", "LA") or "transparency" in upright.info
            upright = upright.convert("RGBA" if has_alpha else "RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise UnsupportedImageError("That image could not be opened.") from exc
    # Never upscale: a 200 px photo stays 200 px rather than becoming a blurry 512.
    edge = min(AVATAR_EDGE, *upright.size)
    square = ImageOps.fit(upright, (edge, edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    square.save(buffer, format="WEBP", quality=WEBP_QUALITY)
    return buffer.getvalue()


def avatar_key(user_id: UUID, filename: str) -> str | None:
    """The storage key behind a served filename, or None if we never write one
    like it -- so the route cannot be pointed at anything else on disk."""
    return f"{user_id}/{filename}" if _FILENAME_RE.fullmatch(filename) else None


def stored_key(user: User) -> str | None:
    """The storage key of the user's current photo, if it is one of ours."""
    url = user.avatar_url
    if not url or not url.startswith(AVATAR_URL_PREFIX):
        return None
    return url.removeprefix(AVATAR_URL_PREFIX)


async def store_avatar(user: User, data: bytes, storage: LocalFileStorage) -> str | None:
    """Write the new photo and point `user.avatar_url` at it.

    Returns the previous photo's key for the caller to delete AFTER committing. The
    old file stays until then: deleted first, a failed commit would leave the row
    naming a file that no longer exists.
    """
    try:
        image = await asyncio.to_thread(normalize_avatar, data)
    except UnsupportedImageError as exc:
        raise ValidationError(str(exc), code="UNSUPPORTED_IMAGE") from exc
    previous = stored_key(user)
    key = f"{user.id}/{uuid4().hex}.webp"
    await storage.put(key, image)
    user.avatar_url = f"{AVATAR_URL_PREFIX}{key}"
    return previous
