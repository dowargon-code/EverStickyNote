"""In-memory NoteStore for the API spike and the window tests."""

from evernote.edam.notestore.ttypes import NoteMetadata, NotesMetadataList
from evernote.edam.type.ttypes import Note, Notebook


class FakeNoteStore:
    def __init__(self):
        self.notebooks = [Notebook(guid="nb-1", name="付箋")]
        self.notes = {
            "note-1": Note(
                guid="note-1",
                title="買い物",
                content=(
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<en-note><div>牛乳</div></en-note>"
                ),
                updateSequenceNum=3,
                notebookGuid="nb-1",
            )
        }
        self._next = 10

    def listNotebooks(self, token):
        if not token:
            raise RuntimeError("missing token")
        return list(self.notebooks)

    def findNotesMetadata(self, token, note_filter, offset, max_notes, spec):
        matched = [
            NoteMetadata(
                guid=note.guid,
                title=note.title,
                updateSequenceNum=note.updateSequenceNum,
                notebookGuid=note.notebookGuid,
            )
            for note in self.notes.values()
            if note.notebookGuid == note_filter.notebookGuid
        ]
        page = matched[offset : offset + max_notes]
        return NotesMetadataList(startIndex=offset, totalNotes=len(matched), notes=page)

    def getNote(self, token, guid, with_content, with_resources_data, with_recognition, with_alternate):
        note = self.notes[guid]
        if with_content:
            return note
        return Note(
            guid=note.guid,
            title=note.title,
            updateSequenceNum=note.updateSequenceNum,
            notebookGuid=note.notebookGuid,
        )

    def createNote(self, token, note):
        self._next += 1
        created = Note(
            guid=f"note-{self._next}",
            title=note.title,
            content=note.content,
            updateSequenceNum=self._next,
            notebookGuid=note.notebookGuid,
        )
        self.notes[created.guid] = created
        return created

    def updateNote(self, token, note):
        current = self.notes[note.guid]
        current.title = note.title
        current.content = note.content
        self._next += 1
        current.updateSequenceNum = self._next
        return current
