from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer, QSize, QRect
from PyQt6.QtWidgets import (
    QApplication, QInputDialog, QMenu, QMenuBar, QVBoxLayout, QHBoxLayout, QDialog,
    QFileDialog, QLabel, QPushButton, QWidget,QMessageBox,
    QToolButton, QFrame, QScrollArea, QSizePolicy
)
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QFont, QColor, QFontMetrics, QPixmap, QKeySequence, QGuiApplication
from pathlib import Path, PurePath
from CWLparser import Parser
import json
from ruamel.yaml import YAML
import builtins
import data
import logging
import sys
import os
import webbrowser
import tempfile
import markdown2
from TabInfoWindow import InfoWindow
from widgets.qtoogle import QToggle
from TabCodeEditor import CodeWindow
from TabToolEditor import ToolEditor
from TabSummary import WorkflowSummary
from CWLtoolFactory import CWLRunner
from widgets.qButtons import ErrorDialog, QIconButton
from typing import Union,List
from pathlib import Path, PosixPath
from TabWorkflowEditor import WorkflowEditor
from ChildWindow import ChildWindow
from DetachableTabs import DETACHABLE_PROPERTY, DetachableTabWidget, placeWindow
from WorkbenchWindow import DetachedWindow, WorkbenchWindow
import workspaceFolders
from logger import ErrorDialogHandler
from draft import DraftTool
import cwled
from platformdirs import user_config_path, user_log_path
import version
import itertools
import theme
import GraphItems
import DocumentDiff
from TabDiff import DiffView
from remoteFolders import RemoteFolders
from RemoteFolderDialog import RemoteFolderDialog
logger = logging.getLogger(__name__)


class CreationEntry(QFrame):
    """Clickable "create a new document" card of the start page (Composer: .creation-entry)."""

    def __init__(self, icon: QIcon, title: str, description: str, callback, parent=None):
        super().__init__(parent)
        self.setObjectName('creationEntry')
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._callback = callback
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(QSize(36, 36), self.devicePixelRatioF()))
        icon_label.setFixedSize(40, 40)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.addWidget(theme.styleTitle(QLabel(title)))
        description_label = QLabel(description)
        description_label.setProperty('muted', True)
        description_label.setWordWrap(True)
        text_layout.addWidget(description_label)
        layout.addLayout(text_layout, 1)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._callback()
        super().mouseReleaseEvent(event)

# class that defines the main window
class MainWindow(WorkbenchWindow):
    '''
    class for the main window
    It hosts all the tabs menus etc
    When a menu action is triggered it passes a message to the downstream applications.

    It also owns every document of the application, including the ones that
    were torn off its tabs into a ``DetachedWindow``, and the menus of all the
    windows, whose actions work on the document of the window they are used in.
    '''
    cwl_dict={}  # this is the cwl dictionary that we carry over in this window
    openWindowFromFile = pyqtSignal(str) # this signal will transfer the filename to open in a window
    def __init__(self , 
                 input_files:List[PosixPath|Path]=None,
                 export_image_file:str=None):
        super().__init__(workspaceFolders.PRIMARY)
        # load the configuration
        self.logger=logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        self.setupGlobalErrorDialogLogging()
        self.open_windows={}
        self.window_titles={}      # window_id -> entry of the Window menu
        self.active_window=None
        self.detached_windows=[]   # windows that tabs were torn off into
        self._last_host=None       # the window that was last active
        self._recent_menus=[]      # the Recent menu of every window
        self._window_menus=[]      # the Window menu of every window
        self._theme_menus=[]       # the View > Theme menu of every window
        self.remote=RemoteFolders(parent=self)   # folders of remote machines, copied here (see remoteFolders.py)
        self.remote.changed.connect(self.updateRemoteViews)
        self.remote.synced.connect(self.onRemoteSynced)
        self.remote.syncFailed.connect(self.onRemoteSyncFailed)
        self.remote.uploaded.connect(self.onRemoteUploaded)
        self.remote.uploadFailed.connect(self.onRemoteUploadFailed)
        theme.notifier.themeChanged.connect(self._refreshThemeMenus)
        GraphItems.LINK.changed.connect(lambda _enabled: self.refreshWindowMenus())
        self.logger.info(f"Setting up {self.__class__.__name__}")
        self.logger.info(f"Logging level set to {logging.getLevelName(self.logger.level)}")
        self.openWindowFromFile.connect( self.onCreateWindowFromFile )
        self.initUI()

        QTimer.singleShot(100, self._ensureWindowActive)

        self.restoreSession()
        
        if input_files:
            for idx,input_file in enumerate(input_files):
                # check if the file is an absolute path or not
                # if it is not, we make it one using the workspace directory as the baseline
                if Path( input_file ).is_absolute():
                    # check that the file is inside one of the workspace folders
                    if not workspaceFolders.isInsideWorkspace(input_file):
                        self.logger.error(f"Input file {input_file} is outside the workspace folders "
                                          f"{', '.join(workspaceFolders.folders())}. Cannot open.")
                        return
                    pass
                else:
                    # make it absolute based on the workspace directory
                    input_files[idx]=input_files[idx].resolve()
                # check that the file exists
                if not Path( input_files[idx] ).exists():
                    self.logger.error(f"Input file {input_files[idx]} does not exist. Cannot open.")
                    return
                # print(f"Opening input file {input_files[idx]} in a new window")
                # child_window_id=self.add_window_to_menu()
                # self.open_windows[child_window_id].menuOpenFile.emit(input_file)
                self.openWindowFromFile.emit( str(input_files[idx]) )
                input_files[idx]=None
            
    def _ensureWindowActive(self):
        """Ensure window is active and menu bar is visible."""
        self.raise_()
        self.activateWindow()
        
        if sys.platform == 'darwin':
            self._refreshMenuBar()
        self.logger.debug("Window activated and raised")

    def _refreshMenuBar(self):
        """Force refresh of menu bar (macOS fix)."""
        menu_bar = self.menuBar()
        if menu_bar:
            menu_bar.setVisible(False)
            menu_bar.setVisible(True)
            menu_bar.update()
            # menu_bar.update()
            # menu_bar.repaint()
            
            # # Ensure all menus are visible
            # for action in menu_bar.actions():
            #     menu = action.menu()
            #     if menu:
            #         menu.setVisible(True)
            #         menu.update()
            self.logger.debug("Menu bar refreshed")

    def initUI(self):
        self.setWindowTitle("CWL editor")
        
        # Set the window icon
        icon_path = data.configuration.get('icons').get('cwllogo') 
        self.logger.info(f"Loading CWL Logo from {icon_path}")
        app_icon = QIcon(icon_path)
        self.setWindowIcon(app_icon)
        
        if app_icon.isNull():
            self.logger.warning(f"Could not load icon from {icon_path}")
        else:
            self.logger.info("CWL Logo loaded successfully")
        
        # Create the main menu
        self.menu=self.menuBar()
        self.setMenu()
        QApplication.instance().focusChanged.connect(self.set_active_child_window)
        
        # Composer layout: side panel and document tabs above a status bar
        self._buildLayout()

    def _buildLayout(self):
        """
        Build the Rabix Composer style main window: a side panel with the
        workspace browser on the left, a tab bar with the open documents
        ("workbox") on the right and a status bar at the bottom.
        Documents open as tabs instead of separate windows; a tab can be
        dragged out to a window of its own (see DetachedWindow).
        """
        self.resize(self._initialSize())
        self.buildWorkbench()
        self.workbox = self.tabs

        new_tab_button = QToolButton(self.workbox)
        new_tab_button.setIcon(theme.icon('plus', color=theme.TEXT_MUTED, active_color=theme.WHITE))
        new_tab_button.setToolTip("New file")
        new_tab_button.setAutoRaise(True)
        new_tab_button.clicked.connect(self.showWelcomeTab)
        self.workbox.setCornerWidget(new_tab_button, Qt.Corner.TopRightCorner)

        # the start page belongs to the main window
        self.welcome = self._buildWelcomePage()
        self.welcome.setProperty(DETACHABLE_PROPERTY, False)
        self.showWelcomeTab()

        # themes, a click away (also in View > Theme)
        theme_button = QToolButton(self)
        theme_button.setObjectName('themeButton')
        theme_button.setIcon(theme.icon('paint-brush'))
        theme_button.setToolTip("Theme")
        theme_button.setAutoRaise(True)
        theme_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        theme_menu = QMenu("Theme", theme_button)
        self._theme_menus.append(theme_menu)
        self._fillThemeMenu(theme_menu)
        theme_button.setMenu(theme_menu)
        self.statusBar().addPermanentWidget(theme_button)

        version_status = QLabel(f"CWLed {version.__version__}")
        version_status.setProperty('muted', True)
        self.statusBar().addPermanentWidget(version_status)
        self.updateWorkspaceViews()
        self.updateRecentLists()

    def _initialSize(self) -> QSize:
        """Initial size from the configuration, clamped to the available screen."""
        main_window_cfg = data.configuration.get('main_window', {}) if data.configuration else {}
        try:
            width = int(main_window_cfg.get('initial_width', 1400))
            height = int(main_window_cfg.get('initial_height', 900))
        except (TypeError, ValueError):
            width, height = 1400, 900
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, int(available.width() * 0.95))
            height = min(height, int(available.height() * 0.95))
        return QSize(max(900, width), max(600, height))

    def _buildWelcomePage(self) -> QWidget:
        """
        Start page, modelled on Composer's "New File" tab: actions to create
        new documents next to the recently opened files, followed by the
        workspace settings and information about the application.
        """
        page = QWidget()
        page.setObjectName('welcome')
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        action_bar = QWidget(page)
        action_bar.setObjectName('actionBar')
        action_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        action_bar.setFixedHeight(theme.ACTION_BAR_HEIGHT)
        page_layout.addWidget(action_bar)

        content = QWidget(page)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(18)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        # Actions column
        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(theme.styleTitle(QLabel("Actions")))
        actions.addWidget(CreationEntry(
            theme.icon('workflow'), "New Workflow",
            "Workflows are chains of interconnected tools.", self.onMenuNewWorkflow))
        actions.addWidget(CreationEntry(
            theme.icon('tool'), "New Command Line Tool",
            "Tools are programs for processing data.", self.onMenuNewCommandTool))
        actions.addWidget(CreationEntry(
            theme.icon('expressiontool'), "New Expression Tool",
            "Expression tools transform data with JavaScript.", self.onMenuNewExpressionTool))
        actions.addWidget(CreationEntry(
            theme.icon('ai', color=theme.SKY), "Draft Command Line Tool",
            "Draft a tool from its documentation with an LLM.", self.onMenuNewDraftCommandTool))
        actions.addStretch(1)
        columns.addLayout(actions, 1)

        # Recently opened column
        recent = QVBoxLayout()
        recent.setSpacing(8)
        recent.addWidget(theme.styleTitle(QLabel("Recently Opened")))
        self.welcome_recent_list = self.sidebar.buildRecentList()
        recent.addWidget(self.welcome_recent_list, 1)
        columns.addLayout(recent, 1)
        content_layout.addLayout(columns, 1)

        # Workspace section: the workspace folders
        workspace_section = QVBoxLayout()
        workspace_section.setSpacing(8)
        workspace_section.addWidget(theme.styleTitle(QLabel("Workspace")))
        workspace_row = QHBoxLayout()
        # one row per folder; scrolls when there are many
        folders_widget = QWidget()
        self.welcome_workspace_folders = QVBoxLayout(folders_widget)
        self.welcome_workspace_folders.setContentsMargins(0, 0, 0, 0)
        self.welcome_workspace_folders.setSpacing(0)
        self.welcome_workspace_scroll = QScrollArea()
        self.welcome_workspace_scroll.setWidget(folders_widget)
        self.welcome_workspace_scroll.setWidgetResizable(True)
        self.welcome_workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.welcome_workspace_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.welcome_workspace_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        workspace_row.addWidget(self.welcome_workspace_scroll, 1)
        open_workspace_button = QPushButton("Open Workspace")
        open_workspace_button.clicked.connect(self.onOpenWorkspace)
        workspace_row.addWidget(open_workspace_button, 0, Qt.AlignmentFlag.AlignTop)
        add_folder_button = QPushButton("Add Folder...")
        add_folder_button.setToolTip("Add a folder to the workspace")
        add_folder_button.clicked.connect(self.onAddWorkspaceFolder)
        workspace_row.addWidget(add_folder_button, 0, Qt.AlignmentFlag.AlignTop)
        self.welcome_add_remote_button = QPushButton("Add Remote Folder...")
        self.welcome_add_remote_button.setToolTip("Add a folder of another machine (an EC2 instance of ~/.ssh/config) to the workspace")
        self.welcome_add_remote_button.clicked.connect(self.onAddRemoteFolder)
        workspace_row.addWidget(self.welcome_add_remote_button, 0, Qt.AlignmentFlag.AlignTop)
        workspace_section.addLayout(workspace_row)
        content_layout.addLayout(workspace_section)

        # About section (Composer: getting started)
        about_section = QVBoxLayout()
        about_section.setSpacing(8)
        about_section.addWidget(theme.styleTitle(QLabel("About")))
        about = QFrame()
        about.setObjectName('formSection')
        about_layout = QHBoxLayout(about)
        about_layout.setContentsMargins(13, 11, 13, 11)
        about_layout.setSpacing(16)
        logo_label = QLabel()
        pixmap = QPixmap(data.configuration.get('icons').get('cwllogo'))
        if not pixmap.isNull():
            logo_label.setPixmap(pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        about_layout.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignTop)
        about_text = QLabel(
            f"<b>CWL Editor</b> &nbsp;version {version.__version__}<br>"
            "Copyright (C) 2026 K.Mavrommatis. This program comes with ABSOLUTELY NO WARRANTY; "
            "for details check the `COPYING` file. This is free software, and you are welcome "
            "to redistribute it under certain conditions.<br><br>"
            f"Configuration directory: {user_config_path(appname='cwled')}<br>"
            f"Log directory: {user_log_path(appname='cwled')}"
        )
        about_text.setWordWrap(True)
        about_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        about_layout.addWidget(about_text, 1)
        user_guide_button = QPushButton("User Guide")
        theme.setButtonRole(user_guide_button, 'link')
        user_guide_button.setIcon(theme.icon('book', color=theme.SKY))
        user_guide_button.clicked.connect(self.onMenuHelp)
        about_layout.addWidget(user_guide_button, 0, Qt.AlignmentFlag.AlignTop)
        about_section.addWidget(about)
        content_layout.addLayout(about_section)

        page_layout.addWidget(content, 1)
        return page

    def showWelcomeTab(self):
        """Show the start page, re-opening its tab if it was closed."""
        index = self.workbox.indexOf(self.welcome)
        if index < 0:
            index = self.workbox.insertTab(0, self.welcome, theme.icon('file-o', color=theme.SMOKE), "Welcome")
        self.workbox.setCurrentIndex(index)

    def updateWorkspaceViews(self):
        """Refresh every view showing the workspace folders of the main window."""
        super().updateWorkspaceViews()
        if hasattr(self, 'welcome_workspace_folders'):
            self._refreshWelcomeWorkspace()

    def _refreshWelcomeWorkspace(self):
        """Start page: one row per workspace folder."""
        layout = self.welcome_workspace_folders
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        folders = self.workspace.folders()
        if not folders:
            empty_label = QLabel("No folders in the workspace.")
            empty_label.setProperty('muted', True)
            layout.addWidget(empty_label)
        for folder in folders:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            icon_label = QLabel()
            theme.setLabelIcon(icon_label, theme.icon('folder'), 14)
            row_layout.addWidget(icon_label)
            folder_label = QLabel(folder)
            folder_label.setProperty('muted', True)
            folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(folder_label)
            remove_button = QIconButton('times', "Remove from Workspace")
            remove_button.setFixedSize(QSize(22, 22))
            remove_button.setIconSize(QSize(12, 12))
            remove_button.clicked.connect(lambda _checked=False, f=folder: self.onRemoveWorkspaceFolder(f))
            row_layout.addWidget(remove_button)
            row_layout.addStretch(1)
            layout.addWidget(row)
        layout.addStretch(1)
        # show up to four folders, scroll for more
        row_height = max(22, QFontMetrics(self.font()).height() + 4)
        self.welcome_workspace_scroll.setMinimumHeight(row_height)
        self.welcome_workspace_scroll.setMaximumHeight(row_height * min(4, max(1, len(folders))))

    def updateRecentLists(self):
        """Refresh the 'Recent' side panel of every window and the start page list."""
        recent_files = [f for f in reversed(data.configuration.get('recents', []) or [])
                        if self._fileExists(f)]
        if hasattr(self, 'welcome_recent_list'):
            self.welcome_recent_list.setFiles(recent_files)
        for window in self.workbenchWindows():
            if hasattr(window, 'sidebar'):
                window.sidebar.setRecentFiles(recent_files)

    @staticmethod
    def _fileExists(file_path) -> bool:
        try:
            return Path(file_path).exists()
        except (OSError, ValueError):
            return False

    def _documentTitle(self, window: ChildWindow) -> str:
        """Short tab title for a document: its file name, label or id."""
        display_path = window.getDisplayFilePath()
        if display_path and display_path != "<unsaved>":
            title = Path(display_path).name
        else:
            cwl_tool = getattr(window, 'cwl_tool', None)
            title = getattr(cwl_tool, 'label', None) or str(getattr(cwl_tool, 'id', '') or '')
            title = title.rstrip('/').split('/')[-1].split('#')[-1] or f"Untitled {window.cwl_type}"
        return f"*{title}" if window.hasChanged else title

    def _documentIcon(self, window: ChildWindow) -> QIcon:
        icon_key = {'Workflow': 'workflow', 'ExpressionTool': 'expressiontool'}.get(window.cwl_type, 'tool')
        return theme.icon(icon_key)

    def _refreshDocumentTab(self, window: ChildWindow):
        """Update the title, icon and tool tip of the tab of a document, in whichever window it is."""
        tabs = DetachableTabWidget.tabsOf(window)
        index = tabs.indexOf(window) if tabs is not None else -1
        if index < 0:
            return
        tabs.setTabText(index, self._documentTitle(window))
        tabs.setTabIcon(index, self._documentIcon(window))
        tabs.setTabToolTip(index, window.windowTitle())
        host = tabs.window()
        if isinstance(host, WorkbenchWindow):
            host.updateTitle()
            if tabs.currentWidget() is window:
                host.followCurrentDocument(only_new=True)

    def _showDocument(self, window: ChildWindow):
        """Bring a document tab to the front, in whichever window it is."""
        tabs = DetachableTabWidget.tabsOf(window)
        if tabs is not None and tabs.indexOf(window) >= 0:
            tabs.setCurrentWidget(window)
            host = tabs.window()
            host.raise_()
            host.activateWindow()
            self.active_window = window
            window.setFocus()
        else:
            window.raise_()
            window.activateWindow()

    def tabWindowLabel(self) -> str:
        return "Main Window"

    def workbenchWindows(self) -> List[WorkbenchWindow]:
        """The main window and the windows that tabs were torn off into."""
        return [self] + [window for window in self.detached_windows if not sip.isdeleted(window)]

    def activeHost(self) -> WorkbenchWindow:
        """The window the user works in: where new documents and the menu actions go."""
        window = QApplication.activeWindow()
        while window is not None:
            if isinstance(window, WorkbenchWindow):
                self._last_host = window
                return window
            window = window.parentWidget()
        host = self._last_host
        if host is not None and not sip.isdeleted(host) and host.isVisible():
            return host
        return self

    def _dialogParent(self) -> QWidget:
        """The parent of the dialogs of the menu actions: the window they were used in."""
        return self.activeHost()

    def _warnNoDocument(self):
        QMessageBox.warning(self._dialogParent(), "No Document", "Please select a document first.")

    def closeTab(self, tabs: DetachableTabWidget, index: int):
        """Close a document tab; the document may veto it (unsaved changes)."""
        widget = tabs.widget(index)
        if widget is None:
            return
        if widget is self.welcome:
            tabs.removeTab(index)
            return
        if not isinstance(widget, ChildWindow):
            self.discardTab(tabs, widget)       # a comparison
            return
        # ChildWindow.closeEvent prompts for unsaved changes and emits
        # windowClosed, which removes the tab (remove_window_from_menu).
        widget.close()

    def discardTab(self, tabs: DetachableTabWidget, widget: QWidget):
        """Remove a tab that is not a document (a comparison) and delete its page."""
        if isinstance(widget, ChildWindow) or widget is self.welcome:
            return
        index = tabs.indexOf(widget)
        if index >= 0:
            tabs.removeTab(index)
        cleanup = getattr(widget, 'cleanup', None)
        if cleanup is not None:
            cleanup()
        widget.deleteLater()

    # -- comparing documents ------------------------------------------------------------------------------------
    def extendTabMenu(self, widget: QWidget, menu: QMenu):
        """The menu of a tab: documents can be compared with another document, file or revision."""
        if isinstance(widget, ChildWindow):
            menu.addAction("Compare with\u2026", lambda: self.compareDocument(widget))

    def onMenuCompare(self):
        if not self.active_window:
            self._warnNoDocument()
            return
        self.compareDocument(self.active_window)

    def compareDocument(self, window: ChildWindow):
        """
        Ask what to compare a document with (another open document, its saved version, a
        revision in git or a file) and show the differences in a tab next to the document.
        The other one is on the left, the document on the right.
        """
        host = DetachableTabWidget.tabsOf(window)
        host = host.window() if host is not None else self
        title = self._documentTitle(window).lstrip('*')
        options = {}
        for other in self.open_windows.values():
            if other is not window and isinstance(other, ChildWindow):
                options[f"Open document: {self._documentTitle(other).lstrip('*')}"] = \
                    (lambda other=other: DocumentDiff.sourceFromWindow(other))
        file_path = getattr(window, 'file_path', None)
        if file_path:
            options["The saved version of this document"] = \
                (lambda: DocumentDiff.sourceFromFile(file_path, f"{Path(str(file_path)).name} (saved)"))
            for revision, description in DocumentDiff.gitRevisions(file_path):
                options[f"Git: {description}"] = \
                    (lambda revision=revision, description=description:
                     DocumentDiff.sourceFromGit(file_path, revision, description.split(' ', 1)[0]))
        options["A file\u2026"] = None
        choice, accepted = QInputDialog.getItem(host, "Compare", f"Compare {title} with:", list(options), 0, False)
        if not accepted:
            return
        left = options[choice]
        if left is None:
            start = str(Path(str(file_path)).parent) if file_path else (host.workspace.currentFolder() or str(Path.home()))
            chosen, _filter = QFileDialog.getOpenFileName(host, "Compare with", start, "CWL documents (*.cwl *.yaml *.json)")
            if not chosen:
                return
            left = (lambda: DocumentDiff.sourceFromFile(chosen))
        self.showComparison(host, left, (lambda: DocumentDiff.sourceFromWindow(window)))

    def showComparison(self, host: WorkbenchWindow, left, right):
        """Show the comparison of two documents as a tab of ``host``; ``left`` and ``right`` make the two sources."""
        view = DiffView(left, right)
        if view.left is None:
            view.deleteLater()      # the sources could not be read: the view told why
            QMessageBox.warning(host, "Compare", view.summary.text())
            return view
        index = host.tabs.addTab(view, theme.icon('exchange'), view.title())
        host.tabs.setTabToolTip(index, view.title())
        host.tabs.setCurrentWidget(view)
        return view

    def onMenuCloseTab(self):
        host = self.activeHost()
        self.closeTab(host.tabs, host.tabs.currentIndex())

    def onTabsCurrentChanged(self, host: WorkbenchWindow):
        """The selected tab of a window changed."""
        if host is not self.activeHost():
            return
        widget = host.tabs.currentWidget()
        self.active_window = widget if isinstance(widget, ChildWindow) else None

    def createDetachedWindow(self, source_tabs: DetachableTabWidget, widget: QWidget):
        """
        The window for a tab that is torn off ``source_tabs``. Its workspace
        starts as a copy of the one of the window the tab comes from (with the
        folder of the document as the current one). Returns its tab widget.
        """
        source = source_tabs.window()
        source_workspace = source.workspace if isinstance(source, WorkbenchWindow) else self.workspace
        workspace = source_workspace.copy()
        file_path = getattr(widget, 'file_path', None)
        folder = workspace.containingFolder(file_path) if file_path else None
        if folder:
            workspace.setCurrentFolder(folder)
        size = source.size()
        screen = source.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            size = QSize(min(size.width(), int(available.width() * 0.9)),
                         min(size.height(), int(available.height() * 0.9)))
        window = self._newDetachedWindow(workspace)
        window.resize(size)
        window.move(source.x() + 40, source.y() + 40)
        self.logger.info(f"Tab {widget.windowTitle()!r} detached to a new window "
                         f"(workspace: {', '.join(workspace.folders())})")
        return window.tabs

    def _newDetachedWindow(self, workspace) -> DetachedWindow:
        """An empty window for tabs, with the given workspace; the caller sizes and shows it."""
        window = DetachedWindow(self, workspace)
        self.detached_windows.append(window)
        self.updateRecentLists()
        self.refreshWindowMenus()
        return window

    def tileWindows(self):
        """Arrange the windows side by side, as wide as the screen allows: the main window on the left."""
        windows = [window for window in self.workbenchWindows()
                   if window.isVisible() and not window.isMinimized()]
        if len(windows) < 2:
            return
        active = self.activeHost()
        screen = active.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        width = available.width() // len(windows)
        for number, window in enumerate(windows):
            last = number == len(windows) - 1
            frame = QRect(available.left() + number * width, available.top(),
                          available.width() - number * width if last else width, available.height())
            placeWindow(window, frame, within=available)
        widest = max(window.frameGeometry().width() for window in windows)
        if widest > width + 2:
            # the windows cannot be that narrow: spread them over the screen, overlapping like a staircase
            last_x = available.right() + 1 - windows[-1].frameGeometry().width()
            for number, window in enumerate(windows):
                window.move(available.left() + round(number * (last_x - available.left()) / (len(windows) - 1)), window.y())
        active.raise_()
        active.activateWindow()

    def onDetachedWindowClosed(self, window: DetachedWindow):
        """A window that tabs were torn off into is gone."""
        if window in self.detached_windows:
            self.detached_windows.remove(window)
        if self._last_host is window:
            self._last_host = None
        QTimer.singleShot(0, self.refreshWindowMenus)

    def reattachAllWindows(self):
        """Move the tabs of every detached window back to the main window."""
        for window in list(self.detached_windows):
            if not sip.isdeleted(window):
                window.reattachAll()

    # -- session ---------------------------------------------------------------------------------------------
    def sessionData(self) -> dict:
        """
        The documents that are open, by window, to open them again at the next start:
        the files of the main window and, for every window that tabs were torn off
        into, its files, position and size and workspace. Documents that were never
        saved are not part of it.
        """
        def describe(window):
            files, current = [], None
            for index in range(window.tabs.count()):
                document = window.tabs.widget(index)
                path = getattr(document, 'file_path', None) if isinstance(document, ChildWindow) else None
                if path and Path(path).is_file():
                    files.append(str(path))
                    if index == window.tabs.currentIndex():
                        current = str(path)
            return {'files': files, 'current': current}

        windows = []
        for window in self.detached_windows:
            if sip.isdeleted(window):
                continue
            entry = describe(window)
            if not entry['files']:
                continue
            geometry = window.geometry()
            entry['geometry'] = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
            entry['workspace'] = window.workspace.folders()
            entry['current_folder'] = window.workspace.currentFolder()
            windows.append(entry)
        return {'main': describe(self), 'windows': windows}

    def saveSession(self, session: dict):
        """Keep the session in the configuration (an empty one when the setting is off)."""
        configuration = data.configuration
        if configuration is None:
            return
        enabled = configuration.get('restore_session', True)
        configuration['session'] = session if enabled else {}
        if data.configuration_manager:
            try:
                data.configuration_manager.saveConfiguration()
            except Exception as e:
                self.logger.error(f"Cannot save the session: {e}")

    def restoreSession(self):
        """
        Open the documents of the last session again: in the main window, and in
        windows of their own, at their old place, for the ones that were torn off.
        Files that are gone are skipped. The setting ``restore_session`` turns it off.
        """
        configuration = data.configuration or {}
        session = configuration.get('session') or {}
        if not configuration.get('restore_session', True) or not session:
            return
        main = session.get('main') or {}
        self._restoreDocuments(self, main.get('files'), main.get('current'))
        for entry in session.get('windows') or []:
            files = [f for f in (entry.get('files') or []) if self._fileExists(f)]
            if not files:
                continue
            folders = [f for f in (entry.get('workspace') or []) if Path(f).is_dir()]
            workspace = workspaceFolders.Workspace(folders or self.workspace.folders(), entry.get('current_folder'))
            window = self._newDetachedWindow(workspace)
            window.resize(self.size())
            window.move(self.x() + 40, self.y() + 40)
            if not self._applyGeometry(window, entry.get('geometry')):
                self.logger.debug("The saved position of a window is on no screen; it is placed next to the main window")
            window.show()
            self._restoreDocuments(window, files, entry.get('current'))

    def _restoreDocuments(self, host: WorkbenchWindow, files, current):
        for file_path in files or []:
            if not self._fileExists(file_path):
                self.logger.info(f"Not reopening {file_path}: it is gone")
                continue
            try:
                self.openDocument(str(file_path), host=host, recent=False)
            except Exception as e:
                self.logger.error(f"Cannot reopen {file_path}: {e}")
        if current:
            for window in self.open_windows.values():
                if getattr(window, 'file_path', None) and str(window.file_path) == str(current) \
                        and DetachableTabWidget.tabsOf(window) is host.tabs:
                    host.tabs.setCurrentWidget(window)

    @staticmethod
    def _applyGeometry(window: QWidget, geometry) -> bool:
        """Put a window at a saved [x, y, width, height] if that is on a screen that exists."""
        try:
            rect = QRect(*(int(value) for value in geometry))
        except (TypeError, ValueError):
            return False
        for screen in QGuiApplication.screens():
            available = screen.availableGeometry()
            if available.intersects(rect):
                rect.setWidth(min(rect.width(), available.width()))
                rect.setHeight(min(rect.height(), available.height()))
                window.setGeometry(rect)
                return True
        return False

    def closeEvent(self, event):
        """Closing the main window closes every document (each may veto it)."""
        session = self.sessionData()
        for window in list(self.open_windows.values()):
            if isinstance(window, ChildWindow) and not window.close():
                event.ignore()
                return
        for window in list(self.detached_windows):
            if not sip.isdeleted(window):
                window.close()
        self.saveSession(session)
        super().closeEvent(event)

    def setupGlobalErrorDialogLogging(self):
        """Set up global error dialog logging for the entire application."""
        error_handler = ErrorDialogHandler(parent_window=self)
        error_handler.setLevel(logging.ERROR)
        
        # Add to root logger to catch all errors
        root_logger = logging.getLogger()
        root_logger.addHandler(error_handler)
        
        # Also ensure stderr output
        if not any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers):
            stderr_handler = logging.StreamHandler()
            stderr_handler.setLevel(logging.ERROR)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            stderr_handler.setFormatter(formatter)
            root_logger.addHandler(stderr_handler)


    
    @pyqtSlot(str)
    def onCreateWindowFromFile( self, input_file:str):
        '''
        Respond to a message to create new window from a file.
        If the file is already open in an existing window, bring that window forward.
        '''
        self.openDocument(input_file)

    def openDocument(self, input_file:str, host:WorkbenchWindow=None, recent:bool=True):
        '''
        Open a file as a tab of ``host`` (by default the window the user works in).
        If the file is already open, in whichever window, that tab is brought forward.
        With ``recent`` False the file is not added to the recent files.
        '''
        # Check if the file is already open in an existing window
        resolved_path = str(Path(input_file).resolve())
        for window in self.open_windows.values():
            if hasattr(window, 'file_path') and window.file_path:
                if str(Path(window.file_path).resolve()) == resolved_path:
                    self._showDocument(window)
                    return

        child_window_id=self.add_window_to_menu(host=host)
        # self.active_window.file_path=input_file
        self.open_windows[child_window_id].menuOpenFile.emit(input_file)
        
        # Add file to recent files and update the menu
        if recent and data.configuration_manager:
            data.configuration_manager.addRecentFile(input_file)
            self.updateRecentMenu()

    def setMenu(self):
        '''
        set the menu in the main application
        '''
        self.buildMenuBar(self.menu, self)

    def buildMenuBar(self, menu_bar:QMenuBar, owner:QWidget):
        '''
        Fill a menu bar with the menus of the application.

        The main window and every window that tabs were torn off into has a
        menu bar of its own (on macOS a window without one shows no menus), with
        its own actions so that the shortcuts work in each of them. All of them
        work on the document of the window they are used in (see activeHost).

        Args:
            menu_bar: the menu bar to fill.
            owner: the window of the menu bar, which owns the actions.
        '''
        file_open=QAction(  "&Open file ...",owner)
        file_open.setShortcut(QKeySequence.StandardKey.Open)
        file_open.triggered.connect(self.onMenuOpenFile)
        file_save=QAction(  "&Save",owner)
        file_save.setShortcut(QKeySequence.StandardKey.Save)
        file_save.triggered.connect(self.onMenuSaveFile)
        file_saveas=QAction(  "Save as ...",owner)
        file_saveas.setShortcut(QKeySequence.StandardKey.SaveAs)
        file_saveas.triggered.connect(self.onMenuSaveAsFile)
        file_reload=QAction(  "Reload file",owner)
        file_reload.setShortcut(QKeySequence.StandardKey.Refresh)
        file_reload.triggered.connect(self.onMenuReloadFile)
        file_add_folder=QAction(  "Add Folder to Workspace...",owner)
        file_add_folder.setToolTip("Add a folder to the workspace")
        file_add_folder.triggered.connect(owner.onAddWorkspaceFolder)
        file_sync_remote=QAction(  "Sync Remote Folders",owner)
        file_sync_remote.setToolTip("Copy the remote folders of the workspace again")
        file_sync_remote.triggered.connect(self.syncRemoteFolders)
        file_close=QAction(  "Close tab",owner)
        file_close.setShortcut(QKeySequence.StandardKey.Close)
        file_close.triggered.connect(self.onMenuCloseTab)
        file_exit=QAction(  "E&xit",owner)
        file_exit.setShortcut(QKeySequence.StandardKey.Quit)
        file_exit.setMenuRole(QAction.MenuRole.QuitRole)
        file_exit.triggered.connect(self.close)
        # create a submenu for New
        

        tools_validate=QAction(  "Validate tool",owner)
        tools_validate.triggered.connect(self.onMenuValidate)
        tools_maketemplate=QAction(  "Generate template",owner)
        tools_maketemplate.triggered.connect(self.onMenuMakeTemplate)
        
        tools_upgrade=QAction(  "Upgrade CWL version",owner)
        tools_upgrade.triggered.connect(self.onMenuUpgradeVersion)
        tools_pack_workflow=QAction(  "Pack workflow to single file",owner)
        tools_pack_workflow.triggered.connect(self.onMenuPackWorkflow)
        tools_restructure_workflow=QAction(  "Repackage workflow with all tools",owner)
        tools_restructure_workflow.triggered.connect(self.onMenuRestructureWorkflow)
        tools_save_documentation=QAction(  "Save workflow documentation",owner)
        tools_save_documentation.triggered.connect(self.onMenuSaveDocumentation)
        tools_configuration=QAction( "Configuration",owner)
        tools_configuration.setShortcut(QKeySequence.StandardKey.Preferences)
        tools_configuration.triggered.connect(self.onMenuConfiguration)
        tools_reset_configuration=QAction( "Reset configuration to default",owner)
        tools_reset_configuration.triggered.connect(self.onMenuResetConfiguration)
        tools_draft_commandtool=QAction("Draft CommandLineTool from documentation", owner)
        tools_draft_commandtool.triggered.connect(self.onMenuNewDraftCommandTool)

        tools_troubleshoot=QAction(  "Troubleshoot tool/workflow",owner)
        tools_troubleshoot.triggered.connect(self.onMenuTroubleshooting)
        tools_compare=QAction(  "Compare with...",owner)
        tools_compare.triggered.connect(self.onMenuCompare)

        new_commandtool=QAction( "Command line tool", owner)
        new_commandtool.triggered.connect(self.onMenuNewCommandTool)
        new_expressiontool=QAction("Expression tool", owner)
        new_expressiontool.triggered.connect(self.onMenuNewExpressionTool)
        new_workflow=QAction("Workflow", owner)
        new_workflow.triggered.connect(self.onMenuNewWorkflow)
        # Draft CommandLineTool placeholder action
        

        file_menu=menu_bar.addMenu( "&File")
        file_menu.addAction( file_open )
        file_menu.addAction( file_save)
        file_menu.addAction( file_saveas )
        file_menu.addAction( file_reload )

        new_menu = QMenu("New", owner)
        file_menu.addMenu(new_menu)
        new_menu.addAction( new_commandtool)
        new_menu.addAction( new_expressiontool)
        new_menu.addAction( new_workflow)
        new_menu.addSeparator()
        
        # Add Recent submenu
        recent_menu = QMenu("Recent", owner)
        file_menu.addMenu(recent_menu)
        self._recent_menus.append(recent_menu)
        self.updateRecentMenu()
        file_menu.addSeparator()
        file_menu.addAction( file_add_folder )
        file_menu.addAction( file_sync_remote )
        file_menu.addSeparator()
        file_menu.addAction( file_close )
        file_menu.addAction( file_exit )
        

        tools_menu=menu_bar.addMenu( "&Tools")
        tools_menu.addAction( tools_validate)
        tools_menu.addAction( tools_compare)
        tools_menu.addAction( tools_maketemplate)
        tools_menu.addAction( tools_pack_workflow)
        tools_menu.addAction( tools_restructure_workflow)
        tools_menu.addAction( tools_save_documentation)
        tools_menu.addAction( tools_upgrade)
        tools_menu.addSeparator()
        tools_menu.addAction( tools_configuration)
        tools_menu.addAction( tools_reset_configuration)
        tools_menu.addSeparator()
        tools_menu.addAction( tools_draft_commandtool)
        tools_menu.addSeparator()
        tools_menu.addAction( tools_troubleshoot)
        
        view_menu=menu_bar.addMenu("&View")
        theme_menu = QMenu("Theme", owner)
        view_menu.addMenu(theme_menu)
        self._theme_menus.append(theme_menu)
        self._fillThemeMenu(theme_menu)

        window_menu=menu_bar.addMenu("&Window")
        self._window_menus.append(window_menu)
        self.refreshWindowMenus()
        
        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        help_user_guide = QAction("User Guide", owner)
        help_user_guide.triggered.connect(self.onMenuHelp)
        help_menu.addAction(help_user_guide)

        if owner is self:
            self.file_menu, self.tools_menu, self.new_menu = file_menu, tools_menu, new_menu
            self.recent_menu, self.window_menu, self.help_menu = recent_menu, window_menu, help_menu

    def _fillThemeMenu(self, menu:QMenu):
        """One checkable entry per theme; the current one is checked."""
        group = QActionGroup(menu)
        group.setExclusive(True)
        for name in theme.themeNames():
            action = QAction(name, menu)
            action.setCheckable(True)
            action.setChecked(name == theme.currentTheme())
            action.setToolTip(theme.THEMES[name]['description'])
            action.setStatusTip(theme.THEMES[name]['description'])
            action.setData(name)
            action.triggered.connect(lambda _checked=False, name=name: self.onMenuTheme(name))
            group.addAction(action)
            menu.addAction(action)
        menu.setToolTipsVisible(True)

    def _refreshThemeMenus(self, current:str):
        self._theme_menus = [menu for menu in self._theme_menus if not sip.isdeleted(menu)]
        for menu in self._theme_menus:
            for action in menu.actions():
                action.setChecked(action.data() == current)

    def onMenuTheme(self, name:str):
        """Switch to another theme (View > Theme or the status bar brush)."""
        applied = theme.setTheme(name)
        self.statusBar().showMessage(f"Theme: {applied}", 3000)

    def refreshWindowMenus(self):
        """Rebuild the Window menu of every window: the main window and the open documents."""
        self._window_menus = [menu for menu in self._window_menus if not sip.isdeleted(menu)]
        for menu in self._window_menus:
            self._clearMenu(menu)
            menu.addAction("Main Window", self._ensureWindowActive)
            if self.detached_windows:
                menu.addAction("Reattach All Tabs to the Main Window", self.reattachAllWindows)
                menu.addAction("Tile Windows Side by Side", self.tileWindows)
            link = menu.addAction("Link Workflow Views")
            link.setCheckable(True)
            link.setChecked(GraphItems.LINK.enabled())
            link.setToolTip("Panning or zooming a workflow does the same in the workflows of the other windows")
            link.toggled.connect(GraphItems.LINK.setEnabled)
            menu.addSeparator()
            for window_id, title in self.window_titles.items():
                menu.addAction(title, lambda _checked=False, window_id=window_id: self.onMenuFocus(window_id))

    @staticmethod
    def _clearMenu(menu:QMenu):
        for action in menu.actions():
            menu.removeAction(action)
            action.deleteLater()

    def updateRecentMenu(self):
        """
        Update the Recent menu of every window with the list of recently opened files.
        Shows up to 10 most recently opened files.
        Shows basename only if unique, or basename with parent directory if duplicates exist.
        """
        # Get recent files from configuration
        recent_files = data.configuration.get('recents', [])

        # Track files that need to be removed due to errors
        files_to_remove = []
        valid_files = []
        for file_path in reversed(recent_files):
            try:
                if Path(file_path).exists():
                    valid_files.append(file_path)
                else:
                    files_to_remove.append(file_path)
            except (OSError, ValueError) as e:
                self.logger.warning(f"Error accessing recent file {file_path}: {e}. Removing from recent files list.")
                files_to_remove.append(file_path)

        # Count how many times each basename appears to detect duplicates
        from collections import Counter
        basename_counts = Counter(Path(f).name for f in valid_files)

        self._recent_menus = [menu for menu in self._recent_menus if not sip.isdeleted(menu)]
        for menu in self._recent_menus:
            self._clearMenu(menu)
            if not valid_files:
                # Show "No recent files" if the list is empty
                no_recent_action = menu.addAction("No recent files")
                no_recent_action.setEnabled(False)
                continue
            # Add recent files (already in most-recent-first order)
            for file_path in valid_files:
                file_name = Path(file_path).name
                if basename_counts[file_name] > 1:
                    display_name = f"{file_name}  —  {Path(file_path).parent.name}"
                else:
                    display_name = file_name
                action = menu.addAction(display_name,
                                        lambda _checked=False, f=file_path: self.onOpenRecentFile(f, host=self.activeHost()))
                action.setToolTip(file_path)  # Show full path as tooltip

        # Remove inaccessible files from the recent files list
        if files_to_remove:
            for file_path in files_to_remove:
                if file_path in data.configuration['recents']:
                    data.configuration['recents'].remove(file_path)
            data.configuration_manager.saveConfiguration()

        self.updateRecentLists()
    
    def onOpenRecentFile(self, file_path:str, host:WorkbenchWindow=None):
        """
        Open a file from the recent files list.
        
        Args:
            file_path (str): Full path to the file to open.
            host: the window to open it in (by default the one the user works in).
        """
        dialog_parent = host if host is not None else self._dialogParent()
        try:
            if Path(file_path).exists():
                self.logger.info(f"Opening recent file {file_path}")
                self.openDocument(file_path, host=host)
            else:
                self.logger.error(f"Recent file {file_path} no longer exists")
                QMessageBox.warning(dialog_parent, "File Not Found", 
                                  f"The file {file_path} no longer exists.")
                # Remove the file from recent files list
                if file_path in data.configuration['recents']:
                    data.configuration['recents'].remove(file_path)
                    data.configuration_manager.saveConfiguration()
                    self.updateRecentMenu()  # Refresh the menu
        except (OSError, ValueError) as e:
            self.logger.error(f"Error accessing recent file {file_path}: {e}")
            QMessageBox.warning(dialog_parent, "Error Opening File", 
                              f"Cannot access the file {file_path}:\n{str(e)}")
            # Remove the file from recent files list
            if file_path in data.configuration['recents']:
                data.configuration['recents'].remove(file_path)
                data.configuration_manager.saveConfiguration()
                self.updateRecentMenu()  # Refresh the menu
    
    def set_active_child_window(self, old, new):
        """The focus moved to the widget ``new``: its document becomes the active one."""
        document = None
        host = None
        widget = new
        while widget is not None:
            if document is None and isinstance(widget, ChildWindow):
                document = widget
            if isinstance(widget, WorkbenchWindow):
                host = widget
                break
            widget = widget.parentWidget()
        if document is not None and document.window_id in self.open_windows:
            self.active_window = document
        elif host is not None:
            # Focus is outside the documents (side panel, menus...): the
            # document shown by the window stays the active one.
            current = host.tabs.currentWidget()
            self.active_window = current if isinstance(current, ChildWindow) else None
        elif self.active_window is not None and self.active_window.window_id not in self.open_windows:
            self.active_window = None

        # Only log the window_id if we have an active window
        if self.active_window:
            self.logger.debug(f"Set the active window to {self.active_window.window_id}")
        else:
            self.logger.debug("No active window set")
    
    # -- remote folders ------------------------------------------------------------------------------------------
    def addRemoteFolder(self, host: WorkbenchWindow = None):
        """Ask for a folder of a remote machine, copy it and add the copy to the workspace of ``host``."""
        host = host if host is not None else self.activeHost()
        dialog = RemoteFolderDialog(self.remote, host)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.folder is not None:
            if host.addWorkspaceFolder(dialog.folder.mirror):
                host.statusBar().showMessage(f"Added {dialog.folder.label} to the workspace", 8000)

    def syncRemoteFolder(self, mirror: str):
        """Copy a remote folder again (the result is shown in the status bar)."""
        folder = self.remote.folderFor(mirror)
        if folder is not None:
            self.activeHost().statusBar().showMessage(f"Syncing {folder.label} ...", 0)
            self.remote.sync(folder.mirror)

    def syncRemoteFolders(self):
        if not self.remote.folders():
            QMessageBox.information(self._dialogParent(), "Sync Remote Folders",
                                    "The workspace has no remote folder. Add one with \"Add a Remote Folder (SSH)\" in the side panel.")
            return
        for folder in self.remote.folders():
            self.syncRemoteFolder(folder.mirror)

    def updateRemoteViews(self):
        """The list of remote folders changed: the roots of every Workspace panel are named again."""
        for window in self.workbenchWindows():
            window.applyRemoteLabels()

    def onRemoteSynced(self, mirror: str, result):
        folder = self.remote.folderFor(mirror)
        self.activeHost().statusBar().showMessage(f"{folder.label if folder else mirror}: {result.summary()}", 8000)
        for window in self.workbenchWindows():
            window.sidebar.workspace_panel.refresh()

    def onRemoteSyncFailed(self, mirror: str, why: str):
        folder = self.remote.folderFor(mirror)
        self.activeHost().statusBar().clearMessage()
        QMessageBox.warning(self._dialogParent(), "Sync from Remote",
                            f"{folder.label if folder else mirror} could not be copied:\n\n{why}")

    def onDocumentSaved(self, file_path: str):
        """A document was saved: if it is in the copy of a remote folder it is uploaded as well."""
        if self.remote.upload(file_path):
            folder = self.remote.folderFor(file_path)
            self.activeHost().statusBar().showMessage(f"Uploading to {folder.label} ...", 0)

    def onRemoteUploaded(self, file_path: str, label: str):
        self.activeHost().statusBar().showMessage(f"Saved on {label}", 5000)

    def onRemoteUploadFailed(self, file_path: str, why: str):
        self.activeHost().statusBar().clearMessage()
        QMessageBox.warning(self._dialogParent(), "Upload to Remote",
                            f"{Path(file_path).name} was saved on this computer but could not be uploaded:\n\n{why}\n\n"
                            "The copy here is kept, and a sync from the remote machine will not overwrite it. "
                            "Save the document again when the machine can be reached.")

    def add_window_to_menu(self, cwl_type:str='CommandLineTool', host:WorkbenchWindow=None):
        """
        Create a document of the given type as a new tab of ``host`` (by
        default the window the user works in) and list it in the Window menu.
        Returns the id of the document.
        """
        if host is None or sip.isdeleted(host):
            host = self.activeHost()

        # ids must stay unique after documents are closed
        if not hasattr(self, '_window_ids'):
            self._window_ids = itertools.count(1)
        window_id = next(self._window_ids)
        child_window = ChildWindow(window_id=window_id, cwl_type=cwl_type, parent=host)
        # Documents live as tabs of a window rather than as separate windows
        child_window.setWindowFlags(Qt.WindowType.Widget)
        
        # Set the same icon for the child window
        icon_path = data.configuration.get('icons').get('cwllogo') 
        app_icon = QIcon(icon_path)
        if not app_icon.isNull():
            child_window.setWindowIcon(app_icon)
        
        # Keep track of the window and show it
        self.open_windows[window_id] = child_window
        child_window.updateMenuSignal.connect(self.update_window_menu_entry)
        
        # Connect to the windowClosed signal to remove the window from the menu when closed
        child_window.windowClosed.connect(self.remove_window_from_menu)
        child_window.fileSaved.connect(self.onDocumentSaved)
        
        # Connect menu actions from child window to parent window handlers
        child_window.menuConfiguration.connect(self.onMenuConfiguration)
        
        # Add window to the window menu
        self.window_titles[window_id] = f"{window_id}: <{cwl_type}>"
        self.refreshWindowMenus()
        
        # Show the document as a new tab and bring it to the front
        host.tabs.addTab(child_window, self._documentIcon(child_window), self._documentTitle(child_window))
        child_window.windowTitleChanged.connect(lambda _title, w=child_window: self._refreshDocumentTab(w))
        self._refreshDocumentTab(child_window)
        self._showDocument(child_window)
        
        return(window_id)
        

    def update_window_menu_entry(self, window_id, new_name):
        if window_id in self.window_titles:
            self.logger.debug(f"Window {window_id} is in the list and its name will be updated to {new_name}")
            self.window_titles[window_id] = new_name
            self.refreshWindowMenus()
            if window_id in self.open_windows:
                self._refreshDocumentTab(self.open_windows[window_id])
        else:
            self.logger.warning(f"Window {window_id} is not in the list of windows")

    def remove_window_from_menu(self, window_id):
        # Remove the window entry from the Window menu
        if window_id in self.window_titles:
            self.logger.debug(f"Removing window {window_id} from the window menu")
            self.window_titles.pop(window_id, None)
            self.refreshWindowMenus()
        
        # Remove the closed window from the open windows dictionary and its tab
        window = self.open_windows.pop(window_id, None)
        tabs = DetachableTabWidget.tabsOf(window)
        if window is not None and tabs is not None and tabs.indexOf(window) >= 0:
            tabs.removeTab(tabs.indexOf(window))
            window.deleteLater()
        
        # If this was the active window, set active_window to None
        if self.active_window and hasattr(self.active_window, 'window_id') and self.active_window.window_id == window_id:
            self.active_window = None

    def close_all_windows(self):
        # Close all child windows
        for window in list(self.open_windows.values()):
            if window:
                window.close()
        self.open_windows.clear()

    def onMenuNewExpressionTool(self):
        self.add_window_to_menu('ExpressionTool')

    def onMenuNewWorkflow(self):
        self.add_window_to_menu('Workflow')
        # self.setMenu()
        

    def onMenuNewCommandTool(self):
        '''
        create a new window for a command line tool
        '''
        self.add_window_to_menu('CommandLineTool')

    def onMenuNewDraftCommandTool(self):
        '''
        Open DraftTool dialog to generate a draft CommandLineTool via LLM.
        On accept, create a new CommandLineTool window and load the generated file.
        '''
  

        try:
            dialog = DraftTool(parent=self._dialogParent())
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                # dialog.outfilename should contain generated file path (relative to CWD)
                out_file = getattr(dialog, 'outfilename', None)
                if out_file and Path(out_file).exists():
                    # Open new CommandLineTool window and load file
                    window_id = self.add_window_to_menu('CommandLineTool')
                    if window_id in self.open_windows:
                        self.open_windows[window_id].menuOpenFile.emit(str(Path(out_file).absolute()))
                else:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(self._dialogParent(), "Draft CommandLineTool", "No output file was produced or file missing.")
        # If rejected do nothing
        except Exception as e:
            self.logger.error(f"Error during Draft CommandLineTool creation: {e}")
            

    def onMenuFocus(self, window_id):
        if window_id in self.open_windows:
            self._showDocument(self.open_windows[window_id])




    def onMenuValidate(self):
        '''
        validate a CWL tool or workflow using cwltool --validate or
        another command specified in the configuration file

        '''
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            self.active_window.menuValidate.emit()

    def onMenuConfiguration(self):
        """
        Open the configuration dialog to edit application settings.
        """
        self.logger.debug("Opening configuration dialog")
        
        from ConfigDialog import ConfigDialog
        dialog = ConfigDialog(self._dialogParent())
        
        # Show the dialog and process the result
        if (dialog.exec() == QDialog.DialogCode.Accepted):
            self.logger.info("Configuration updated")
            
            # Update logger levels for various components
            if hasattr(self, 'logger'):
                new_level = data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG')
                self.logger.setLevel(new_level)
                
            # Update logger levels for open windows
            for window in self.open_windows.values():
                if hasattr(window, 'logger'):
                    new_level = data.configuration.get('logLevel', {}).get(window.__class__.__name__, 'DEBUG')
                    window.logger.setLevel(new_level)

    def onMenuResetConfiguration(self):
        """
        Reset the configuration to the default values by reloading from the 
        original configuration file in the resources directory.
        """
        self.logger.debug("Resetting configuration to defaults")
        
        # Ask for confirmation
        reply = QMessageBox.question(
            self._dialogParent(),
            "Reset Configuration",
            "Are you sure you want to reset the configuration to default values?\n\n"
            "This will overwrite your current settings.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from configuration import Configuration
                
                # Create a new Configuration instance pointing to the default config
                conf = Configuration(configuration_directory=data.config_directory)
                conf.resetConfigurationFile('cwled.yaml')
                
                self.logger.info("Configuration reset to defaults")
                QMessageBox.information(
                    self._dialogParent(),
                    "Configuration Reset",
                    "Configuration has been reset to default values."
                )
                
                # Update logger levels
                if hasattr(self, 'logger'):
                    new_level = data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG')
                    self.logger.setLevel(new_level)
                    
            except Exception as e:
                self.logger.error(f"Failed to reset configuration: {e}")
                QMessageBox.critical(
                    self._dialogParent(),
                    "Reset Failed",
                    f"Failed to reset configuration:\n{str(e)}"
                )

    def onMenuOpenFile(self):

        home_dir = self.activeHost().workspace.currentFolder() or str(Path.home())
        fname=QFileDialog.getOpenFileName(
            self._dialogParent(), 
            'Open file', 
            home_dir, 
            "*.txt;*.cwl;*.yaml;*.json")
        
        if fname[0]:
            self.logger.info(f"Opening file {fname[0]}")
            logger.debug(f"Opening file {fname[0]}")
            # self.file_path=fname[0]
            
            # self.pass_action_to_active_window("File Open")
            # if self.active_window:
            self.logger.info(f"Loading the file {fname[0]} to the current window")
            self.onCreateWindowFromFile( fname[0])
                # child_window_id=self.add_window_to_menu()
                # self.active_window.input_file=fname[0]
                # self.open_windows[child_window_id].menuOpenFile.emit(fname[0])
            # else:
                # print("No active window to load the file into, creating a new one")
            # self.loadCWL()
            # self.setWindowTitle( self.file_path)

    def onMenuSaveFile(self):
        # Invoke the Save As dialog if a file_path is not set
        # Otherwise save the file
        # if self.file_path:
        # self.saveFile(self.file_path, format)
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window.file_path :
            self.active_window.menuSaveFile.emit( 
                str(self.active_window.file_path) , 
                self.active_window.file_format
                )
        else:
            self.onMenuSaveAsFile()
        
    def onMenuSaveAsFile(self):
        # Invoke the Save As dialog
        # options = QFileDialog.Options()
        # options |= QFileDialog.Option.DontUseNativeDialog  # Optional: Use PyQt's dialog instead of the native OS one
        if not self.active_window:
            self._warnNoDocument()
            return None
        else:
            aw=self.active_window
        # Use the current workspace folder by default, or fall back to existing file location or home directory
        if self.activeHost().workspace.currentFolder():
            home_dir = self.activeHost().workspace.currentFolder()
        elif self.active_window.file_path:
            home_dir = str(Path(self.active_window.file_path).parent)
        else:
            home_dir = str(Path.home())
            
        filters = "YAML (*.cwl);;YAML (*.yaml);;JSON (*.cwl);;JSON (*.json)"
        # Show the dialog and get the selected file path
        file_path, format = QFileDialog.getSaveFileName(
            self._dialogParent(), 
            "Save As", 
            home_dir,  # Default directory or file name
            filters
        )
        if file_path:
            selected_format = 'YAML'
            selected_filter = (format or '').upper()
            suffix = Path(file_path).suffix.lower()

            if 'JSON' in selected_filter or suffix == '.json':
                selected_format = 'JSON'
            elif 'YAML' in selected_filter or suffix in ['.yaml', '.yml']:
                selected_format = 'YAML'

            aw.file_format = selected_format
            aw.menuSaveFile.emit(file_path, selected_format)
            
            # Add file to recent files list
            if data.configuration_manager:
                data.configuration_manager.addRecentFile(file_path)
                self.updateRecentMenu()
            
            return file_path
        
    def onMenuReloadFile(self):
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            self.active_window.menuReloadFile.emit()
    
    def onMenuUpgradeVersion(self):
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            self.active_window.menuUpgradeVersion.emit(None)
        
    def onMenuPackWorkflow(self):
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            self.active_window.menuPackWorkflow.emit(None)

    def onMenuRestructureWorkflow(self):
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            self.active_window.menuRestructureWorkflow.emit(None)

    def onMenuSaveDocumentation(self):
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            self.active_window.menuSaveDocumentation.emit()

    def onMenuMakeTemplate(self):
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            # print(f"Emitting signal for menu make template")
            self.active_window.menuMakeTemplate.emit()

    def onMenuTroubleshooting(self):
        """Handle the Troubleshoot tool/workflow menu action."""
        if not self.active_window:
            self._warnNoDocument()
            return None
        if self.active_window:
            self.active_window.menuTroubleshoot.emit()

    def onMenuHelp(self):
        """
        Opens the User Guide in the system's default web browser.
        Converts the markdown documentation to HTML and displays it.
        """
        self.logger.debug("Opening User Guide")
        
        try:
            # Path to the User-guide.md file
            # Handle both development and packaged environments
            if getattr(sys, 'frozen', False):
                # Running in PyInstaller bundle
                base_path = Path(sys._MEIPASS)
            else:
                # Running in normal Python environment
                base_path = Path(__file__).parent.parent
            
            user_guide_path = base_path / 'docs' / 'User-guide.md'
            docs_dir = user_guide_path.parent
            
            if not user_guide_path.exists():
                self.logger.error(f"User guide not found at {user_guide_path}")
                QMessageBox.warning(
                    self._dialogParent(),
                    "User Guide Not Found",
                    f"The user guide could not be found at:\n{user_guide_path}"
                )
                return
            
            # Read the markdown content
            with open(user_guide_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            
            # Convert markdown to HTML with extras for better formatting
            html_content = markdown2.markdown(
                markdown_content,
                extras=['tables', 'fenced-code-blocks', 'header-ids', 'code-friendly']
            )
            
            # Fix relative image paths to absolute file:// URLs
            import re
            def fix_image_path(match):
                src = match.group(1)
                # If it's a relative path (starts with ./ or just a filename)
                if not src.startswith(('http://', 'https://', 'file://')):
                    # Remove leading ./
                    src = src.lstrip('./')
                    # Create absolute path to image in docs directory
                    image_path = docs_dir / src
                    if image_path.exists():
                        return f'<img src="file://{image_path.absolute()}"'
                    else:
                        self.logger.warning(f"Image not found: {image_path}")
                return match.group(0)
            
            html_content = re.sub(r'<img src="([^"]+)"', fix_image_path, html_content)
            
            # Create styled HTML document
            styled_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>CWLed User Guide</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            color: {theme.TEXT};
            background-color: {theme.BODY_BG};
        }}
        h1 {{
            color: {theme.WHITE};
            font-family: Montserrat, sans-serif;
            border-bottom: 2px solid {theme.SKY};
            padding-bottom: 10px;
        }}
        h2 {{
            color: {theme.TEXT};
            font-family: Montserrat, sans-serif;
            margin-top: 30px;
            border-bottom: 1px solid {theme.BLACK};
            padding-bottom: 8px;
        }}
        h3 {{
            color: {theme.TEXT};
            margin-top: 20px;
        }}
        code {{
            background-color: {theme.INPUT_BG};
            padding: 2px 6px;
            border-radius: 2px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.9em;
            color: {theme.CODE_ARGS};
        }}
        pre {{
            background-color: {theme.TERMINAL_BG};
            padding: 16px;
            border-radius: 2px;
            overflow-x: auto;
            border: 1px solid {theme.BLACK};
        }}
        pre code {{
            background-color: transparent;
            padding: 0;
            color: {theme.CODE_STREAM};
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
        }}
        th, td {{
            border: 1px solid {theme.BLACK};
            padding: 12px;
            text-align: left;
        }}
        th {{
            background-color: {theme.PANEL_BG};
            font-weight: bold;
        }}
        tr:nth-child(even) {{
            background-color: {theme.INPUT_BG};
        }}
        a {{
            color: {theme.SKY};
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 20px auto;
            border: 1px solid {theme.BLACK};
            border-radius: 2px;
        }}
        blockquote {{
            border-left: 4px solid {theme.SKY};
            margin: 20px 0;
            padding: 10px 20px;
            background-color: {theme.PANEL_BG};
        }}
        ul, ol {{
            padding-left: 30px;
        }}
        li {{
            margin: 8px 0;
        }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""
            
            # Create a temporary HTML file
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.html', encoding='utf-8') as f:
                f.write(styled_html)
                temp_path = f.name
            
            # Open in the default web browser
            webbrowser.open(f'file://{temp_path}')
            self.logger.info(f"Opened user guide in browser: {temp_path}")
            
        except Exception as e:
            self.logger.error(f"Error opening user guide: {e}")
            QMessageBox.critical(
                self,
                "Error Opening User Guide",
                f"An error occurred while opening the user guide:\n{str(e)}"
            )
