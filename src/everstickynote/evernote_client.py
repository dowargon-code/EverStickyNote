"""Evernote NoteStore access for a personal desktop client.

evernote3's EvernoteClient imports the removed oauth2 package and
inspect.getargspec, so this module opens the EDAM thrift endpoints directly.
EDAM 1.25 has updateNote but not updateNoteIfUsnMatches. Conditional writes
re-read the note USN and call updateNote only when it still matches.
"""

from __future__ import annotations

from dataclasses import dataclass

import evernote.edam.notestore.NoteStore as NoteStore
import evernote.edam.userstore.UserStore as UserStore
import evernote.edam.userstore.constants as UserStoreConstants
from evernote.edam.error.ttypes import (
    EDAMNotFoundException,
    EDAMSystemException,
    EDAMUserException,
)
from evernote.edam.notestore.ttypes import NoteFilter, NotesMetadataResultSpec
from evernote.edam.type.ttypes import Note
from thrift.protocol.TBinaryProtocol import TBinaryProtocol
from thrift.transport.THttpClient import THttpClient

PAGE_SIZE = 100


class EvernoteError(Exception):
    pass


@dataclass
class NotebookInfo:
    guid: str
    name: str


@dataclass
class NoteSummary:
    guid: str
    title: str
    update_sequence_num: int
    notebook_guid: str


@dataclass
class NoteDetail:
    guid: str
    title: str
    content: str
    update_sequence_num: int
    notebook_guid: str


@dataclass
class ConditionalUpdate:
    updated: bool
    note: NoteDetail


def format_evernote_error(exc: BaseException) -> str:
    if isinstance(exc, EvernoteError):
        return str(exc)
    if isinstance(exc, EDAMUserException):
        return f"Evernoteが要求を拒否しました ({exc.errorCode}: {exc.parameter or ''})".strip()
    if isinstance(exc, EDAMNotFoundException):
        return f"Evernote上で見つかりません ({exc.identifier or ''})".strip()
    if isinstance(exc, EDAMSystemException):
        message = getattr(exc, "message", "") or ""
        return f"Evernoteのシステムエラー ({exc.errorCode}: {message})".strip()
    return str(exc)


def _store_client(url: str, client_cls):
    transport = THttpClient(url)
    transport.setCustomHeaders({"User-Agent": "EverStickyNote / 1.0"})
    protocol = TBinaryProtocol(transport)
    return client_cls(protocol)


class EvernoteClient:
    def __init__(self, token: str, service_host: str = "www.evernote.com", note_store=None):
        self._token = token.strip()
        self._service_host = service_host
        self._note_store = note_store

    def __repr__(self) -> str:
        return f"EvernoteClient(connected={self._note_store is not None})"

    def connect(self) -> None:
        if self._note_store is not None:
            return
        if not self._token:
            raise EvernoteError("トークンが空です")
        user_store = _store_client(
            f"https://{self._service_host}/edam/user",
            UserStore.Client,
        )
        accepted = user_store.checkVersion(
            "EverStickyNote",
            UserStoreConstants.EDAM_VERSION_MAJOR,
            UserStoreConstants.EDAM_VERSION_MINOR,
        )
        if not accepted:
            raise EvernoteError("このクライアントのAPIバージョンはEvernoteに拒否されました")
        note_store_url = user_store.getNoteStoreUrl(self._token)
        self._note_store = _store_client(note_store_url, NoteStore.Client)

    def list_notebooks(self) -> list[NotebookInfo]:
        self.connect()
        notebooks = self._note_store.listNotebooks(self._token)
        items = [
            NotebookInfo(guid=notebook.guid, name=notebook.name or "")
            for notebook in notebooks
        ]
        items.sort(key=lambda item: item.name.casefold())
        return items

    def list_notes(self, notebook_guid: str) -> list[NoteSummary]:
        self.connect()
        spec = NotesMetadataResultSpec(
            includeTitle=True,
            includeUpdateSequenceNum=True,
            includeNotebookGuid=True,
            includeUpdated=True,
        )
        note_filter = NoteFilter(notebookGuid=notebook_guid)
        offset = 0
        collected: list[NoteSummary] = []
        while True:
            page = self._note_store.findNotesMetadata(
                self._token, note_filter, offset, PAGE_SIZE, spec
            )
            for meta in page.notes or []:
                collected.append(
                    NoteSummary(
                        guid=meta.guid,
                        title=meta.title or "",
                        update_sequence_num=meta.updateSequenceNum or 0,
                        notebook_guid=meta.notebookGuid or notebook_guid,
                    )
                )
            offset += len(page.notes or [])
            total = page.totalNotes or 0
            if offset >= total or not page.notes:
                break
        collected.sort(key=lambda item: item.title.casefold())
        return collected

    def get_note(self, guid: str) -> NoteDetail:
        self.connect()
        note = self._note_store.getNote(self._token, guid, True, False, False, False)
        return self._detail_from_note(note, fallback_content=note.content or "")

    def create_note(self, notebook_guid: str, title: str, content: str) -> NoteDetail:
        self.connect()
        created = self._note_store.createNote(
            self._token,
            Note(title=title, content=content, notebookGuid=notebook_guid),
        )
        return self._detail_from_note(created, fallback_content=content, notebook_guid=notebook_guid)

    def update_note_if_usn_matches(
        self, guid: str, title: str, content: str, expected_usn: int
    ) -> ConditionalUpdate:
        """Write only when the server USN is still the one the editor loaded."""
        self.connect()
        current = self._note_store.getNote(self._token, guid, True, False, False, False)
        current_detail = self._detail_from_note(current, fallback_content=current.content or "")
        if (current.updateSequenceNum or 0) != expected_usn:
            return ConditionalUpdate(updated=False, note=current_detail)
        saved = self._note_store.updateNote(
            self._token,
            Note(guid=guid, title=title, content=content),
        )
        detail = self._detail_from_note(
            saved,
            fallback_content=content,
            notebook_guid=current_detail.notebook_guid,
            title=title,
        )
        return ConditionalUpdate(updated=True, note=detail)

    @staticmethod
    def _detail_from_note(
        note,
        fallback_content: str,
        notebook_guid: str = "",
        title: str = "",
    ) -> NoteDetail:
        return NoteDetail(
            guid=note.guid,
            title=note.title or title,
            content=note.content if note.content is not None else fallback_content,
            update_sequence_num=note.updateSequenceNum or 0,
            notebook_guid=note.notebookGuid or notebook_guid,
        )
