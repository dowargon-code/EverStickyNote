import sqlite3
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QUrl

from local_notes import (
    LocalEvernote,
    LocalEvernoteError,
    display_text,
    display_title,
    evernote_app_url,
    extract_dat_text,
    layout_search_text,
)


def _write_database(base: Path) -> None:
    directory = base / "conduit-storage" / "https%3A%2F%2Fwww.evernote.com"
    directory.mkdir(parents=True)
    connection = sqlite3.connect(directory / "UDB-User1+RemoteGraph.sql")
    connection.executescript(
        """
        CREATE TABLE Nodes_Notebook (
            id TEXT PRIMARY KEY,
            label TEXT
        );
        CREATE TABLE Nodes_Note (
            id TEXT PRIMARY KEY,
            label TEXT,
            updated INTEGER,
            deleted INTEGER,
            parent_Notebook_id TEXT,
            snippet TEXT
        );
        CREATE TABLE Offline_Search_Note_Content (
            id TEXT PRIMARY KEY,
            content TEXT
        );
        INSERT INTO Nodes_Notebook VALUES ('nb-b', '仕事'), ('nb-a', 'アイデア');
        INSERT INTO Nodes_Note VALUES
            ('n1', '買い物', 20, NULL, 'nb-a', '牛乳'),
            ('n2', '  ', 10, NULL, 'nb-a', '下書き'),
            ('n3', '古い', 30, 1, 'nb-a', '消えた'),
            ('n4', '会議', 5, NULL, 'nb-b', NULL),
            ('abc123ghi', 'メモ', 40, NULL, 'nb-a', '');
        INSERT INTO Offline_Search_Note_Content VALUES
            ('n1', '  牛乳とパン\n明日  '),
            ('n2', ''),
            ('n4', '議事録です');
        """
    )
    connection.commit()
    connection.close()
    dat_dir = (
        base
        / "conduit-fs"
        / "https%3A%2F%2Fwww.evernote.com"
        / "profile"
        / "rte"
        / "Note"
        / "internal_rteDoc"
        / "abc"
        / "ghi"
    )
    dat_dir.mkdir(parents=True)
    (dat_dir / "abc123ghi.dat").write_bytes(b"\x02" + "ローカル本文".encode() + b"\x00")


class EvernoteAppUrlTests(unittest.TestCase):
    def test_builds_the_desktop_note_link(self):
        url = evernote_app_url(
            9580249.0,
            "s86",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "ffffffff-1111-2222-3333-444444444444",
        )
        self.assertEqual(
            url,
            "evernote:///view/9580249/s86/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/ffffffff-1111-2222-3333-444444444444",
        )
        self.assertEqual(QUrl(url).toString(), url)


class LocalNoteTextTests(unittest.TestCase):
    def test_title_and_text_fallbacks(self):
        self.assertEqual(display_title("  買い物  "), "買い物")
        self.assertEqual(display_title("   "), "無題")
        self.assertEqual(display_text("  本文\n続き  ", "snippet"), "本文\n続き")
        self.assertEqual(display_text("一行/n二行", ""), "一行\n二行")
        self.assertEqual(display_text("一行\\n二行", ""), "一行\n二行")
        self.assertEqual(display_text("  ", "  抜粋  "), "抜粋")
        self.assertEqual(display_text("", ""), "")

    def test_layout_breaks_only_on_div_or_br(self):
        label = "設計No：".encode()
        value = "2609".encode()
        data = b"\x00" + label + b"\x04" + value + b"\x03div\x01" + label + b"\x02br" + value
        content = "設計No：/n2609/n設計No：/n2609"
        self.assertEqual(layout_search_text(content, data), "設計No：2609\n設計No：\n2609")
        self.assertIsNone(layout_search_text("無い/n文字", b"\x03div"))

    def test_dat_text_keeps_japanese_and_drops_style_keys(self):
        data = b"\x01" + "牛乳を買う".encode() + b"\x00customNoteStyle\x00" + "明日".encode()
        self.assertEqual(extract_dat_text(data), "牛乳を買う\n明日")


class LocalEvernoteTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.base = Path(self._dir.name)
        _write_database(self.base)
        self.reader = LocalEvernote(self.base)
        self.reader.open()

    def tearDown(self):
        self.reader.close()
        self._dir.cleanup()

    def test_reopen_replaces_the_snapshot_while_the_old_file_is_open(self):
        self.reader.open()
        self.assertEqual(len(self.reader.list_notebooks()), 2)

    def test_lists_notebooks_and_skips_deleted_notes(self):
        notebooks = self.reader.list_notebooks()
        self.assertEqual([item.name for item in notebooks], ["アイデア", "仕事"])
        notes = self.reader.list_notes("nb-a")
        self.assertEqual([item.title for item in notes], ["メモ", "買い物", "無題"])

    def test_reads_plain_text_and_snippet_fallback(self):
        note = self.reader.get_note("n1")
        self.assertEqual(note.text, "牛乳とパン\n明日")
        untitled = self.reader.get_note("n2")
        self.assertEqual(untitled.title, "無題")
        self.assertEqual(untitled.text, "下書き")
        with self.assertRaises(LocalEvernoteError):
            self.reader.get_note("n3")
        from_dat = self.reader.get_note("abc123ghi")
        self.assertEqual(from_dat.text, "ローカル本文")


if __name__ == "__main__":
    unittest.main()
