import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from everstickynote.enex import build_enex_xml, safe_enex_filename, write_enex_file


class EnexTests(unittest.TestCase):
    def test_build_enex_xml_creates_valid_evernote_export(self):
        stamp = datetime(2026, 11, 23, 1, 41, 0, tzinfo=timezone.utc)
        xml_text = build_enex_xml(
            "買い物 & メモ <1>",
            "牛乳\n\nパン & ]]> 確認",
            timestamp=stamp,
        )
        root = ET.fromstring(xml_text)
        self.assertEqual(root.tag, "en-export")
        self.assertEqual(root.attrib["export-date"], "20261123T014100Z")
        note = root.find("note")
        self.assertIsNotNone(note)
        self.assertEqual(note.findtext("title"), "買い物 & メモ <1>")
        self.assertEqual(note.findtext("created"), "20261123T014100Z")
        self.assertEqual(note.findtext("updated"), "20261123T014100Z")
        content = note.findtext("content")
        self.assertIn('<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">', content)
        self.assertIn("<en-note><div>牛乳</div><div><br/></div><div>パン &amp; ]]&gt; 確認</div></en-note>", content)

    def test_build_enex_xml_defaults_empty_title_to_untitled(self):
        xml_text = build_enex_xml("   ", "本文")
        root = ET.fromstring(xml_text)
        self.assertEqual(root.findtext("note/title"), "無題")

    def test_safe_enex_filename_strips_forbidden_chars(self):
        stamp = datetime(2026, 11, 23, 1, 41, 0, tzinfo=timezone.utc)
        name = safe_enex_filename('議事録: <A/B>?*"test"', timestamp=stamp)
        self.assertTrue(name.endswith("_20261123_014100.enex"))
        for bad in '<>:"/\\|?*':
            self.assertNotIn(bad, name)

    def test_write_enex_file_handles_collisions_and_leaves_no_tmp(self):
        stamp = datetime(2026, 11, 23, 1, 41, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = write_enex_file(folder, "メモ", "1つ目", timestamp=stamp)
            second = write_enex_file(folder, "メモ", "2つ目", timestamp=stamp)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertNotEqual(first, second)
            self.assertIn("1つ目", first.read_text(encoding="utf-8"))
            self.assertIn("2つ目", second.read_text(encoding="utf-8"))
            self.assertEqual(list(folder.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
