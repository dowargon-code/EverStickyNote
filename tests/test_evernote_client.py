import unittest

from evernote_client import EvernoteClient
from spike_api import run_spike
from sync import enml_to_text, text_to_enml
from tests.fake_store import FakeNoteStore


class EvernoteClientTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeNoteStore()
        self.client = EvernoteClient("token", note_store=self.store)

    def test_lists_notebooks_and_reads_note_content(self):
        notebooks = self.client.list_notebooks()
        self.assertEqual(notebooks[0].name, "付箋")
        notes = self.client.list_notes(notebooks[0].guid)
        self.assertEqual(notes[0].title, "買い物")
        detail = self.client.get_note(notes[0].guid)
        self.assertEqual(enml_to_text(detail.content), "牛乳")
        self.assertEqual(detail.update_sequence_num, 3)

    def test_conditional_update_rejects_a_stale_usn(self):
        created = self.client.create_note("nb-1", "新規", text_to_enml("a"))
        updated = self.client.update_note_if_usn_matches(
            created.guid, "新規", text_to_enml("b"), created.update_sequence_num
        )
        self.assertTrue(updated.updated)
        self.assertEqual(enml_to_text(self.client.get_note(created.guid).content), "b")
        stale = self.client.update_note_if_usn_matches(
            created.guid, "新規", text_to_enml("c"), created.update_sequence_num
        )
        self.assertFalse(stale.updated)
        self.assertEqual(enml_to_text(stale.note.content), "b")

    def test_spike_creates_reads_and_conditionally_updates(self):
        message = run_spike(self.client)
        self.assertIn("read_ok", message)
        self.assertIn("update_ok", message)
        self.assertIn("conflict_ok", message)


if __name__ == "__main__":
    unittest.main()
