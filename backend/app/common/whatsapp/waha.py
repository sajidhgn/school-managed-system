"""WAHA -- the self-hosted WhatsApp gateway: sessions, sending, media, webhooks.

WHY THIS FILE EXISTS
    The diary agent needs WhatsApp in BOTH directions: a teacher's photo comes in,
    the formatted diary goes out to the class group. pywhatkit can only type into a
    browser, and Meta's Cloud API cannot post to ordinary groups (its Groups API is
    capped at 8 participants on groups the business itself created). WAHA links the
    school's own number the way WhatsApp Web does, runs headless in Docker, and
    exposes it over HTTP -- so this is a thin, typed client for the calls we make.

ONE SESSION PER CAMPUS
    Each campus links its own number, so each campus is one WAHA session, named
    from the school id (`session_name`). The session's webhook carries the
    organization and school ids in its `metadata`, and WAHA signs every webhook
    with `WAHA_WEBHOOK_SECRET` -- so a verified webhook tells us WHICH tenant it is
    for without trusting anything else in the request.

WHAT WAHA CALLS A CHAT
    `923001234567@c.us` a person, `120363...@g.us` a group, `1234...@lid` a person
    behind WhatsApp's privacy id -- resolved to a phone number with `lid_to_phone`.

UNOFFICIAL, AND THAT IS A REAL RISK
    WhatsApp's terms do not allow automating a personal or business-app number.
    A campus that posts a handful of diaries a day is unlikely to be flagged; one
    that bursts hundreds of messages can be. The outbox drains one message at a
    time for that reason.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class WahaError(Exception):
    """WAHA refused or could not be reached. The message is safe to show staff."""


@dataclass(frozen=True, slots=True)
class WahaSessionInfo:
    name: str
    status: str
    """STOPPED | STARTING | SCAN_QR_CODE | WORKING | FAILED (WAHA's own values)."""
    phone: str | None
    """The linked number (`923001234567@c.us`), once WORKING."""
    push_name: str | None


@dataclass(frozen=True, slots=True)
class WahaQr:
    mimetype: str
    data: str
    """Base64 PNG, ready for a `data:` URL."""


def session_name(school_id: UUID) -> str:
    """The WAHA session for a campus. Deterministic, so nothing has to be stored."""
    return f"school_{school_id.hex}"


def verify_webhook(body: bytes, signature: str | None, algorithm: str | None, key: str) -> bool:
    """WAHA signs the RAW body with HMAC-SHA512 (hex) in `X-Webhook-Hmac`.

    An empty key verifies nothing: refusing every webhook is the safe failure for a
    deployment that forgot to configure it.
    """
    if not key or not signature:
        return False
    if algorithm and algorithm.lower() != "sha512":
        return False
    expected = hmac.new(key.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def sign_webhook(body: bytes, key: str) -> str:
    """The signature WAHA would send. Used by the tests."""
    return hmac.new(key.encode(), body, hashlib.sha512).hexdigest()


class WahaClient:
    """Async client for the WAHA REST API. One per request or job; cheap to build."""

    def __init__(self, settings: Settings | None = None, *, transport: Any = None) -> None:
        self.settings = settings or get_settings()
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self.settings.WHATSAPP_BACKEND == "waha" and bool(self.settings.WAHA_BASE_URL)

    # -- sessions ---------------------------------------------------------

    async def ensure_session(
        self, name: str, *, organization_id: UUID, school_id: UUID
    ) -> WahaSessionInfo:
        """Create the campus's session, or re-point an existing one, and start it.

        Re-applying the config every time is deliberate: it is how a changed
        webhook URL or secret reaches sessions created before the change.
        """
        config = {
            "metadata": {"organization_id": str(organization_id), "school_id": str(school_id)},
            "webhooks": [
                {
                    "url": self.settings.WAHA_WEBHOOK_URL,
                    "events": ["message"],
                    "hmac": {"key": self.settings.WAHA_WEBHOOK_SECRET},
                    "retries": {"policy": "constant", "delaySeconds": 5, "attempts": 3},
                }
            ],
        }
        existing = await self._request("GET", f"/api/sessions/{name}", allow_404=True)
        if existing is None:
            await self._request(
                "POST", "/api/sessions", json={"name": name, "start": True, "config": config}
            )
        else:
            await self._request("PUT", f"/api/sessions/{name}", json={"config": config})
            if str(existing.get("status")) in ("STOPPED", "FAILED"):
                await self._request("POST", f"/api/sessions/{name}/start")
        info = await self.session_info(name)
        if info is None:
            raise WahaError("The WhatsApp gateway did not start the session.")
        return info

    async def session_info(self, name: str) -> WahaSessionInfo | None:
        data = await self._request("GET", f"/api/sessions/{name}", allow_404=True)
        if data is None:
            return None
        me = data.get("me") or {}
        return WahaSessionInfo(
            name=name,
            status=str(data.get("status") or "STOPPED"),
            phone=me.get("id"),
            push_name=me.get("pushName"),
        )

    async def qr(self, name: str) -> WahaQr:
        data = await self._request(
            "GET",
            f"/api/{name}/auth/qr",
            params={"format": "image"},
            headers={"Accept": "application/json"},
        )
        return WahaQr(mimetype=str(data.get("mimetype") or "image/png"), data=str(data["data"]))

    async def logout(self, name: str) -> None:
        await self._request("POST", f"/api/sessions/{name}/logout", allow_404=True)

    # -- messaging --------------------------------------------------------

    async def send_text(self, session: str, chat_id: str, text: str) -> None:
        await self._request(
            "POST", "/api/sendText", json={"session": session, "chatId": chat_id, "text": text}
        )

    async def check_number(self, session: str, phone: str) -> str | None:
        """The `...@c.us` chat for a phone number, or None when it has no WhatsApp.

        Asked before a one-to-one send because WAHA accepts a text to any number and
        reports nothing back when it has no account -- the message simply never
        arrives. The chat id WhatsApp returns is also the one to send to: it is not
        always the digits of the E.164 number.
        """
        data = await self._request(
            "GET",
            "/api/contacts/check-exists",
            params={"phone": phone.lstrip("+"), "session": session},
        )
        if not isinstance(data, dict) or not data.get("numberExists"):
            return None
        chat_id = data.get("chatId")
        return str(chat_id) if chat_id else f"{phone.lstrip('+')}@c.us"

    async def download_media(self, url: str, *, max_bytes: int) -> bytes:
        """Fetch a file WAHA saved for an incoming message.

        WAHA builds the URL from ITS idea of its own address, which inside Docker is
        often not the one we reach it on -- so only the path is kept, and it is
        always fetched from `WAHA_BASE_URL`. That also means a webhook cannot point
        this download at an arbitrary host.
        """
        parts = urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if not parts.path.startswith("/api/files/"):
            raise WahaError("Unexpected media location.")
        async with self._client() as client:
            response = await client.get(path)
            if response.status_code != 200:
                raise WahaError(f"Could not download the photo (HTTP {response.status_code}).")
            if len(response.content) > max_bytes:
                raise WahaError("The photo is too large.")
            return response.content

    async def lid_to_phone(self, session: str, lid: str) -> str | None:
        """`1234@lid` -> `923001234567@c.us`, or None when WhatsApp will not say."""
        data = await self._request(
            "GET", f"/api/{session}/lids/{quote(lid, safe='')}", allow_404=True
        )
        if not data:
            return None
        pn = data.get("pn")
        return str(pn) if pn else None

    async def group_chat_id(self, session: str, invite_code: str) -> str:
        """The `...@g.us` id of the group an invite code opens.

        `join-info` answers without joining but its shape differs by WAHA engine,
        so the id is looked for in the shapes the engines use; failing that,
        `groups/join` returns `{"id": ...}` -- and is a no-op when the number is
        already in the group, which it must be to post there anyway.
        """
        info = await self._request(
            "GET", f"/api/{session}/groups/join-info", params={"code": invite_code}, allow_404=True
        )
        found = _group_id_from(info)
        if found:
            return found
        joined = await self._request(
            "POST", f"/api/{session}/groups/join", json={"code": invite_code}
        )
        found = _group_id_from(joined)
        if not found:
            raise WahaError("WhatsApp did not return the group for that invite link.")
        return found

    # -- plumbing ---------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        headers = {"X-Api-Key": self.settings.WAHA_API_KEY} if self.settings.WAHA_API_KEY else {}
        return httpx.AsyncClient(
            base_url=self.settings.WAHA_BASE_URL.rstrip("/"),
            headers=headers,
            timeout=self.settings.WAHA_TIMEOUT_SECONDS,
            transport=self._transport,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allow_404: bool = False,
        **kwargs: Any,
    ) -> Any:
        if not self.configured:
            raise WahaError("The WhatsApp gateway is not configured (WHATSAPP_BACKEND=waha).")
        try:
            async with self._client() as client:
                response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("waha_unreachable", path=path, error=str(exc))
            raise WahaError("The WhatsApp gateway is not reachable.") from exc
        if response.status_code == 404 and allow_404:
            return None
        if response.status_code >= 400:
            logger.warning(
                "waha_error", path=path, status=response.status_code, body=response.text[:300]
            )
            raise WahaError(
                f"The WhatsApp gateway refused the request (HTTP {response.status_code})."
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": base64.b64encode(response.content).decode()}


def _group_id_from(data: Any) -> str | None:
    """Pull a `...@g.us` id out of whichever shape the engine answered with."""
    if not isinstance(data, dict):
        return None
    for key in ("id", "JID", "jid", "gid", "groupId"):
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("_serialized")
        if isinstance(value, str) and value.endswith("@g.us"):
            return value
    return None
