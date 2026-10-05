"""
The windows of the editor.

A ``WorkbenchWindow`` has a workspace side panel on the left and the tabs of
the open documents on the right (Composer's "workbox"). The main window is
one; ``DetachedWindow`` is the other kind: a window that tabs were torn off
the main window into, so that several documents can be compared side by side.

Each window has its own ``Workspace`` (the folders its side panel shows). A
detached window starts with a copy of the workspace it was torn off, and when
tabs move to another window the workspaces are merged, so the folders opened
in a detached window are not lost when its tabs are reattached.

The main window (``controller``) owns the documents, the menus and the
actions; the windows only host them.
"""
import logging
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox, QSizePolicy, QSplitter,
                             QToolButton, QWidget)

import theme
import workspaceFolders
from ChildWindow import ChildWindow
from DetachableTabs import DetachableTabWidget, moveTab
from WorkspaceSidebar import WorkspaceSidebar

logger = logging.getLogger(__name__)

SIDEBAR_WIDTH = 270


class WorkbenchWindow(QMainWindow):
    """
    A window with the workspace side panel on the left and document tabs on
    the right.

    Attributes:
        controller: the main window, which opens, closes and lists the documents.
        workspace: the folders shown by the side panel of this window.
        sidebar: the left panel.
        tabs: the document tabs.
    """

    def __init__(self, workspace: workspaceFolders.Workspace, controller: Optional['WorkbenchWindow'] = None,
                 parent=None):
        super().__init__(parent)
        self.controller = controller if controller is not None else self
        self.workspace = workspace
        self._followed = None       # (document, file) last selected in the Workspace panel by followCurrentDocument

    # -- layout -------------------------------------------------------------------
    def buildWorkbench(self):
        """Build the side panel, the document tabs and the status bar."""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName('mainSplitter')
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        self.sidebar = WorkspaceSidebar(self.workspace.folders(), self)
        self.sidebar.fileSelected.connect(self.openFile)
        self.sidebar.recentFileSelected.connect(self.openRecentFile)
        self.sidebar.addFolderRequested.connect(self.onAddWorkspaceFolder)
        self.sidebar.removeFolderRequested.connect(self.onRemoveWorkspaceFolder)
        self.sidebar.addRemoteFolderRequested.connect(self.onAddRemoteFolder)
        self.sidebar.syncRemoteFolderRequested.connect(self.controller.syncRemoteFolder)
        self.sidebar.currentFolderChanged.connect(self.onCurrentWorkspaceFolderChanged)
        self.sidebar.workspace_panel.followDocumentChanged.connect(
            lambda follow: follow and self.followCurrentDocument())
        splitter.addWidget(self.sidebar)

        self.tabs = DetachableTabWidget(self)
        self.tabs.setObjectName('workbox')
        self.tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabCloseRequested.connect(self.onTabCloseRequested)
        self.tabs.currentChanged.connect(self.onCurrentTabChanged)
        self.tabs.tabTransferred.connect(self.onTabTransferred)
        self.tabs.setWindowFactory(self.controller.createDetachedWindow)
        self.tabs.menuHook = self.controller.extendTabMenu
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([SIDEBAR_WIDTH, max(400, self.width() - SIDEBAR_WIDTH)])
        self.setCentralWidget(splitter)

        # Status bar (Composer: ct-status-bar)
        status_bar = self.statusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.setFixedHeight(theme.STATUS_BAR_HEIGHT)
        self.workspace_status = QLabel()
        # a long path must not set the minimum width of the window (the tool tip has the whole list)
        self.workspace_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_bar.addWidget(self.workspace_status, 1)
        self._updateWorkspaceStatus()
        self.applyRemoteLabels()

    def tabWindowLabel(self) -> str:
        """How this window is named in the tab menus."""
        return self.windowTitle()

    def updateTitle(self):
        """The title of the window follows its documents (see DetachedWindow)."""

    def documents(self) -> List[ChildWindow]:
        """The documents shown by this window."""
        return [widget for widget in self.tabs.widgets() if isinstance(widget, ChildWindow)]

    # -- documents ------------------------------------------------------------------
    def openFile(self, file_path: str):
        """Open a file of the side panel in this window."""
        self.controller.openDocument(file_path, host=self)

    def openRecentFile(self, file_path: str):
        """Open a recent file in this window (the file may be gone)."""
        self.controller.onOpenRecentFile(file_path, host=self)

    def onTabCloseRequested(self, index: int):
        self.controller.closeTab(self.tabs, index)

    def onCurrentTabChanged(self, index: int):
        self.updateTitle()
        self.controller.onTabsCurrentChanged(self)
        self.followCurrentDocument()

    def followCurrentDocument(self, only_new: bool = False):
        """
        Select the file of the document that is shown in the Workspace panel (the
        button "Select the open document in the list" of the panel turns it off).
        It leaves a search, a folder that is not shown and the Recent page alone.
        With ``only_new`` it does so only for a document or file it did not select yet,
        so that editing a document does not take the selection back from the user.
        """
        panel = self.sidebar.workspace_panel
        if not panel.follow_document or self.sidebar.pages.currentWidget() is not panel:
            return
        document = self.tabs.currentWidget()
        path = getattr(document, 'file_path', None) if isinstance(document, ChildWindow) else None
        if not path:
            return
        key = (id(document), str(path))
        if only_new and key == self._followed:
            return
        self._followed = key
        panel.revealFile(path, clear_search=False, allow_hidden=False)

    def onTabTransferred(self, widget: QWidget, source: QWidget):
        """A tab arrived from another window: merge the workspaces."""
        source_window = source.window()
        if isinstance(source_window, WorkbenchWindow) and source_window is not self:
            self.mergeWorkspace(source_window.workspace)
        self.updateTitle()

    # -- workspace ------------------------------------------------------------------
    def updateWorkspaceViews(self):
        """Refresh every view showing the workspace folders of this window."""
        self._updateWorkspaceStatus()
        self.sidebar.setWorkspaceFolders(self.workspace.folders())
        self.applyRemoteLabels()

    def applyRemoteLabels(self):
        """Name the roots of the Workspace panel that are copies of remote folders."""
        remote = getattr(self.controller, 'remote', None)
        if remote is not None:
            self.sidebar.setRemoteLabels(remote.labels())

    def onAddRemoteFolder(self):
        """Choose a folder of a remote machine (an EC2 instance of the SSH configuration) and add it."""
        self.controller.addRemoteFolder(self)

    def _updateWorkspaceStatus(self):
        """Status bar: the current workspace folder (where new files go) and the number of others."""
        folders = self.workspace.folders()
        text = f"Workspace: {self.workspace.currentFolder() or 'no folder'}"
        if len(folders) > 1:
            others = len(folders) - 1
            text += f"  (+{others} more folder{'s' if others > 1 else ''})"
        self.workspace_status.setText(text)
        self.workspace_status.setToolTip("Workspace folders:\n" + "\n".join(folders) if folders else "")

    def mergeWorkspace(self, other: workspaceFolders.Workspace):
        """Take the folders of the workspace of another window into this one."""
        added = self.workspace.merge(other.folders())
        if added:
            self.updateWorkspaceViews()
            self.statusBar().showMessage(f"Added {', '.join(added)} to the workspace", 5000)

    def revealInWorkspace(self, file_path) -> bool:
        """
        Show a file in the Workspace panel of this window: the panel is shown,
        the folders down to the file are expanded and the file is selected.

        Returns:
            True if the file was found in the workspace folders of this window.
        """
        self.sidebar.show()
        self.sidebar.showWorkspace()
        if self.sidebar.workspace_panel.revealFile(file_path):
            return True
        name = Path(str(file_path)).name
        if not Path(str(file_path)).is_file():
            message = f"{name} was not found"
        elif not self.workspace.isInsideWorkspace(file_path):
            message = f"{name} is not in a workspace folder of this window"
        else:
            message = f"{name} is not listed in the Workspace panel"
        self.statusBar().showMessage(message, 5000)
        return False

    def onOpenWorkspace(self):
        """Show the workspace browser in the side panel and rescan the workspace."""
        self.sidebar.show()
        self.sidebar.showWorkspace()
        self.sidebar.workspace_panel.on_rescan_clicked()
        self.sidebar.workspace_panel.search_box.setFocus()

    def onAddWorkspaceFolder(self):
        """Choose a folder and add it to the workspace (Composer "Add a Folder")."""
        start_directory = self.workspace.currentFolder() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self,
            "Add a Folder to the Workspace",
            start_directory,
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self.addWorkspaceFolder(folder)

    def addWorkspaceFolder(self, folder) -> bool:
        """
        Add a folder to the workspace and show it in the Workspace panel. A
        folder already in the workspace is refused; workspace folders inside
        the new folder are replaced by it.

        Returns:
            True if the folder was added.
        """
        status, related = self.workspace.addFolder(folder)
        if status == workspaceFolders.DUPLICATE:
            QMessageBox.information(self, "Add a Folder", f"{folder} is already in the workspace.")
            return False
        if status == workspaceFolders.NESTED:
            QMessageBox.information(self, "Add a Folder",
                                    f"{folder} is already in the workspace, inside {related[0]}.")
            return False
        self.updateWorkspaceViews()
        self.sidebar.show()
        self.sidebar.showWorkspace()
        self.sidebar.workspace_panel.showFolder(self.workspace.currentFolder())
        message = f"Added {self.workspace.currentFolder()} to the workspace"
        if related:
            message += f", in place of {', '.join(related)}"
        self.statusBar().showMessage(message, 5000)
        return True

    def onRemoveWorkspaceFolder(self, folder: str):
        """
        Remove a folder from the workspace (Composer "Remove from Workspace").
        The files are not touched; documents opened from the folder stay open.
        """
        folder = workspaceFolders.normalise(folder)
        open_documents = [document for document in self.documents()
                          if getattr(document, 'file_path', None)
                          and self.workspace.containingFolder(document.file_path) == folder]
        if open_documents:
            reply = QMessageBox.question(
                self,
                "Remove from Workspace",
                f"{len(open_documents)} open document(s) are in {folder}. Files outside the "
                "workspace cannot be saved.\n\nRemove the folder from the workspace anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self.workspace.removeFolder(folder):
            self.updateWorkspaceViews()
            self.statusBar().showMessage(f"Removed {folder} from the workspace", 5000)

    def onCurrentWorkspaceFolderChanged(self, folder: str):
        """The user works in another workspace folder: new files go there."""
        if self.workspace.setCurrentFolder(folder):
            self._updateWorkspaceStatus()


class DetachedWindow(WorkbenchWindow):
    """
    A window that tabs were torn off the main window into.

    It has a workspace side panel of its own, which starts as a copy of the one
    of the window the first tab came from. Tabs move back to the main window
    by dragging them onto its tab bar, from the tab menu or with the button in
    the corner; their workspace folders are then merged into the workspace of
    the main window. The window goes away when it has no tab left, and closing
    it closes its documents.
    """

    def __init__(self, controller: WorkbenchWindow, workspace: workspaceFolders.Workspace):
        super().__init__(workspace, controller)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowIcon(controller.windowIcon())
        self._closing = False
        self.buildWorkbench()
        self.tabs.windowFollowsLastTab = True
        self.tabs.emptied.connect(self._onEmptied)

        reattach = QToolButton(self.tabs)
        reattach.setIcon(theme.icon('compress', color=theme.TEXT_MUTED, active_color=theme.WHITE))
        reattach.setToolTip("Reattach all tabs to the main window")
        reattach.setAutoRaise(True)
        reattach.clicked.connect(self.reattachAll)
        self.tabs.setCornerWidget(reattach, Qt.Corner.TopRightCorner)

        # the same menus as the main window, working on the document of this window
        controller.buildMenuBar(self.menuBar(), self)
        self.updateTitle()

    def tabWindowLabel(self) -> str:
        return f"Window: {self._currentTitle() or 'Detached'}"

    def _currentTitle(self) -> str:
        index = self.tabs.currentIndex()
        return self.tabs.tabText(index).lstrip('*') if index >= 0 else ""

    def updateTitle(self):
        title = self._currentTitle()
        self.setWindowTitle(f"CWL editor — {title}" if title else "CWL editor")

    def reattachAll(self):
        """Move every tab back to the main window (this window goes away)."""
        main = self.controller
        for widget in self.tabs.widgets():
            moveTab(widget, main.tabs)
        main.raise_()
        main.activateWindow()

    def _onEmptied(self):
        # closing from within removeTab() would pull the window from under its callers
        QTimer.singleShot(0, self._closeIfEmpty)

    def _closeIfEmpty(self):
        if not self._closing and self.tabs.count() == 0:
            self.close()

    def closeEvent(self, event):
        """Closing the window closes its documents (each may veto it, e.g. for unsaved changes)."""
        if not self._closing:
            for document in self.documents():
                if not document.close():
                    event.ignore()
                    return
            # what else the window shows (a comparison) goes with it
            for widget in self.tabs.widgets():
                self.controller.discardTab(self.tabs, widget)
        self._closing = True
        self.controller.onDetachedWindowClosed(self)
        super().closeEvent(event)
