"""One always-on-top window for a single Evernote note."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizeGrip,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

COLORS = {
    "yellow": ("#fff3a3", "#3d3200"),
    "green": ("#c8f7c5", "#123314"),
    "blue": ("#c9e7ff", "#10283d"),
    "pink": ("#ffd0e0", "#3d1424"),
    "purple": ("#e4d4ff", "#2a1840"),
    "gray": ("#e6e6e6", "#222222"),
}
COLOR_ORDER = list(COLORS)


# class DragHandle(QLabel):
#     released = Signal()
#
#     def __init__(self):
#         super().__init__("移動")
#         self._offset: QPoint | None = None
#         self.setCursor(Qt.CursorShape.SizeAllCursor)
#
#     def mousePressEvent(self, event):
#         if event.button() == Qt.MouseButton.LeftButton:
#             self._offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
#         super().mousePressEvent(event)
#
#     def mouseMoveEvent(self, event):
#         if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
#             self.window().move(event.globalPosition().toPoint() - self._offset)
#         super().mouseMoveEvent(event)
#
#     def mouseReleaseEvent(self, event):
#         if self._offset is not None:
#             self._offset = None
#             self.released.emit()
#         super().mouseReleaseEvent(event)
# 2026/09/23 変更 ---＞
class HeaderBar(QWidget):
    released = Signal()
    # 2026/09/23 変更 ---＞
    doubleClicked = Signal()
    # <--- 2026/09/23 変更

    def __init__(self):
        super().__init__()
        self._offset: QPoint | None = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFixedHeight(36)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._offset is not None:
            self._offset = None
            self.released.emit()
        super().mouseReleaseEvent(event)

    # 2026/09/23 変更 ---＞
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = None
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)
    # <--- 2026/09/23 変更
# <--- 2026/09/23 変更


class StickyWindow(QWidget):
    edited = Signal(str)
    closeRequested = Signal(str)
    colorChanged = Signal(str, str)
    pinChanged = Signal(str, bool)
    geometryChanged = Signal(str)
    pullRequested = Signal(str)
    # 2026/09/23 変更 ---＞
    openRequested = Signal(str)
    # <--- 2026/09/23 変更

    def __init__(self, guid: str, color: str = "yellow", pinned: bool = True):
        super().__init__()
        self.guid = guid
        self._color = color if color in COLORS else "yellow"
        self._pinned = pinned
        self._rich = False
        self.setObjectName("stickyRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(240, 200)
        self.resize(300, 280)
        self._apply_flags()
        self._build()
        self._apply_style()

    def _apply_flags(self) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self._pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # self._bar = QWidget()
        # self._bar.setFixedHeight(36)
        # 2026/09/23 変更 ---＞
        self._bar = HeaderBar()
        self._bar.released.connect(lambda: self.geometryChanged.emit(self.guid))
        self._bar.doubleClicked.connect(lambda: self.openRequested.emit(self.guid))
        # <--- 2026/09/23 変更
        bar_layout = QHBoxLayout(self._bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(4)

        # self.drag_handle = DragHandle()
        # self.drag_handle.released.connect(lambda: self.geometryChanged.emit(self.guid))
        # bar_layout.addWidget(self.drag_handle)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("タイトル")
        font = QFont("Yu Gothic UI", 11)
        font.setBold(True)
        self.title_edit.setFont(font)
        self.title_edit.textChanged.connect(self._on_title_changed)
        bar_layout.addWidget(self.title_edit, 1)

        self.color_button = QPushButton("色")
        self.color_button.setFixedWidth(36)
        self.color_button.clicked.connect(self._cycle_color)
        bar_layout.addWidget(self.color_button)

        # self.pin_button = QPushButton("最前面")
        # 2026/09/23 変更 ---＞
        # self.pin_button = QPushButton("最前面解除" if self._pinned else "最前面")
        # <--- 2026/09/23 変更
        # 2026/09/23 変更 ---＞
        self.pin_button = QPushButton("最前面")
        # <--- 2026/09/23 変更
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self._pinned)
        self.pin_button.clicked.connect(self._toggle_pin)
        bar_layout.addWidget(self.pin_button)

        self.close_button = QPushButton("閉じる")
        self.close_button.clicked.connect(lambda: self.closeRequested.emit(self.guid))
        bar_layout.addWidget(self.close_button)
        # 2026/09/23 変更 ---＞
        for button in (self.color_button, self.pin_button, self.close_button):
            button.setCursor(Qt.CursorShape.ArrowCursor)
        # <--- 2026/09/23 変更
        root.addWidget(self._bar)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.hide()
        root.addWidget(self.banner)

        self.pull_button = QPushButton("Evernote側を取り込む")
        self.pull_button.hide()
        self.pull_button.clicked.connect(lambda: self.pullRequested.emit(self.guid))
        root.addWidget(self.pull_button)

        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("メモ")
        self.body_edit.setFont(QFont("Yu Gothic UI", 10))
        self.body_edit.textChanged.connect(self._emit_edited)
        root.addWidget(self.body_edit, 1)

        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        self._grip = QSizeGrip(self)
        grip_row.addWidget(self._grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        root.addLayout(grip_row)

    def _apply_style(self) -> None:
        background, foreground = COLORS[self._color]
        self.setStyleSheet(
            f"""
            QWidget#stickyRoot {{
                background: {background};
                color: {foreground};
                border: 1px solid rgba(0, 0, 0, 90);
            }}
            QLineEdit, QTextEdit {{
                background: transparent;
                border: none;
                color: {foreground};
            }}
            QPushButton {{
                background: rgba(255, 255, 255, 120);
                border: none;
                color: {foreground};
                padding: 2px 6px;
            }}
            QLabel {{
                color: {foreground};
            }}
            """
        )

    def note_title(self) -> str:
        return self.title_edit.text()

    def note_text(self) -> str:
        return self.body_edit.toPlainText()

    def set_content(self, title: str, text: str) -> None:
        self.title_edit.blockSignals(True)
        self.body_edit.blockSignals(True)
        self.title_edit.setText(title)
        self.body_edit.setPlainText(text)
        self.setWindowTitle(title or "無題")
        self.title_edit.blockSignals(False)
        self.body_edit.blockSignals(False)

    # def set_read_only(self, message: str) -> None:
    #     self.title_edit.setReadOnly(True)
    #     self.body_edit.setReadOnly(True)
    #     self.banner.setText(message)
    #     self.banner.show()
    # 2026/09/23 変更 ---＞
    # def set_read_only(self, message: str) -> None:
    #     self.title_edit.setReadOnly(True)
    #     self.body_edit.setReadOnly(True)
    #     self.banner.hide()
    # <--- 2026/09/23 変更
    # 2026/09/23 変更 ---＞
    def set_read_only(self, message: str) -> None:
        self.title_edit.setReadOnly(True)
        self.body_edit.setReadOnly(True)
        self.title_edit.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.banner.hide()
    # <--- 2026/09/23 変更

    def set_rich(self, rich: bool) -> None:
        self._rich = rich
        self.title_edit.setReadOnly(rich)
        self.body_edit.setReadOnly(rich)
        if rich:
            self.banner.setText("画像や装飾を含むため、この付箋では編集できません。")
            self.banner.show()
        elif not self.pull_button.isVisible():
            self.banner.hide()

    def set_conflict(self, conflict: bool) -> None:
        self.pull_button.setVisible(conflict)
        if conflict:
            self.banner.setText("Evernote側が新しいため、上書きを止めています。")
            self.banner.show()
        elif not self._rich:
            self.banner.hide()

    def set_color(self, color: str) -> None:
        if color not in COLORS:
            color = "yellow"
        self._color = color
        self._apply_style()

    def color(self) -> str:
        return self._color

    # def set_pinned(self, pinned: bool) -> None:
    #     if pinned == self._pinned:
    #         self.pin_button.setChecked(pinned)
    #         return
    #     self._pinned = pinned
    #     self.pin_button.setChecked(pinned)
    #     self._apply_flags()
    #     if self.isVisible():
    #         self.show()
    # 2026/09/23 変更 ---＞
    # def set_pinned(self, pinned: bool) -> None:
    #     was_visible = self.isVisible()
    #     geometry = self.geometry()
    #     self._pinned = pinned
    #     self.pin_button.setChecked(pinned)
    #     if pinned == self._pinned and self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint == (
    #         Qt.WindowType.WindowStaysOnTopHint if pinned else Qt.WindowType.Widget
    #     ):
    #         pass
    #     self._apply_flags()
    #     self.setGeometry(geometry)
    #     if was_visible:
    #         self.show()
    #         if pinned:
    #             self.raise_()
    #             self.activateWindow()
    # <--- 2026/09/23 変更
    # 2026/09/23 変更 ---＞
    # def set_pinned(self, pinned: bool) -> None:
    #     self.pin_button.setText("最前面解除" if pinned else "最前面")
    #     self.pin_button.setChecked(pinned)
    #     if pinned == self._pinned:
    #         return
    #     was_visible = self.isVisible()
    #     geometry = self.geometry()
    #     self._pinned = pinned
    #     self._apply_flags()
    #     self.setGeometry(geometry)
    #     if was_visible:
    #         self.show()
    # <--- 2026/09/23 変更
    # 2026/09/23 変更 ---＞
    def set_pinned(self, pinned: bool) -> None:
        self.pin_button.setChecked(pinned)
        if pinned == self._pinned:
            return
        was_visible = self.isVisible()
        geometry = self.geometry()
        self._pinned = pinned
        self._apply_flags()
        self.setGeometry(geometry)
        if was_visible:
            self.show()
    # <--- 2026/09/23 変更

    def pinned(self) -> bool:
        return self._pinned

    def place(self, x: int | None, y: int | None, width: int | None, height: int | None, index: int) -> None:
        from PySide6.QtWidgets import QApplication

        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        width = width or 300
        height = height or 280
        if x is None or y is None:
            x = area.x() + 48 + (index % 8) * 28
            y = area.y() + 48 + (index % 8) * 28
        if x + 80 > area.right():
            x = area.x() + 48
        if y + 80 > area.bottom():
            y = area.y() + 48
        self.setGeometry(x, y, width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.geometryChanged.emit(self.guid)

    def _emit_edited(self) -> None:
        self.edited.emit(self.guid)

    def _on_title_changed(self, title: str) -> None:
        self.setWindowTitle(title or "無題")
        self._emit_edited()

    def _cycle_color(self) -> None:
        index = COLOR_ORDER.index(self._color)
        color = COLOR_ORDER[(index + 1) % len(COLOR_ORDER)]
        self.set_color(color)
        self.colorChanged.emit(self.guid, color)

    def _toggle_pin(self) -> None:
        pinned = self.pin_button.isChecked()
        self.set_pinned(pinned)
        self.pinChanged.emit(self.guid, pinned)
