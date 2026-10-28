"""Profile photos: `POST/DELETE /auth/me/avatar`, `GET /auth/avatars/...`.

What these pin down:
    * any member sets their own photo -- the organization owner and a teacher on
      the seeded role alike, with no permission involved;
    * what is stored is a square WebP with the upload's metadata gone, never the
      upload itself;
    * replacing or removing a photo deletes the old file, and its URL stops working;
    * bytes that are not an image, or an oversized upload, are refused;
    * the serving route needs a session and only serves files this feature wrote.

Storage is a temporary directory.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

from app.common.storage import LocalFileStorage
from app.core.config import Settings, get_settings
from app.modules.auth.router import avatar_storage
from tests.integration.conftest import API, Tenant
from tests.integration.staff import _teacher


@pytest.fixture
def photos(tenant: Tenant, tmp_path: Path) -> Path:
    root = tmp_path / "avatars"
    app = tenant.client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[avatar_storage] = lambda: LocalFileStorage(root)
    return root


def _photo(size: tuple[int, int] = (800, 600), fmt: str = "JPEG") -> bytes:
    """A phone-like photo: landscape, with EXIF that names where it was taken."""
    image = Image.new("RGB", size, (200, 80, 40))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {2: (33.0, 41.0, 0.0)}  # GPSInfo: latitude
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, exif=exif)
    return buffer.getvalue()


def _on_disk(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def _files(data: bytes, name: str = "me.jpg", kind: str = "image/jpeg") -> dict[str, object]:
    return {"file": (name, data, kind)}


async def test_owner_sets_photo_and_me_reports_it(tenant: Tenant, photos: Path) -> None:
    uploaded = await tenant.post(f"{API}/auth/me/avatar", files=_files(_photo()))
    assert uploaded.status_code == 200, uploaded.text
    url = uploaded.json()["avatar_url"]
    assert url.startswith(f"/auth/avatars/{tenant.owner_user_id}/")
    assert url.endswith(".webp")

    me = await tenant.get(f"{API}/auth/me")
    assert me.json()["avatar_url"] == url

    served = await tenant.get(f"{API}{url}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert "immutable" in served.headers["cache-control"]

    stored = Image.open(io.BytesIO(served.content))
    assert stored.format == "WEBP"
    assert stored.size == (512, 512)  # centre-cropped square, capped
    assert not stored.getexif()  # the GPS position did not survive
    assert len(_on_disk(photos)) == 1


async def test_a_teacher_sets_their_own_photo(tenant: Tenant, photos: Path) -> None:
    """No permission gates this: the seeded teacher role holds nothing about
    profiles, and still manages its own photo."""
    del photos
    teacher = await _teacher(tenant, "photo.teacher@test.example", "Photo Teacher")
    client = tenant.client

    uploaded = await client.post(
        f"{API}/auth/me/avatar", headers=teacher.headers, files=_files(_photo())
    )
    assert uploaded.status_code == 200, uploaded.text
    url = uploaded.json()["avatar_url"]
    assert url.startswith(f"/auth/avatars/{teacher.user_id}/")

    # Colleagues see it; the owner's own photo is untouched.
    assert (await tenant.get(f"{API}{url}")).status_code == 200
    assert (await tenant.get(f"{API}/auth/me")).json()["avatar_url"] is None

    removed = await client.delete(f"{API}/auth/me/avatar", headers=teacher.headers)
    assert removed.status_code == 204, removed.text
    me = await client.get(f"{API}/auth/me", headers=teacher.headers)
    assert me.json()["avatar_url"] is None


async def test_replacing_deletes_the_old_photo(tenant: Tenant, photos: Path) -> None:
    first = (await tenant.post(f"{API}/auth/me/avatar", files=_files(_photo()))).json()
    png = _photo((300, 900), "PNG")
    second = await tenant.post(f"{API}/auth/me/avatar", files=_files(png, "me.png", "image/png"))
    assert second.status_code == 200, second.text
    new_url = second.json()["avatar_url"]

    assert new_url != first["avatar_url"]
    assert (await tenant.get(f"{API}{first['avatar_url']}")).status_code == 404
    served = await tenant.get(f"{API}{new_url}")
    assert Image.open(io.BytesIO(served.content)).size == (300, 300)  # never upscaled
    assert len(_on_disk(photos)) == 1


async def test_removing_deletes_the_file(tenant: Tenant, photos: Path) -> None:
    url = (await tenant.post(f"{API}/auth/me/avatar", files=_files(_photo()))).json()["avatar_url"]
    removed = await tenant.delete(f"{API}/auth/me/avatar")
    assert removed.status_code == 204, removed.text

    assert (await tenant.get(f"{API}/auth/me")).json()["avatar_url"] is None
    assert (await tenant.get(f"{API}{url}")).status_code == 404
    assert not _on_disk(photos)

    # Removing when there is nothing to remove is not an error.
    assert (await tenant.delete(f"{API}/auth/me/avatar")).status_code == 204


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7 not a photo",
        b"plain text",
        b"\xff\xd8\xff\xe0 a JPEG header and then nothing",
    ],
)
async def test_non_images_are_refused(tenant: Tenant, photos: Path, data: bytes) -> None:
    refused = await tenant.post(f"{API}/auth/me/avatar", files=_files(data))
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "UNSUPPORTED_IMAGE"
    assert (await tenant.get(f"{API}/auth/me")).json()["avatar_url"] is None
    assert not _on_disk(photos)


async def test_oversized_upload_is_refused(
    tenant: Tenant, photos: Path, db_settings: Settings
) -> None:
    del photos
    app = tenant.client._transport.app  # type: ignore[attr-defined]
    small = db_settings.model_copy(update={"AVATAR_MAX_UPLOAD_MB": 1})
    app.dependency_overrides[get_settings] = lambda: small

    big = b"\xff\xd8\xff" + b"\0" * (1024 * 1024)
    refused = await tenant.post(f"{API}/auth/me/avatar", files=_files(big))
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "FILE_TOO_LARGE"


async def test_serving_needs_a_session_and_a_real_photo(
    tenant: Tenant, db_client: AsyncClient, photos: Path
) -> None:
    del photos
    url = (await tenant.post(f"{API}/auth/me/avatar", files=_files(_photo()))).json()["avatar_url"]
    db_client.cookies.clear()
    assert (await db_client.get(f"{API}{url}")).status_code == 401

    # Only names this feature writes are served -- nothing else under the root.
    owner = tenant.owner_user_id
    for name in ("..%2F..%2Fsecret.webp", "photo.png", "not-hex-at-all.webp"):
        assert (await tenant.get(f"{API}/auth/avatars/{owner}/{name}")).status_code == 404
