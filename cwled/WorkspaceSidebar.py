"""
The left panel of a window: the application title above the "Workspace" and
"Recent" panels (Composer: the side panel with "My Projects | Public Apps").

The main window and every window that tabs were torn off into have one. Each
shows the folders of the workspace of its window.
"""
from pathlib import Path
from typing import Iterable, List

from PyQt6.QtCore import QMimeData, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QStackedWidget, QTabBar,
                             QVBoxLayout, QWidget)

import theme
from WorkspaceContents import WorkspaceContents


class RecentFilesList(QListWidget):
    """Recently opened files. They can be dragged, e.g. onto a workflow to
    add them as steps."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

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
            item = QListWidgetItem(theme.icon('file-o', color=theme.SMOKE), Path(file_path).name)
            item.setToolTip(str(file_path))
            item.setData(Qt.ItemDataRole.UserRole, str(file_path))
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
        title_layout.setContentsMargins(0, 0, 0, 0)
        app_title = QLabel(
            f'<span style="font-family:\'{theme.TITLE_FONT_FAMILY}\'">CWL</span>'
            f'<span style="font-family:\'{theme.TITLE_FONT_FAMILY}\'; font-weight:300">ed</span>'
        )
        app_title.setObjectName('appTitle')
        title_font = QFont(theme.TITLE_FONT_FAMILY)
        title_font.setPointSizeF(QApplication.font().pointSizeF() + 2)
        app_title.setFont(title_font)
        title_layout.addWidget(app_title)
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

    def setRecentFiles(self, files: Iterable[str]):
        self.recent_panel.setFiles(files)

    def showWorkspace(self):
        """Show the 'Workspace' panel."""
        self.tabs.setCurrentIndex(self.pages.indexOf(self.workspace_panel))
