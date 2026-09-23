# """Desktop sticky notes backed by one Evernote notebook."""
# 2026/09/23 変更 ---＞
"""Read-only desktop sticky notes from the local Evernote app data."""
# <--- 2026/09/23 変更

import sys

from PySide6.QtWidgets import QApplication

# from ui.main_window import MainWindow
# 2026/09/23 変更 ---＞
from ui.local_window import LocalMainWindow
# <--- 2026/09/23 変更


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EverStickyNote")
    # window = MainWindow()
    # 2026/09/23 変更 ---＞
    window = LocalMainWindow()
    # <--- 2026/09/23 変更
    # window.show()
    # 2026/09/23 変更 ---＞
    window.show_saved_state()
    # <--- 2026/09/23 変更
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
