import tempfile
import unittest
from pathlib import Path

from local_notes import LocalNotebook
from notebook_config import NotebookConfigError, load_notebook_names, select_notebooks


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

    def test_rejects_a_notebooks_value_that_is_not_a_list_of_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("notebooks = 1\n", encoding="utf-8")
            with self.assertRaises(NotebookConfigError):
                load_notebook_names(path)


if __name__ == "__main__":
    unittest.main()
