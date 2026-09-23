"""Convert Evernote ENML to plain text and decide when a write is safe."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

SIMPLE_TAGS = {
    "en-note",
    "div",
    "br",
    "span",
    "b",
    "i",
    "u",
    "strong",
    "em",
    "p",
}

BLOCK_TAGS = {"div", "p", "li"}

ENML_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">'
)


class RichNoteBlocked(Exception):
    """Raised when a note has formatting that a plain-text write would destroy."""


def _local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _strip_preamble(enml: str) -> str:
    text = enml.strip()
    text = re.sub(r"<\?xml[^>]*\?>", "", text, count=1).strip()
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, count=1, flags=re.IGNORECASE).strip()
    return text


def _root(enml: str) -> ET.Element:
    return ET.fromstring(_strip_preamble(enml))


def is_rich_enml(enml: str) -> bool:
    """True when the note contains more than plain text and simple inline markup."""
    root = _root(enml)
    for element in root.iter():
        if _local_name(element.tag) not in SIMPLE_TAGS:
            return True
    return False


def _render(element: ET.Element) -> str:
    name = _local_name(element.tag)
    if name == "br":
        return "\n"
    inner = element.text or ""
    for child in list(element):
        inner += _render(child)
        if child.tail:
            inner += child.tail
    if name in BLOCK_TAGS and not inner.endswith("\n"):
        inner += "\n"
    return inner


def enml_to_text(enml: str) -> str:
    text = _render(_root(enml)).replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return text


def text_to_enml(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines:
        lines = [""]
    chunks: list[str] = []
    for line in lines:
        if line == "":
            chunks.append("<div><br/></div>")
        else:
            chunks.append(f"<div>{escape(line)}</div>")
    return f"{ENML_HEADER}<en-note>{''.join(chunks)}</en-note>"


def parse_note_body(enml: str) -> tuple[str, bool]:
    """Return plain text and whether the note must stay read-only."""
    try:
        rich = is_rich_enml(enml)
        return enml_to_text(enml), rich
    except ET.ParseError:
        plain = re.sub(r"<[^>]+>", "", enml)
        return plain.strip(), True


def build_update_content(original_enml: str, text: str) -> str:
    if is_rich_enml(original_enml):
        raise RichNoteBlocked("装飾を含むノートは上書きしません")
    return text_to_enml(text)


def normalize_title(title: str) -> str:
    collapsed = " ".join(title.replace("\r", " ").replace("\n", " ").split())
    collapsed = "".join(ch for ch in collapsed if ch >= " " or ch == "\t")
    collapsed = collapsed.strip()
    if not collapsed:
        collapsed = "無題"
    return collapsed[:255]


def classify_remote_change(
    *,
    editor_title: str,
    editor_text: str,
    synced_title: str,
    synced_text: str,
    remote_title: str,
    remote_text: str,
    remote_usn: int,
    local_usn: int,
    rich: bool,
) -> str:
    """Return unchanged, apply, conflict, or rich."""
    remote_changed = (
        remote_usn != local_usn
        or remote_title != synced_title
        or remote_text != synced_text
    )
    local_dirty = editor_title != synced_title or editor_text != synced_text
    if not remote_changed:
        return "unchanged"
    if local_dirty:
        return "conflict"
    if rich:
        return "rich"
    return "apply"
