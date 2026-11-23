"""Build and write Evernote Export (.enex) files for creating new notes."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from everstickynote import __version__
from everstickynote.sync import normalize_title, text_to_enml

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def build_enex_xml(
    title: str,
    text: str,
    timestamp: datetime | None = None,
) -> str:
    """Build an Evernote Export (.enex) XML document for a single note."""
    clean_title = normalize_title(title)
    enml = text_to_enml(text).replace("]]>", "]]]]><![CDATA[>")
    when = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export3.dtd">\n'
        f'<en-export export-date="{stamp}" application="EverStickyNote" version="{__version__}">\n'
        "  <note>\n"
        f"    <title>{escape(clean_title)}</title>\n"
        f"    <content><![CDATA[{enml}]]></content>\n"
        f"    <created>{stamp}</created>\n"
        f"    <updated>{stamp}</updated>\n"
        "  </note>\n"
        "</en-export>\n"
    )


def safe_enex_filename(title: str, timestamp: datetime | None = None) -> str:
    """Return a filesystem-safe .enex filename derived from title and UTC timestamp."""
    when = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = when.strftime("%Y%m%d_%H%M%S")
    clean = normalize_title(title)
    sanitized = _INVALID_FILENAME_CHARS.sub("_", clean)
    sanitized = re.sub(r"_+", "_", sanitized).strip(" ._")
    if not sanitized:
        sanitized = "note"
    sanitized = sanitized[:50].rstrip(" ._") or "note"
    return f"{sanitized}_{stamp}.enex"


def write_enex_file(
    directory: Path,
    title: str,
    text: str,
    timestamp: datetime | None = None,
) -> Path:
    """Atomically write an .enex file into ``directory`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    filename = safe_enex_filename(title, timestamp=timestamp)
    target = directory / filename
    stem = target.stem
    counter = 1
    while target.exists():
        target = directory / f"{stem}_{counter}.enex"
        counter += 1
    content = build_enex_xml(title, text, timestamp=timestamp)
    temp_path = directory / f".{target.stem}.{os.getpid()}.enex.tmp"
    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, target)
    except Exception:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise
    return target
