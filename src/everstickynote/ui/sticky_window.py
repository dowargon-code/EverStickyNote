"""One always-on-top window for a single Evernote note."""

from __future__ import annotations

import re

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizeGrip,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from everstickynote.app_icon import app_icon

COLORS = {
    "yellow": ("#fff3a3", "#3d3200"),
    "green": ("#c8f7c5", "#123314"),
    "blue": ("#c9e7ff", "#10283d"),
    "pink": ("#ffd0e0", "#3d1424"),
    "purple": ("#e4d4ff", "#2a1840"),
    "gray": ("#e6e6e6", "#222222"),
}
COLOR_ORDER = list(COLORS)
RESIZE_DEBOUNCE_MS = 200

_URL_PATTERN = re.compile(
    r"(?:https?://|evernote:///)[^\s<>\"'\u3000「」『』（）【】〈〉《》、。]+",
    re.IGNORECASE,
)


def iter_urls(text: str):
    """Yield (start, end, url) spans for clickable links in plain text."""
    for match in _URL_PATTERN.finditer(text):
        url = match.group(0)
        end = match.end()
        while url:
            last = url[-1]
            if last in ".,;:!?":
                url = url[:-1]
                end -= 1
            elif last == ")" and url.count(")") > url.count("("):
                url = url[:-1]
                end -= 1
            elif last == "]" and url.count("]") > url.count("["):
                url = url[:-1]
                end -= 1
            else:
                break
        if "://" not in url:
            continue
        after_scheme = url.split("://", 1)[1].lstrip("/")
        if not after_scheme:
            continue
        yield match.start(), end, url


class _UrlHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#1a5fb4"))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
        for start, end, _url in iter_urls(text):
            self.setFormat(start, end - start, fmt)


class NoteBodyEdit(QTextEdit):
    """QTextEdit that opens http(s)/evernote links on click when read-only."""

    urlClicked = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._press_pos: QPoint | None = None
        self._press_url: str | None = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._highlighter = _UrlHighlighter(self.document())

    def url_at(self, pos: QPoint) -> str | None:
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        if not block.isValid():
            return None
        offset = cursor.positionInBlock()
        block_text = block.text()
        for start, end, url in iter_urls(block_text):
            if not (start <= offset <= end):
                continue
            rect = self.cursorRect(cursor)
            if pos.y() < rect.top() - 2 or pos.y() > rect.bottom() + 2:
                continue
            if offset == start and pos.x() < rect.x() - 4:
                continue
            if offset == end and pos.x() > rect.x() + 4:
                continue
            return url
        return None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.isReadOnly():
            url = self.url_at(event.position().toPoint())
            shape = Qt.CursorShape.PointingHandCursor if url else Qt.CursorShape.IBeamCursor
            self.viewport().setCursor(shape)
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    def mousePressEvent(self, event):
        if self.isReadOnly() and event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_url = self.url_at(self._press_pos)
        else:
            self._press_pos = None
            self._press_url = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if (
            self.isReadOnly()
            and event.button() == Qt.MouseButton.LeftButton
            and self._press_url is not None
            and self._press_pos is not None
        ):
            release_pos = event.position().toPoint()
            moved = (release_pos - self._press_pos).manhattanLength()
            if (
                moved <= QApplication.startDragDistance()
                and not self.textCursor().hasSelection()
                and self.url_at(release_pos) == self._press_url
            ):
                self.urlClicked.emit(self._press_url)
        self._press_pos = None
        self._press_url = None


def arrange_positions(
    sizes: list[tuple[int, int]],
    area: tuple[int, int, int, int],
    ratio: float = 0.7,
    margin: int = 8,
) -> list[tuple[int, int]]:
    """Place windows from the top-right, down the main screen, then left."""
    left, top, width, height = area
    screen_right = left + width
    bottom_limit = top + int(height * ratio)
    column_right = screen_right - margin
    column_left = column_right
    y = top + margin
    positions: list[tuple[int, int]] = []
    for item_width, item_height in sizes:
        if y + item_height > bottom_limit and y > top + margin:
            column_right = column_left - margin
            column_left = column_right
            y = top + margin
        x = column_right - item_width
        positions.append((x, y))
        column_left = min(column_left, x)
        y += item_height + margin
    return positions


class HeaderBar(QWidget):
    released = Signal()
    doubleClicked = Signal()

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

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = None
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class StickyWindow(QWidget):
    edited = Signal(str)
    closeRequested = Signal(str)
    colorChanged = Signal(str, str)
    pinChanged = Signal(str, bool)
    geometryChanged = Signal(str)
    pullRequested = Signal(str)
    openRequested = Signal(str)
    arrangeRequested = Signal(str)
    mainRequested = Signal(str)
    newNoteRequested = Signal(str)
    updateNoticeFinished = Signal(str)
    urlClicked = Signal(str)

    def __init__(self, guid: str, color: str = "yellow", pinned: bool = True):
        super().__init__()
        self.guid = guid
        self._color = color if color in COLORS else "yellow"
        self._pinned = pinned
        self._rich = False
        self._updated = False
        self._flicker_on = False
        self._flicker_elapsed = 0
        self._flicker_limit_ms = 5000
        self._flicker_timer = QTimer(self)
        self._flicker_timer.setInterval(250)
        self._flicker_timer.timeout.connect(self._tick_update_flicker)
        self.setObjectName("stickyRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(240, 200)
        self.resize(300, 280)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._emit_resize_geometry)
        self._apply_flags()
        self._build()
        self._apply_style()

    def _apply_flags(self) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self._pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowIcon(app_icon())

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        self._bar = HeaderBar()
        self._bar.released.connect(self._on_header_released)
        self._bar.doubleClicked.connect(lambda: self.openRequested.emit(self.guid))
        bar_layout = QHBoxLayout(self._bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(4)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("タイトル")
        font = QFont("Yu Gothic UI", 11)
        font.setBold(True)
        self.title_edit.setFont(font)
        self.title_edit.textChanged.connect(self._on_title_changed)
        bar_layout.addWidget(self.title_edit, 1)

        self.arrange_button = QPushButton("整列")
        self.arrange_button.clicked.connect(lambda: self.arrangeRequested.emit(self.guid))
        bar_layout.addWidget(self.arrange_button)

        self.color_button = QPushButton("色")
        self.color_button.setFixedWidth(36)
        self.color_button.clicked.connect(self._cycle_color)
        bar_layout.addWidget(self.color_button)

        self.pin_button = QPushButton("最前面")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self._pinned)
        self.pin_button.clicked.connect(self._toggle_pin)
        bar_layout.addWidget(self.pin_button)

        self.close_button = QPushButton("閉じる")
        self.close_button.clicked.connect(lambda: self.closeRequested.emit(self.guid))
        bar_layout.addWidget(self.close_button)
        for button in (self.arrange_button, self.color_button, self.pin_button, self.close_button):
            button.setCursor(Qt.CursorShape.ArrowCursor)
        self._header_buttons = (
            self.arrange_button,
            self.color_button,
            self.pin_button,
            self.close_button,
        )
        self._set_header_buttons_visible(False)
        root.addWidget(self._bar)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.hide()
        root.addWidget(self.banner)

        self.pull_button = QPushButton("Evernote側を取り込む")
        self.pull_button.hide()
        self.pull_button.clicked.connect(lambda: self.pullRequested.emit(self.guid))
        root.addWidget(self.pull_button)

        self.body_edit = NoteBodyEdit()
        self.body_edit.setPlaceholderText("メモ")
        self.body_edit.setFont(QFont("Yu Gothic UI", 10))
        self.body_edit.textChanged.connect(self._emit_edited)
        self.body_edit.urlClicked.connect(self._on_body_url_clicked)
        root.addWidget(self.body_edit, 1)
        for widget in (self, self._bar, self.title_edit, self.body_edit):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(self._popup_main_menu)

        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        self._grip = QSizeGrip(self)
        grip_row.addWidget(self._grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        root.addLayout(grip_row)

    def _on_header_released(self) -> None:
        self.cancel_pending_geometry()
        self.geometryChanged.emit(self.guid)

    def _emit_resize_geometry(self) -> None:
        self.geometryChanged.emit(self.guid)

    def flush_geometry(self) -> None:
        if hasattr(self, "_resize_timer") and self._resize_timer.isActive():
            self._resize_timer.stop()
            self.geometryChanged.emit(self.guid)

    def cancel_pending_geometry(self) -> None:
        if hasattr(self, "_resize_timer") and self._resize_timer.isActive():
            self._resize_timer.stop()

    def _on_body_url_clicked(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
        self.urlClicked.emit(url)

    def _set_header_buttons_visible(self, visible: bool) -> None:
        for button in self._header_buttons:
            button.setVisible(visible)

    def enterEvent(self, event):
        self._set_header_buttons_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_header_buttons_visible(False)
        super().leaveEvent(event)

    def mark_updated(self, seconds: float = 5) -> None:
        self._updated = True
        self._flicker_on = True
        self._flicker_elapsed = 0
        self._flicker_limit_ms = max(0, int(seconds * 1000))
        self._apply_style()
        if self._flicker_limit_ms <= 0:
            self._finish_update_flicker()
            return
        self._flicker_timer.start()

    def _tick_update_flicker(self) -> None:
        self._flicker_elapsed += self._flicker_timer.interval()
        if self._flicker_elapsed >= self._flicker_limit_ms:
            self._finish_update_flicker()
            return
        self._flicker_on = not self._flicker_on
        self._apply_style()

    def _finish_update_flicker(self) -> None:
        self._flicker_timer.stop()
        self._updated = False
        self._flicker_on = False
        self._apply_style()
        self.updateNoticeFinished.emit(self.guid)

    def _apply_style(self) -> None:
        background, foreground = COLORS[self._color]
        border = (
            "3px solid #e07000"
            if self._updated and self._flicker_on
            else "1px solid rgba(0, 0, 0, 90)"
        )
        self.setStyleSheet(
            f"""
            QWidget#stickyRoot {{
                background: {background};
                color: {foreground};
                border: {border};
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

    def _build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("メインフォームを開く", lambda: self.mainRequested.emit(self.guid))
        menu.addAction("新規作成", lambda: self.newNoteRequested.emit(self.guid))
        return menu

    def _popup_main_menu(self, pos) -> None:
        widget = self.sender()
        if not isinstance(widget, QWidget):
            widget = self
        menu = self._build_context_menu()
        menu.exec(widget.mapToGlobal(pos))

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

    def set_read_only(self, message: str) -> None:
        self.title_edit.setReadOnly(True)
        self.body_edit.setReadOnly(True)
        self.title_edit.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.banner.hide()

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

    def pinned(self) -> bool:
        return self._pinned

    def place(self, x: int | None, y: int | None, width: int | None, height: int | None, index: int) -> None:
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
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def closeEvent(self, event):
        self.flush_geometry()
        super().closeEvent(event)

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
