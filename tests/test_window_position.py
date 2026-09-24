import tempfile
import unittest
from pathlib import Path

from window_position import NotePosition, WindowLayout, load_layout, save_layout


class WindowPositionTests(unittest.TestCase):
    def test_round_trip_keeps_minimized_and_note_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "position.toml"
            layout = WindowLayout(
                minimized=True,
                notes={
                    "note-1": NotePosition(x=12, y=-40, width=300, height=280),
                },
            )
            save_layout(path, layout)
            loaded = load_layout(path)
        self.assertTrue(loaded.minimized)
        self.assertEqual(loaded.notes["note-1"], NotePosition(12, -40, 300, 280, visible=True))
        hidden = WindowLayout(notes={"note-2": NotePosition(1, 2, 300, 280, visible=False)})
        save_layout(path, hidden)
        self.assertFalse(load_layout(path).notes["note-2"].visible)

    def test_missing_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = load_layout(Path(directory) / "position.toml")
        self.assertFalse(loaded.minimized)
        self.assertEqual(loaded.notes, {})
