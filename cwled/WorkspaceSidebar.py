"""
The left panel of a window: the application title above the "Workspace" and
"Recent" panels (Composer: the side panel with "My Projects | Public Apps").

The main window and every window that tabs were torn off into have one. Each
shows the folders of the workspace of its window.
"""
import re
from pathlib import Path
from typing import Iterable, List, Optional

from PyQt6.QtCore import QMimeData, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QStackedWidget, QStyle,
                             QStyledItemDelegate, QStyleOptionViewItem, QTabBar,
                             QVBoxLayout, QWidget)

import logo
import theme
from WorkspaceContents import WorkspaceContents


ROLE_FOLDER = Qt.ItemDataRole.UserRole + 1
_CLASS_PATTERN = re.compile(r'^\s*["\']?class["\']?\s*:\s*["\']?([A-Za-z]+)')
_CLASS_ICONS = {'Workflow': 'workflow', 'CommandLineTool': 'tool', 'ExpressionTool': 'expressiontool'}


def documentClass(file_path: str) -> Optional[str]:
    """The CWL class of a document (Workflow, CommandLineTool...), from its first lines."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as handle:
            for number, line in enumerate(handle):
                match = _CLASS_PATTERN.search(line)
                if match and match.group(1) in _CLASS_ICONS:
                    return match.group(1)
                if number > 400:
                    break
    except OSError:
        pass
    return None


def _folderHint(file_path: str) -> str:
    """The last two folders of a path, as Composer shows under a file name."""
    parts = Path(file_path).parent.parts
    return "/".join(parts[-2:]) if len(parts) > 1 else str(Path(file_path).parent)


class _RecentItemDelegate(QStyledItemDelegate):
    """A recent file: its name, then its folder in the muted colour."""

    def paint(self, painter, option, index):
        folder = index.data(ROLE_FOLDER)
        if not folder:
            return super().paint(painter, option, index)
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        name, item.text = item.text, ""
        widget = item.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, item, widget)
        metrics = item.fontMetrics
        name = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, rect.width())
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        selected = bool(item.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setPen(QColor(theme.WHITE if selected else theme.TEXT))
        painter.drawText(rect, align, name)
        rest = rect.adjusted(metrics.horizontalAdvance(name) + 10, 0, 0, 0)
        if rest.width() > 24:
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(rest, align, metrics.elidedText(folder, Qt.TextElideMode.ElideLeft, rest.width()))
        painter.restore()


class RecentFilesList(QListWidget):
    """Recently opened files. They can be dragged, e.g. onto a workflow to
    add them as steps."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setItemDelegate(_RecentItemDelegate(self))

    def mimeData(self, items):
        mime_data = QMimeData()
        paths = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in paths if path])
        return mime_data

    def setFiles(self, files: Iterable[str]):
        """Show these files (most recent first), or a placeholder."""
        self.clear()
        files = list(files)
        for file_path in files:
            icon_key = _CLASS_ICONS.get(documentClass(file_path))
            item_icon = theme.icon(icon_key) if icon_key else theme.icon('file-o', color=theme.SMOKE)
            item = QListWidgetItem(item_icon, Path(file_path).name)
            item.setToolTip(str(file_path))
            item.setData(Qt.ItemDataRole.UserRole, str(file_path))
            item.setData(ROLE_FOLDER, _folderHint(file_path))
            self.addItem(item)
        if not files:
            placeholder = QListWidgetItem("No recent files")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(placeholder)


class WorkspaceSidebar(QWidget):
    """The side panel: application title, then the 'Workspace' / 'Recent' panels."""

    fileSelected = pyqtSignal(str)          # a file of the workspace was opened
    recentFileSelected = pyqtSignal(str)    # a recent file was opened
    addFolderRequested = pyqtSignal()
    removeFolderRequested = pyqtSignal(str)
    addRemoteFolderRequested = pyqtSignal()
    syncRemoteFolderRequested = pyqtSignal(str)
    remoteFolderOpened = pyqtSignal(str)
    remoteRescanRequested = pyqtSignal(list)
    currentFolderChanged = pyqtSignal(str)

    def __init__(self, folders: List[str], parent=None):
        super().__init__(parent)
        self.setObjectName('sidebar')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = QWidget(self)
        title_bar.setObjectName('titleBar')
        title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        title_bar.setFixedHeight(theme.ACTION_BAR_HEIGHT)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 0, 0, 0)
        title_layout.setSpacing(-4)             # the title has a padding of its own (see theme.STYLE_SHEET)
        mark = QLabel(title_bar)                # the logo, before the name
        mark.setPixmap(logo.markPixmap(30, tile=False))
        title_layout.addWidget(mark)
        app_title = QLabel(
            f'<span style="font-family:\'{theme.TITLE_FONT_FAMILY}\'">CWL</span>'
            f'<span style="font-family:\'{theme.TITLE_FONT_FAMILY}\'; font-weight:300">ed</span>'
        )
        app_title.setObjectName('appTitle')
        title_font = QFont(theme.TITLE_FONT_FAMILY)
        title_font.setPointSizeF(QApplication.font().pointSizeF() + 2)
        app_title.setFont(title_font)
        title_layout.addWidget(app_title)
        title_layout.addStretch(1)
        layout.addWidget(title_bar)

        # Panel selector (Composer: "My Projects | Public Apps")
        self.tabs = QTabBar(self)
        self.tabs.setExpanding(True)
        self.tabs.setDrawBase(False)
        self.tabs.addTab("Workspace")
        self.tabs.addTab("Recent")
        layout.addWidget(self.tabs)

        self.pages = QStackedWidget(self)
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)

        # one root per workspace folder (Composer "Local Files")
        self.workspace_panel = WorkspaceContents(workspace_path=folders, parent=self, sidebar=True)
        self.workspace_panel.setWindowFlags(Qt.WindowType.Widget)
        self.workspace_panel.fileSelected.connect(self.fileSelected)
        self.workspace_panel.addFolderRequested.connect(self.addFolderRequested)
        self.workspace_panel.removeFolderRequested.connect(self.removeFolderRequested)
        self.workspace_panel.currentFolderChanged.connect(self.currentFolderChanged)
        self.workspace_panel.addRemoteFolderRequested.connect(self.addRemoteFolderRequested)
        self.workspace_panel.syncRemoteFolderRequested.connect(self.syncRemoteFolderRequested)
        self.workspace_panel.remoteFolderOpened.connect(self.remoteFolderOpened)
        self.workspace_panel.remoteRescanRequested.connect(self.remoteRescanRequested)
        self.pages.addWidget(self.workspace_panel)

        self.recent_panel = self.buildRecentList()
        self.pages.addWidget(self.recent_panel)
        layout.addWidget(self.pages, 1)

    def buildRecentList(self) -> RecentFilesList:
        """A list of recent files that opens the file that is double clicked."""
        recent_list = RecentFilesList()
        recent_list.setIconSize(QSize(16, 16))
        recent_list.itemDoubleClicked.connect(
            lambda item: self.recentFileSelected.emit(item.data(Qt.ItemDataRole.UserRole)))
        return recent_list

    def setWorkspaceFolders(self, folders: List[str]):
        self.workspace_panel.setWorkspaceFolders(folders)

    def setRemoteLabels(self, labels: dict):
        self.workspace_panel.setRemoteLabels(labels)

    def setRecentFiles(self, files: Iterable[str]):
        self.recent_panel.setFiles(files)

    def showWorkspace(self):
        """Show the 'Workspace' panel."""
        self.tabs.setCurrentIndex(self.pages.indexOf(self.workspace_panel))
