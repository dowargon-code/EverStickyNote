import unittest

from sync import (
    RichNoteBlocked,
    build_update_content,
    classify_remote_change,
    enml_to_text,
    is_rich_enml,
    normalize_title,
    text_to_enml,
)


PLAIN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">'
    "<en-note><div>一行目</div><div><br/></div><div>三行目</div></en-note>"
)

RICH = "<en-note><div>写真</div><en-media type=\"image/jpeg\" hash=\"abc\"/></en-note>"


class SyncTests(unittest.TestCase):
    def test_plain_enml_round_trip(self):
        self.assertFalse(is_rich_enml(PLAIN))
        self.assertEqual(enml_to_text(PLAIN), "一行目\n\n三行目")
        self.assertEqual(enml_to_text(text_to_enml("一行目\n\n三行目")), "一行目\n\n三行目")
        self.assertEqual(enml_to_text(text_to_enml("A & B <C>")), "A & B <C>")

    def test_rich_notes_are_not_writable(self):
        self.assertTrue(is_rich_enml(RICH))
        self.assertTrue(is_rich_enml("<en-note><en-todo checked=\"false\"/>牛乳</en-note>"))
        self.assertTrue(is_rich_enml("<en-note><table><tr><td>a</td></tr></table></en-note>"))
        with self.assertRaises(RichNoteBlocked):
            build_update_content(RICH, "上書き")

    def test_title_is_trimmed_to_evernote_limits(self):
        self.assertEqual(normalize_title("  hello \n world  "), "hello world")
        self.assertEqual(normalize_title("   "), "無題")
        self.assertEqual(len(normalize_title("あ" * 400)), 255)

    def test_remote_change_classification(self):
        common = dict(
            editor_title="題",
            editor_text="本文",
            synced_title="題",
            synced_text="本文",
            remote_title="題",
            remote_text="本文",
            remote_usn=2,
            local_usn=2,
            rich=False,
        )
        self.assertEqual(classify_remote_change(**common), "unchanged")
        self.assertEqual(
            classify_remote_change(**{**common, "remote_text": "新しい", "remote_usn": 3}),
            "apply",
        )
        self.assertEqual(
            classify_remote_change(
                **{**common, "editor_text": "手元", "remote_text": "新しい", "remote_usn": 3}
            ),
            "conflict",
        )
        self.assertEqual(
            classify_remote_change(**{**common, "remote_usn": 4, "rich": True}),
            "rich",
        )
        self.assertEqual(
            classify_remote_change(
                **{**common, "editor_text": "手元", "remote_usn": 4, "rich": True}
            ),
            "conflict",
        )


if __name__ == "__main__":
    unittest.main()
