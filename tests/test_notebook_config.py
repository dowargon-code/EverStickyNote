import tempfile
import unittest
from pathlib import Path

from everstickynote.local_notes import LocalNotebook
from everstickynote.notebook_config import (
    AppConfig,
    NotebookConfigError,
    load_close_after_flicker,
    load_config,
    load_default_notebook,
    load_flicker_seconds,
    load_import_dir,
    load_launch_at_startup,
    load_notebook_names,
    load_watch_seconds,
    save_config,
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

    def test_load_import_dir_defaults_and_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('notebooks = ["仕事"]\n', encoding="utf-8")
            self.assertEqual(load_import_dir(path), "")
            path.write_text('notebooks = ["仕事"]\nimport_dir = "  C:\\\\Import  "\n', encoding="utf-8")
            self.assertEqual(load_import_dir(path), r"C:\Import")
            path.write_text('notebooks = ["仕事"]\nimport_dir = 123\n', encoding="utf-8")
            with self.assertRaises(NotebookConfigError):
                load_import_dir(path)

    def test_save_config_preserves_comments_and_handles_multiline_arrays(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                "# ユーザーコメント1\n"
                "notebooks = [\n"
                '  "古い",\n'
                '  "仕事",\n'
                "]\n\n"
                "# ユーザーコメント2\n"
                "watch_seconds = 2\n",
                encoding="utf-8",
            )
            save_config(
                path,
                notebooks=["仕事", "個人", "仕事"],
                watch_seconds=3.5,
                flicker_seconds=7,
                close_after_flicker=False,
                default_notebook="  0.  Inbox  ",
                import_dir=r"C:\Users\Test\EvernoteImport",
            )
            written = path.read_text(encoding="utf-8")
            self.assertIn("# ユーザーコメント1", written)
            self.assertIn("# ユーザーコメント2", written)
            loaded = load_config(path)
            self.assertEqual(
                loaded,
                AppConfig(
                    notebooks=["仕事", "個人"],
                    watch_seconds=3.5,
                    launch_at_startup=False,
                    flicker_seconds=7.0,
                    close_after_flicker=False,
                    default_notebook="0. Inbox",
                    import_dir=r"C:\Users\Test\EvernoteImport",
                ),
            )
            self.assertEqual(load_default_notebook(path), "0. Inbox")

    def test_default_notebook_validation_and_legacy_import_dir_ignored_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('notebooks = ["仕事"]\nimport_dir = "C:\\\\Legacy"\n', encoding="utf-8")
            cfg = load_config(path)
            self.assertEqual(cfg.default_notebook, "")
            self.assertEqual(load_default_notebook(path), "")
            path.write_text('notebooks = ["仕事"]\ndefault_notebook = 1\n', encoding="utf-8")
            with self.assertRaises(NotebookConfigError):
                load_default_notebook(path)


if __name__ == "__main__":
    unittest.main()
