import tempfile
import unittest
from pathlib import Path

from local_store import LocalStore


class LocalStoreTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = LocalStore(Path(self._dir.name) / "state.sqlite")

    def tearDown(self):
        self.store.close()
        self._dir.cleanup()

    def test_token_and_notebook_round_trip(self):
        self.assertEqual(self.store.get_token(), "")
        self.store.set_token("secret-token")
        self.store.set_notebook_guid("nb-1")
        self.assertEqual(self.store.get_token(), "secret-token")
        self.assertEqual(self.store.get_notebook_guid(), "nb-1")

    def test_window_state_defaults_then_saves_layout(self):
        state = self.store.get_note_state("note-1")
        self.assertFalse(state.is_open)
        self.assertEqual(state.color, "yellow")
        self.assertTrue(state.pinned)
        self.assertIsNone(state.last_usn)

        state.is_open = True
        state.x = 12
        state.y = 24
        state.width = 300
        state.height = 280
        state.color = "blue"
        state.pinned = False
        state.last_usn = 9
        self.store.save_note_state(state)

        loaded = self.store.get_note_state("note-1")
        self.assertTrue(loaded.is_open)
        self.assertEqual((loaded.x, loaded.y, loaded.width, loaded.height), (12, 24, 300, 280))
        self.assertEqual(loaded.color, "blue")
        self.assertFalse(loaded.pinned)
        self.assertEqual(loaded.last_usn, 9)

        self.store.set_open("note-1", False)
        self.assertFalse(self.store.get_note_state("note-1").is_open)
        self.assertEqual(self.store.get_note_state("note-1").color, "blue")


if __name__ == "__main__":
    unittest.main()
