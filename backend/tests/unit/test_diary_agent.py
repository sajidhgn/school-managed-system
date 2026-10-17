"""The diary agent's pure parts: phones, the format, the webhook, the photo."""

from __future__ import annotations

import io
import json
from datetime import date
from uuid import uuid4

from PIL import Image

from app.common.whatsapp.waha import session_name, sign_webhook, verify_webhook
from app.modules.diary_agent.agent import prepare_image
from app.modules.diary_agent.conversation import normalize_phone, parse_webhook
from app.modules.diary_agent.models import DEFAULT_DIARY_TEMPLATE, DEFAULT_ENTRY_TEMPLATE
from app.modules.diary_agent.service import render_diary


def test_every_way_a_pakistani_mobile_is_typed_is_one_number() -> None:
    for raw in ("0300-1234567", "+92 300 1234567", "0092 300 1234567", "3001234567"):
        assert normalize_phone(raw, "92") == "923001234567", raw
    assert normalize_phone("+44 7700 900123", "92") == "447700900123"
    assert normalize_phone("not a phone", "92") is None


def test_the_default_format_drops_an_empty_notes_line() -> None:
    body = render_diary(
        DEFAULT_DIARY_TEMPLATE,
        DEFAULT_ENTRY_TEMPLATE,
        school="City School",
        class_label="Grade 5-B",
        diary_date=date(2026, 10, 16),
        entries=[("English", "Lesson 6 words"), ("Maths", "Ex 4.2")],
        notes=None,
        teacher="Ms. Ayesha",
    )
    assert body == (
        "*City School*\n"
        "📘 *Daily Diary - Grade 5-B*\n"
        "🗓️ Friday, 16 Oct 2026\n"
        "\n"
        "▪️ *English:* Lesson 6 words\n"
        "▪️ *Maths:* Ex 4.2"
    )


def test_unknown_placeholders_and_stray_braces_survive_the_template() -> None:
    body = render_diary(
        "{class} {nope} {",
        "{subject}",
        school="",
        class_label="5-B",
        diary_date=date(2026, 10, 16),
        entries=[],
        notes=None,
        teacher="",
    )
    assert body == "5-B {nope} {"


def test_only_a_correctly_signed_webhook_verifies() -> None:
    body = b'{"event":"message"}'
    signature = sign_webhook(body, "secret")
    assert verify_webhook(body, signature, "sha512", "secret")
    assert not verify_webhook(body + b" ", signature, "sha512", "secret")
    assert not verify_webhook(body, signature, "sha512", "other")
    assert not verify_webhook(body, signature, "md5", "secret")
    # No configured secret verifies nothing, however the request is signed.
    assert not verify_webhook(body, sign_webhook(body, ""), "sha512", "")


def _envelope(**overrides: object) -> dict[str, object]:
    school_id = uuid4()
    envelope: dict[str, object] = {
        "event": "message",
        "session": session_name(school_id),
        "metadata": {"organization_id": str(uuid4()), "school_id": str(school_id)},
        "payload": {
            "id": "m1",
            "from": "923001234567@c.us",
            "fromMe": False,
            "body": "ok",
            "hasMedia": False,
        },
    }
    envelope.update(overrides)
    return envelope


def test_a_message_event_parses_and_its_tenant_must_match_its_session() -> None:
    event = parse_webhook(json.dumps(_envelope()).encode())
    assert event is not None and event.body == "ok" and not event.has_media

    mismatched = _envelope(session=session_name(uuid4()))
    assert parse_webhook(json.dumps(mismatched).encode()) is None
    assert parse_webhook(json.dumps(_envelope(event="session.status")).encode()) is None
    assert parse_webhook(b"not json") is None


def test_a_sideways_phone_photo_is_turned_upright_and_shrunk() -> None:
    original = Image.new("RGB", (4000, 3000), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90° clockwise to view"
    raw = io.BytesIO()
    original.save(raw, format="JPEG", exif=exif)

    data, mimetype = prepare_image(raw.getvalue(), "image/jpeg")
    assert mimetype == "image/jpeg"
    with Image.open(io.BytesIO(data)) as prepared:
        assert prepared.size == (1536, 2048)  # portrait, long edge capped


def test_something_that_is_not_an_image_is_passed_through_untouched() -> None:
    assert prepare_image(b"%PDF-1.7", "application/pdf") == (b"%PDF-1.7", "application/pdf")
