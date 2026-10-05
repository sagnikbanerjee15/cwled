"""
The tab that compares two documents side by side (see DocumentDiff).

The two texts are shown line by line against each other, with gaps where a side
has no counterpart, scrolling together. The lines that differ are coloured, the
parts that changed (inputs, outputs, steps...) are listed on the left, and the
steps that were added, removed or changed can be marked in the graphs of the
documents that are open.
"""
import logging
import time
from typing import Callable, List, Optional

from PyQt6 import sip
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QTextCursor, QTextFormat
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
                             QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget)

import data
import theme
from DocumentDiff import (ADDED, CHANGED, EQUAL, PAD, REMOVED, Change, DocumentSource, Line, alignedLines,
                          changeBlocks, stepStates, structuralChanges)

logger = logging.getLogger(__name__)

# Backgrounds of the lines (dark theme)
LINE_COLORS = {
    ADDED: '#27421f',
    REMOVED: '#4d2626',
    CHANGED: '#4a3b1c',
    PAD: '#2b2b2b',
}
CHANGE_COLORS = {ADDED: theme.GREEN, REMOVED: theme.RED, CHANGED: theme.CARROT}
CHANGE_ICONS = {ADDED: 'plus', REMOVED: 'minus', CHANGED: 'pencil'}
SourceFactory = Callable[[], DocumentSource]


class DiffView(QWidget):
    """Two documents side by side. ``left_factory`` and ``right_factory`` make the sources (again, when refreshed)."""

    def __init__(self, left_factory: SourceFactory, right_factory: SourceFactory, parent=None):
        super().__init__(parent)
        self.setObjectName('diffView')
        self._factories = [left_factory, right_factory]
        self.left: Optional[DocumentSource] = None
        self.right: Optional[DocumentSource] = None
        self.left_lines: List[Line] = []
        self.right_lines: List[Line] = []
        self.changes: List[Change] = []
        self.blocks = []                # runs of lines that differ, as (first row, last row)
        self._syncing = False
        self._highlighted = []          # the documents whose graphs are marked

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._buildHeader())

        body = QSplitter(Qt.Orientation.Horizontal, self)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(1)
        self.change_list = QListWidget(body)
        self.change_list.setMinimumWidth(160)
        self.change_list.setIconSize(QSize(12, 12))
        self.change_list.itemClicked.connect(self._onChangeClicked)
        body.addWidget(self.change_list)
        panes = QSplitter(Qt.Orientation.Horizontal, body)
        panes.setHandleWidth(1)
        panes.setChildrenCollapsible(False)
        self.left_title, self.left_edit = self._buildPane(panes)
        self.right_title, self.right_edit = self._buildPane(panes)
        body.addWidget(panes)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([230, 1000])
        layout.addWidget(body, 1)

        for first, second in ((self.left_edit, self.right_edit), (self.right_edit, self.left_edit)):
            for bar in (first.verticalScrollBar(), first.horizontalScrollBar()):
                bar.valueChanged.connect(lambda _value, a=first, b=second: self._syncScroll(a, b))
        self.refresh()

    # -- construction ---------------------------------------------------------------------------------
    def _buildHeader(self) -> QWidget:
        header = QWidget(self)
        header.setObjectName('actionBar')
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setFixedHeight(theme.ACTION_BAR_HEIGHT)
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(6)
        self.previous_button = self._tool(row, 'arrow-up', "Previous difference", lambda: self.goToBlock(-1))
        self.next_button = self._tool(row, 'arrow-down', "Next difference", lambda: self.goToBlock(1))
        self.summary = QLabel(header)
        row.addWidget(self.summary)
        row.addStretch(1)
        self.highlight_check = QCheckBox("Mark the steps in the graphs", header)
        self.highlight_check.setToolTip("Mark the steps that were added, removed or changed in the graphs of the "
                                        "documents that are open")
        self.highlight_check.setChecked(True)
        self.highlight_check.toggled.connect(lambda _checked: self._applyHighlights())
        row.addWidget(self.highlight_check)
        self.swap_button = self._tool(row, 'exchange', "Swap the sides", self.swap)
        self.refresh_button = self._tool(row, 'refresh', "Compare again (documents and files are read again)", self.refresh)
        return header

    def _tool(self, row, glyph, tooltip, slot):
        from PyQt6.QtWidgets import QToolButton
        button = QToolButton(self)
        button.setIcon(theme.icon(glyph))
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.clicked.connect(lambda _checked=False: slot())
        row.addWidget(button)
        return button

    def _buildPane(self, parent):
        pane = QWidget(parent)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title = QLabel(pane)
        title.setProperty('muted', True)
        title.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(title)
        edit = QPlainTextEdit(pane)
        edit.setReadOnly(True)
        edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        edit.setFont(self._font())
        layout.addWidget(edit, 1)
        parent.addWidget(pane)
        return title, edit

    @staticmethod
    def _font() -> QFont:
        configuration = (data.configuration or {}).get('code_editor', {}) or {}
        font = QFont(configuration.get('font_family', 'monospace'))
        font.setStyleHint(QFont.StyleHint.Monospace)
        try:
            font.setPointSize(int(configuration.get('font_size', 12)))
        except (TypeError, ValueError):
            font.setPointSize(12)
        return font

    # -- content --------------------------------------------------------------------------------------------
    def title(self) -> str:
        left = self.left.label if self.left else '?'
        right = self.right.label if self.right else '?'
        return f"{left} ↔ {right}"

    def refresh(self):
        """Read both sides again and compare them."""
        try:
            left, right = (factory() for factory in self._factories)
        except Exception as e:
            logger.error(f"Cannot compare: {e}")
            self.summary.setText(f"Cannot compare: {e}")
            self.summary.setStyleSheet(f"color: {theme.RED};")
            return
        self.left, self.right = left, right
        self.left_lines, self.right_lines = alignedLines(left.text(), right.text())
        self.changes = structuralChanges(left.cwl, right.cwl, self.left_lines, self.right_lines)
        self.blocks = changeBlocks(self.right_lines)
        for title, source in ((self.left_title, left), (self.right_title, right)):
            title.setText(source.label)
            title.setToolTip(source.detail)
        self._fill(self.left_edit, self.left_lines)
        self._fill(self.right_edit, self.right_lines)
        self.change_list.clear()
        for change in self.changes:
            item = QListWidgetItem(theme.icon(CHANGE_ICONS[change.kind], color=CHANGE_COLORS[change.kind]),
                                   change.describe().split(' ', 1)[1])
            item.setData(Qt.ItemDataRole.UserRole, change.row)
            item.setToolTip({ADDED: "Only in " + right.label, REMOVED: "Only in " + left.label,
                             CHANGED: "Different"}[change.kind])
            self.change_list.addItem(item)
        if not self.changes:
            placeholder = QListWidgetItem("No changes")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.change_list.addItem(placeholder)
        if self.blocks:
            self.summary.setText(f"{len(self.blocks)} difference{'s' if len(self.blocks) != 1 else ''}"
                                 f" · {len(self.changes)} part{'s' if len(self.changes) != 1 else ''} changed"
                                 f" · {time.strftime('%H:%M:%S')}")
            self.summary.setStyleSheet("")
        else:
            self.summary.setText("The documents are the same")
            self.summary.setStyleSheet(f"color: {theme.GREEN};")
        self.previous_button.setEnabled(bool(self.blocks))
        self.next_button.setEnabled(bool(self.blocks))
        self._applyHighlights()

    def swap(self):
        self._factories.reverse()
        self.refresh()

    def _fill(self, edit: QPlainTextEdit, lines: List[Line]):
        edit.setPlainText('\n'.join(line.text for line in lines))
        selections = []
        document = edit.document()
        for row, line in enumerate(lines):
            if line.kind == EQUAL:
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(LINE_COLORS[line.kind]))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = QTextCursor(document.findBlockByNumber(row))
            selections.append(selection)
        edit.setExtraSelections(selections)
        edit.moveCursor(QTextCursor.MoveOperation.Start)

    # -- navigation -----------------------------------------------------------------------------------------
    def _syncScroll(self, source: QPlainTextEdit, target: QPlainTextEdit):
        if self._syncing:
            return
        self._syncing = True
        try:
            target.verticalScrollBar().setValue(source.verticalScrollBar().value())
            target.horizontalScrollBar().setValue(source.horizontalScrollBar().value())
        finally:
            self._syncing = False

    def currentRow(self) -> int:
        return self.right_edit.textCursor().blockNumber()

    def goToRow(self, row: int):
        """Show a row of the texts in both panes."""
        for edit in (self.left_edit, self.right_edit):
            block = edit.document().findBlockByNumber(max(0, row))
            edit.setTextCursor(QTextCursor(block))
            edit.centerCursor()

    def goToBlock(self, step: int):
        """Go to the next (``step`` 1) or previous (-1) run of lines that differ, around the end of the texts."""
        if not self.blocks:
            return
        row = self.currentRow()
        if step > 0:
            target = next((first for first, _last in self.blocks if first > row), self.blocks[0][0])
        else:
            target = next((first for first, _last in reversed(self.blocks) if first < row), self.blocks[-1][0])
        self.goToRow(target)

    def _onChangeClicked(self, item: QListWidgetItem):
        row = item.data(Qt.ItemDataRole.UserRole)
        if row is not None:
            self.goToRow(row)

    # -- the graphs ------------------------------------------------------------------------------------------
    def _applyHighlights(self):
        """Mark the steps that differ in the graphs of the documents that are open (or clear the marks)."""
        self._clearHighlights()
        if not self.highlight_check.isChecked() or self.left is None:
            return
        if self.left.cwl.get('class') != 'Workflow' or self.right.cwl.get('class') != 'Workflow':
            return
        states = stepStates(self.left.cwl, self.right.cwl)
        for side, source in (('left', self.left), ('right', self.right)):
            window = source.window
            if window is not None and not sip.isdeleted(window) and hasattr(window, 'setDiffStates'):
                window.setDiffStates(states[side])
                self._highlighted.append(window)

    def _clearHighlights(self):
        for window in self._highlighted:
            if not sip.isdeleted(window):
                window.setDiffStates({})
        self._highlighted = []

    def cleanup(self):
        """The tab is closed: the graphs are not marked any more."""
        self._clearHighlights()
