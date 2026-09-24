import tempfile
import unittest
from pathlib import Path

from local_notes import LocalNotebook
from notebook_config import (
    NotebookConfigError,
    load_close_after_flicker,
    load_flicker_seconds,
    load_launch_at_startup,
    load_notebook_names,
    load_watch_seconds,
    save_launch_at_startup,
    select_notebooks,
)


class NotebookConfigTests(unittest.TestCase):
    def test_loads_names_and_selects_matching_notebooks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('notebooks = ["  仕事  ", "仕事", "個人"]\n', encoding="utf-8")
            names = load_notebook_names(path)
        self.assertEqual(names, ["仕事", "個人"])
        matched, missing = select_notebooks(
            [
                LocalNotebook("b", "個人"),
                LocalNotebook("a", "仕事"),
                LocalNotebook("c", "その他"),
            ],
            names,
        )
        self.assertEqual([item.id for item in matched], ["a", "b"])
        self.assertEqual(missing, [])

    def test_reports_unknown_names(self):
        matched, missing = select_notebooks(
            [LocalNotebook("a", "仕事")],
            ["無いノート"],
        )
        self.assertEqual(matched, [])
        self.assertEqual(missing, ["無いノート"])

    def test_watch_seconds_defaults_to_two_and_rejects_bad_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('notebooks = ["仕事"]\n', encoding="utf-8")
            self.assertEqual(load_watch_seconds(path), 2)
            path.write_text("notebooks = []\nwatch_seconds = 2\n", encoding="utf-8")
            self.assertEqual(load_watch_seconds(path), 2)
            path.write_text("notebooks = []\nwatch_seconds = true\n", encoding="utf-8")
            with self.assertRaises(NotebookConfigError):
                load_watch_seconds(path)

    def test_launch_at_startup_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('notebooks = ["仕事"]\nwatch_seconds = 2\n', encoding="utf-8")
            self.assertFalse(load_launch_at_startup(path))
            save_launch_at_startup(path, True)
            self.assertTrue(load_launch_at_startup(path))
            self.assertIn('notebooks = ["仕事"]', path.read_text(encoding="utf-8"))

    def test_flicker_settings_use_defaults_until_they_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('notebooks = ["仕事"]\n', encoding="utf-8")
            self.assertEqual(load_flicker_seconds(path), 5)
            self.assertTrue(load_close_after_flicker(path))
            path.write_text(
                'notebooks = ["仕事"]\nflicker_seconds = 1.5\nclose_after_flicker = false\n',
                encoding="utf-8",
            )
            self.assertEqual(load_flicker_seconds(path), 1.5)
            self.assertFalse(load_close_after_flicker(path))

    def test_rejects_a_notebooks_value_that_is_not_a_list_of_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("notebooks = 1\n", encoding="utf-8")
            with self.assertRaises(NotebookConfigError):
                load_notebook_names(path)


if __name__ == "__main__":
    unittest.main()
