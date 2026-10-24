"""Turning uploads into pages -- no AI, no database, no network.

WHY THIS FILE EXISTS
    Everything the agent does starts from "a list of page images, each with
    whatever text the file already carried". Producing that list is plain file
    handling, and keeping it free of I/O beyond its arguments makes it testable with
    a generated PDF and a generated photo.

RESPONSIBILITY
    * `sniff_kind`: decide PDF vs image from the BYTES, never the filename or the
      browser's content type, both of which the uploader controls.
    * `split_file`: one `RawPage` per page -- rendered PNG + text layer for a PDF,
      an upright, size-capped JPEG for a photo.
    * `text_layer_is_usable` / `guess_printed_page_number`: the two cheap checks
      that let a digitally typeset PDF skip the vision model entirely.

LIBRARIES
    `pypdfium2` (Apache-2.0/BSD) renders and extracts text; `Pillow` normalises
    photos. PyMuPDF is deliberately not used: it is AGPL.

ALL FUNCTIONS ARE SYNCHRONOUS AND CPU-BOUND -- callers run them in a thread.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from app.modules.books.models import FileKind

RENDER_DPI = 150
"""Enough for a vision model to read 9pt body text; ~1.2 MP for an A4 page."""
MAX_IMAGE_EDGE = 2000
JPEG_QUALITY = 85

_MIN_TEXT_LAYER_CHARS = 200
_MAX_BAD_CHAR_RATIO = 0.02

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class UnsupportedFileError(ValueError):
    """The bytes are not a PDF, JPEG, PNG or WebP, or cannot be opened."""


@dataclass(frozen=True, slots=True)
class RawPage:
    source_index: int
    image: bytes
    image_type: str
    """`image/png` or `image/jpeg` -- what `image` is encoded as."""
    text_layer: str


def sniff_kind(data: bytes) -> tuple[FileKind, str]:
    """(kind, canonical content type) from magic bytes."""
    if data.startswith(b"%PDF-"):
        return FileKind.PDF, "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return FileKind.IMAGE, "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileKind.IMAGE, "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return FileKind.IMAGE, "image/webp"
    raise UnsupportedFileError("Only PDF, JPEG, PNG and WebP files can be uploaded.")


def count_pages(data: bytes, kind: FileKind) -> int:
    if kind is FileKind.IMAGE:
        return 1
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise UnsupportedFileError(
            "That PDF could not be opened. Is it password protected?"
        ) from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


def split_file(data: bytes, kind: FileKind, *, max_pages: int | None = None) -> list[RawPage]:
    """Every page of one upload, in the file's own order -- or only its first
    `max_pages`, so reading a whole-book PDF's front matter renders a dozen pages,
    not three hundred."""
    if kind is FileKind.IMAGE:
        return [RawPage(0, normalize_image(data), "image/jpeg", "")]
    return _split_pdf(data, max_pages)


def _split_pdf(data: bytes, max_pages: int | None = None) -> list[RawPage]:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise UnsupportedFileError("That PDF could not be opened.") from exc
    pages: list[RawPage] = []
    try:
        count = len(pdf) if max_pages is None else min(len(pdf), max_pages)
        for index in range(count):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded()
                finally:
                    textpage.close()
                pil = page.render(scale=RENDER_DPI / 72).to_pil()
                pil.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
                buffer = io.BytesIO()
                pil.convert("RGB").save(buffer, format="PNG", optimize=True)
                pages.append(RawPage(index, buffer.getvalue(), "image/png", _clean(text)))
            finally:
                page.close()
    finally:
        pdf.close()
    return pages


def normalize_image(data: bytes) -> bytes:
    """Upright (EXIF orientation applied), RGB, longest edge capped, as JPEG.

    Phones store portrait photos sideways plus an orientation tag; a vision model
    shown the raw pixels reads the page rotated 90 degrees.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            upright = ImageOps.exif_transpose(img).convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise UnsupportedFileError("That image could not be opened.") from exc
    upright.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buffer = io.BytesIO()
    upright.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def text_layer_is_usable(text: str) -> bool:
    """Whether a PDF page's own text can be trusted instead of reading the image.

    Fails for scanned pages (no text at all) and for PDFs exported from tools that
    map glyphs to private-use code points -- Urdu InPage exports are the common
    case. Those come out as plausible-length strings of garbage, so length alone is
    not enough.
    """
    stripped = "".join(text.split())
    if len(stripped) < _MIN_TEXT_LAYER_CHARS:
        return False
    bad = sum(1 for ch in stripped if ch == "�" or unicodedata.category(ch) in {"Co", "Cc", "Cn"})
    if bad / len(stripped) > _MAX_BAD_CHAR_RATIO:
        return False
    letters = sum(1 for ch in stripped if ch.isalpha())
    return letters / len(stripped) >= 0.5


# "12", "- 12 -", "(12)", "Page 12". \u2013 is the en dash some typesetters put around it.
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:page|pg\.?|p\.)?\s*[-\u2013(]?\s*(\d{1,4})\s*[-\u2013)]?\s*$", re.I
)


def guess_printed_page_number(text: str) -> int | None:
    """The printed page number from a text layer, if a header/footer line is one.

    Looks only at the first and last two non-empty lines -- where running headers
    and footers live -- and only at lines that are nothing BUT a number, so "Table
    12" or an exercise number in the body is never mistaken for one.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    for line in [*lines[-2:][::-1], *lines[:2]]:
        match = _PAGE_NUMBER_LINE.match(line)
        if match:
            number = int(match.group(1))
            if 0 < number < 2000:
                return number
    return None
