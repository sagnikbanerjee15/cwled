from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer, QSize, QMimeData, QUrl
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMenu, QVBoxLayout, QHBoxLayout, QDialog,
    QFileDialog, QLabel, QPushButton, QWidget,QMessageBox, QSplitter,
    QTabWidget, QTabBar, QStackedWidget, QListWidget, QListWidgetItem,
    QToolButton, QFrame, QAbstractItemView, QScrollArea, QSizePolicy
)
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QFontMetrics, QPixmap, QKeySequence
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
from WorkspaceContents import WorkspaceContents
import workspaceFolders
from logger import ErrorDialogHandler
from draft import DraftTool
import cwled
from platformdirs import user_config_path, user_log_path
import version
import itertools
import theme
logger = logging.getLogger(__name__)


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
class MainWindow( QMainWindow):
    '''
    class for the main window
    It hosts all the tabs menus etc
    When a menu action is triggered it passes a message to the downstream applications.
    '''
    cwl_dict={}  # this is the cwl dictionary that we carry over in this window
    openWindowFromFile = pyqtSignal(str) # this signal will transfer the filename to open in a window
    def __init__(self , 
                 input_files:List[PosixPath|Path]=None,
                 export_image_file:str=None):
        super().__init__()
        # load the configuration
        self.logger=logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        self.setupGlobalErrorDialogLogging()
        self.open_windows={}
        self.window_actions={}
        self.active_window=None
        self.logger.info(f"Setting up {self.__class__.__name__}")
        self.logger.info(f"Logging level set to {logging.getLevelName(self.logger.level)}")
        self.openWindowFromFile.connect( self.onCreateWindowFromFile )
        self.initUI()

        QTimer.singleShot(100, self._ensureWindowActive)
        
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
        Documents open as tabs instead of separate windows.
        """
        self.resize(self._initialSize())

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName('mainSplitter')
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        self.sidebar = self._buildSidebar()
        splitter.addWidget(self.sidebar)

        self.workbox = QTabWidget(self)
        self.workbox.setObjectName('workbox')
        self.workbox.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.workbox.setTabsClosable(True)
        self.workbox.setMovable(True)
        self.workbox.setUsesScrollButtons(True)
        self.workbox.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.workbox.tabBar().setExpanding(False)
        self.workbox.tabCloseRequested.connect(self.onWorkboxTabClose)
        self.workbox.currentChanged.connect(self.onWorkboxCurrentChanged)

        new_tab_button = QToolButton(self.workbox)
        new_tab_button.setIcon(theme.icon('plus', color=theme.TEXT_MUTED, active_color=theme.WHITE))
        new_tab_button.setToolTip("New file")
        new_tab_button.setAutoRaise(True)
        new_tab_button.clicked.connect(self.showWelcomeTab)
        self.workbox.setCornerWidget(new_tab_button, Qt.Corner.TopRightCorner)

        self.welcome = self._buildWelcomePage()
        self.showWelcomeTab()
        splitter.addWidget(self.workbox)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([270, max(400, self.width() - 270)])
        self.setCentralWidget(splitter)

        # Status bar (Composer: ct-status-bar)
        status_bar = self.statusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.setFixedHeight(theme.STATUS_BAR_HEIGHT)
        self.workspace_status = QLabel()
        status_bar.addWidget(self.workspace_status, 1)
        version_status = QLabel(f"CWLed {version.__version__}")
        version_status.setProperty('muted', True)
        status_bar.addPermanentWidget(version_status)
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

    def _buildSidebar(self) -> QWidget:
        """Left panel: application title, then 'Workspace' / 'Recent' panels."""
        sidebar = QWidget(self)
        sidebar.setObjectName('sidebar')
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setMinimumWidth(200)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = QWidget(sidebar)
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
        self.sidebar_tabs = QTabBar(sidebar)
        self.sidebar_tabs.setExpanding(True)
        self.sidebar_tabs.setDrawBase(False)
        self.sidebar_tabs.addTab("Workspace")
        self.sidebar_tabs.addTab("Recent")
        layout.addWidget(self.sidebar_tabs)

        self.sidebar_pages = QStackedWidget(sidebar)
        self.sidebar_tabs.currentChanged.connect(self.sidebar_pages.setCurrentIndex)

        # one root per workspace folder (Composer "Local Files")
        self.workspace_panel = WorkspaceContents(workspace_path=workspaceFolders.folders(), parent=sidebar, sidebar=True)
        self.workspace_panel.setWindowFlags(Qt.WindowType.Widget)
        self.workspace_panel.fileSelected.connect(self.onCreateWindowFromFile)
        self.workspace_panel.addFolderRequested.connect(self.onAddWorkspaceFolder)
        self.workspace_panel.removeFolderRequested.connect(self.onRemoveWorkspaceFolder)
        self.workspace_panel.currentFolderChanged.connect(self.onCurrentWorkspaceFolderChanged)
        self.sidebar_pages.addWidget(self.workspace_panel)

        self.recent_panel = self._buildRecentList()
        self.sidebar_pages.addWidget(self.recent_panel)
        layout.addWidget(self.sidebar_pages, 1)
        return sidebar

    def _buildRecentList(self) -> QListWidget:
        recent_list = RecentFilesList()
        recent_list.setIconSize(QSize(16, 16))
        recent_list.itemDoubleClicked.connect(
            lambda item: self.onOpenRecentFile(item.data(Qt.ItemDataRole.UserRole)))
        self._recent_lists = getattr(self, '_recent_lists', []) + [recent_list]
        return recent_list

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
        recent.addWidget(self._buildRecentList(), 1)
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
        """Refresh every view showing the workspace folders."""
        self._updateWorkspaceStatus()
        if hasattr(self, 'welcome_workspace_folders'):
            self._refreshWelcomeWorkspace()
        if hasattr(self, 'workspace_panel'):
            self.workspace_panel.setWorkspaceFolders(workspaceFolders.folders())

    def _updateWorkspaceStatus(self):
        """Status bar: the current workspace folder (where new files go) and the number of others."""
        if not hasattr(self, 'workspace_status'):
            return
        folders = workspaceFolders.folders()
        text = f"Workspace: {workspaceFolders.currentFolder() or 'no folder'}"
        if len(folders) > 1:
            others = len(folders) - 1
            text += f"  (+{others} more folder{'s' if others > 1 else ''})"
        self.workspace_status.setText(text)
        self.workspace_status.setToolTip("Workspace folders:\n" + "\n".join(folders) if folders else "")

    def _refreshWelcomeWorkspace(self):
        """Start page: one row per workspace folder."""
        layout = self.welcome_workspace_folders
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        folders = workspaceFolders.folders()
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
            icon_label.setPixmap(theme.icon('folder').pixmap(QSize(14, 14), self.devicePixelRatioF()))
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
        """Refresh the 'Recent' side panel and the start page list."""
        recent_files = [f for f in reversed(data.configuration.get('recents', []) or [])
                        if self._fileExists(f)]
        for recent_list in getattr(self, '_recent_lists', []):
            recent_list.clear()
            for file_path in recent_files:
                item = QListWidgetItem(theme.icon('file-o', color=theme.SMOKE), Path(file_path).name)
                item.setToolTip(str(file_path))
                item.setData(Qt.ItemDataRole.UserRole, str(file_path))
                recent_list.addItem(item)
            if not recent_files:
                placeholder = QListWidgetItem("No recent files")
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                recent_list.addItem(placeholder)

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
        index = self.workbox.indexOf(window)
        if index < 0:
            return
        self.workbox.setTabText(index, self._documentTitle(window))
        self.workbox.setTabIcon(index, self._documentIcon(window))
        self.workbox.setTabToolTip(index, window.windowTitle())

    def _showDocument(self, window: ChildWindow):
        """Bring a document tab to the front."""
        if self.workbox.indexOf(window) >= 0:
            self.workbox.setCurrentWidget(window)
            self.active_window = window
            window.setFocus()
        else:
            window.raise_()
            window.activateWindow()

    def onWorkboxTabClose(self, index: int):
        """Close a document tab; the document may veto it (unsaved changes)."""
        widget = self.workbox.widget(index)
        if widget is None:
            return
        if widget is self.welcome:
            self.workbox.removeTab(index)
            return
        # ChildWindow.closeEvent prompts for unsaved changes and emits
        # windowClosed, which removes the tab (remove_window_from_menu).
        widget.close()

    def onWorkboxCurrentChanged(self, index: int):
        widget = self.workbox.widget(index)
        self.active_window = widget if isinstance(widget, ChildWindow) else None

    def closeEvent(self, event):
        """Closing the main window closes every document (each may veto)."""
        for window in list(self.open_windows.values()):
            if isinstance(window, ChildWindow) and not window.close():
                event.ignore()
                return
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
        # Check if the file is already open in an existing window
        resolved_path = str(Path(input_file).resolve())
        for window in self.open_windows.values():
            if hasattr(window, 'file_path') and window.file_path:
                if str(Path(window.file_path).resolve()) == resolved_path:
                    self._showDocument(window)
                    return

        child_window_id=self.add_window_to_menu()
        # self.active_window.file_path=input_file
        self.open_windows[child_window_id].menuOpenFile.emit(input_file)
        
        # Add file to recent files and update the menu
        if data.configuration_manager:
            data.configuration_manager.addRecentFile(input_file)
            self.updateRecentMenu()

    def setMenu(self):
        '''
        set the menu in the main application
        '''
        file_open=QAction(  "&Open file ...",self)
        file_open.setShortcut(QKeySequence.StandardKey.Open)
        file_open.triggered.connect(self.onMenuOpenFile)
        file_save=QAction(  "&Save",self)
        file_save.setShortcut(QKeySequence.StandardKey.Save)
        file_save.triggered.connect(self.onMenuSaveFile)
        file_saveas=QAction(  "Save as ...",self)
        file_saveas.setShortcut(QKeySequence.StandardKey.SaveAs)
        file_saveas.triggered.connect(self.onMenuSaveAsFile)
        file_reload=QAction(  "Reload file",self)
        file_reload.setShortcut(QKeySequence.StandardKey.Refresh)
        file_reload.triggered.connect(self.onMenuReloadFile)
        file_add_folder=QAction(  "Add Folder to Workspace...",self)
        file_add_folder.setToolTip("Add a folder to the workspace")
        file_add_folder.triggered.connect(self.onAddWorkspaceFolder)
        file_close=QAction(  "Close tab",self)
        file_close.setShortcut(QKeySequence.StandardKey.Close)
        file_close.triggered.connect(lambda: self.onWorkboxTabClose(self.workbox.currentIndex()))
        file_exit=QAction(  "E&xit",self)
        file_exit.setShortcut(QKeySequence.StandardKey.Quit)
        file_exit.setMenuRole(QAction.MenuRole.QuitRole)
        file_exit.triggered.connect(self.close)
        # create a submenu for New
        

        tools_validate=QAction(  "Validate tool",self)
        tools_validate.triggered.connect(self.onMenuValidate)
        tools_maketemplate=QAction(  "Generate template",self)
        tools_maketemplate.triggered.connect(self.onMenuMakeTemplate)
        
        tools_upgrade=QAction(  "Upgrade CWL version",self)
        tools_upgrade.triggered.connect(self.onMenuUpgradeVersion)
        tools_pack_workflow=QAction(  "Pack workflow to single file",self)
        tools_pack_workflow.triggered.connect(self.onMenuPackWorkflow)
        tools_restructure_workflow=QAction(  "Repackage workflow with all tools",self)
        tools_restructure_workflow.triggered.connect(self.onMenuRestructureWorkflow)
        tools_save_documentation=QAction(  "Save workflow documentation",self)
        tools_save_documentation.triggered.connect(self.onMenuSaveDocumentation)
        tools_configuration=QAction( "Configuration",self)
        tools_configuration.setShortcut(QKeySequence.StandardKey.Preferences)
        tools_configuration.triggered.connect(self.onMenuConfiguration)
        tools_reset_configuration=QAction( "Reset configuration to default",self)
        tools_reset_configuration.triggered.connect(self.onMenuResetConfiguration)
        tools_draft_commandtool=QAction("Draft CommandLineTool from documentation", self)
        tools_draft_commandtool.triggered.connect(self.onMenuNewDraftCommandTool)

        tools_troubleshoot=QAction(  "Troubleshoot tool/workflow",self)
        tools_troubleshoot.triggered.connect(self.onMenuTroubleshooting)

        new_commandtool=QAction( "Command line tool", self)
        new_commandtool.triggered.connect(self.onMenuNewCommandTool)
        new_expressiontool=QAction("Expression tool", self)
        new_expressiontool.triggered.connect(self.onMenuNewExpressionTool)
        new_workflow=QAction("Workflow", self)
        new_workflow.triggered.connect(self.onMenuNewWorkflow)
        # Draft CommandLineTool placeholder action
        

        self.file_menu=self.menu.addMenu( "&File")
        self.file_menu.addAction( file_open )
        self.file_menu.addAction( file_save)
        self.file_menu.addAction( file_saveas )
        self.file_menu.addAction( file_reload )

        self.new_menu = QMenu("New", self)
        self.file_menu.addMenu(self.new_menu)
        self.new_menu.addAction( new_commandtool)
        self.new_menu.addAction( new_expressiontool)
        self.new_menu.addAction( new_workflow)
        self.new_menu.addSeparator()
        
        # Add Recent submenu
        self.recent_menu = QMenu("Recent", self)
        self.file_menu.addMenu(self.recent_menu)
        self.updateRecentMenu()
        self.file_menu.addSeparator()
        self.file_menu.addAction( file_add_folder )
        self.file_menu.addSeparator()
        self.file_menu.addAction( file_close )
        self.file_menu.addAction( file_exit )
        

        self.tools_menu=self.menu.addMenu( "&Tools")
        self.tools_menu.addAction( tools_validate)
        self.tools_menu.addAction( tools_maketemplate)
        self.tools_menu.addAction( tools_pack_workflow)
        self.tools_menu.addAction( tools_restructure_workflow)
        self.tools_menu.addAction( tools_save_documentation)
        self.tools_menu.addAction( tools_upgrade)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction( tools_configuration)
        self.tools_menu.addAction( tools_reset_configuration)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction( tools_draft_commandtool)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction( tools_troubleshoot)
        
        self.window_menu=self.menu.addMenu("&Window")
        main_window_action = QAction("Main Window", self)
        main_window_action.triggered.connect(self._ensureWindowActive)
        self.window_menu.addAction(main_window_action)
        self.window_menu.addSeparator()
        
        # Help menu
        self.help_menu = self.menu.addMenu("&Help")
        help_user_guide = QAction("User Guide", self)
        help_user_guide.triggered.connect(self.onMenuHelp)
        self.help_menu.addAction(help_user_guide)

    def updateRecentMenu(self):
        """
        Update the Recent menu with the list of recently opened files.
        Shows up to 10 most recently opened files.
        Shows basename only if unique, or basename with parent directory if duplicates exist.
        """
        # Clear existing menu items
        self.recent_menu.clear()
        
        # Get recent files from configuration
        recent_files = data.configuration.get('recents', [])
        
        if not recent_files:
            # Show "No recent files" if the list is empty
            no_recent_action = QAction("No recent files", self)
            no_recent_action.setEnabled(False)
            self.recent_menu.addAction(no_recent_action)
        else:
            # Track files that need to be removed due to errors
            files_to_remove = []

            # Count how many times each basename appears to detect duplicates
            from collections import Counter
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

            basename_counts = Counter(Path(f).name for f in valid_files)

            # Add recent files (already in most-recent-first order)
            for file_path in valid_files:
                file_name = Path(file_path).name
                if basename_counts[file_name] > 1:
                    display_name = f"{file_name}  —  {Path(file_path).parent.name}"
                else:
                    display_name = file_name
                action = QAction(display_name, self)
                action.setToolTip(file_path)  # Show full path as tooltip
                action.triggered.connect(lambda checked, f=file_path: self.onOpenRecentFile(f))
                self.recent_menu.addAction(action)
            
            # Remove inaccessible files from the recent files list
            if files_to_remove:
                for file_path in files_to_remove:
                    if file_path in data.configuration['recents']:
                        data.configuration['recents'].remove(file_path)
                data.configuration_manager.saveConfiguration()

        self.updateRecentLists()
    
    def onOpenRecentFile(self, file_path:str):
        """
        Open a file from the recent files list.
        
        Args:
            file_path (str): Full path to the file to open.
        """
        try:
            if Path(file_path).exists():
                self.logger.info(f"Opening recent file {file_path}")
                self.onCreateWindowFromFile(file_path)
            else:
                self.logger.error(f"Recent file {file_path} no longer exists")
                QMessageBox.warning(self, "File Not Found", 
                                  f"The file {file_path} no longer exists.")
                # Remove the file from recent files list
                if file_path in data.configuration['recents']:
                    data.configuration['recents'].remove(file_path)
                    data.configuration_manager.saveConfiguration()
                    self.updateRecentMenu()  # Refresh the menu
        except (OSError, ValueError) as e:
            self.logger.error(f"Error accessing recent file {file_path}: {e}")
            QMessageBox.warning(self, "Error Opening File", 
                              f"Cannot access the file {file_path}:\n{str(e)}")
            # Remove the file from recent files list
            if file_path in data.configuration['recents']:
                data.configuration['recents'].remove(file_path)
                data.configuration_manager.saveConfiguration()
                self.updateRecentMenu()  # Refresh the menu
    
    def set_active_child_window(self, old, new):
        # Set the currently active child window
        any_window_active = False
        for window in self.open_windows.values():
            if window.isAncestorOf(new) or window == new:
                self.active_window = window
                any_window_active = True
                break
                
        if not any_window_active:
            # Focus is outside the documents (side panel, menus...): the
            # document shown in the workbox stays the active one.
            current = self.workbox.currentWidget() if hasattr(self, 'workbox') else None
            self.active_window = current if isinstance(current, ChildWindow) else None
        
        # Only log the window_id if we have an active window
        if self.active_window:
            self.logger.debug(f"Set the active window to {self.active_window.window_id}")
        else:
            self.logger.debug("No active window set")
    
    def add_window_to_menu(self, cwl_type:str='CommandLineTool'):

        # ids must stay unique after documents are closed
        if not hasattr(self, '_window_ids'):
            self._window_ids = itertools.count(1)
        window_id = next(self._window_ids)
        child_window = ChildWindow(window_id=window_id, cwl_type=cwl_type, parent=self)
        # Documents live as tabs of the workbox rather than as separate windows
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
        
        # Connect menu actions from child window to parent window handlers
        child_window.menuConfiguration.connect(self.onMenuConfiguration)
        
        # Add window to the window menu
        new_window=QAction(f"{window_id}: <{cwl_type}>", self)
        new_window.triggered.connect(lambda: self.onMenuFocus(window_id))
        self.window_menu.addAction(new_window)
        self.window_actions[window_id]=new_window
        
        # Show the document as a new tab and bring it to the front
        self.workbox.addTab(child_window, self._documentIcon(child_window), self._documentTitle(child_window))
        child_window.windowTitleChanged.connect(lambda _title, w=child_window: self._refreshDocumentTab(w))
        self._refreshDocumentTab(child_window)
        self._showDocument(child_window)
        
        return(window_id)
        

    def update_window_menu_entry(self, window_id, new_name):
        if window_id in self.window_actions:
            self.logger.debug(f"Window {window_id} is in the list and its name will be updated to {new_name}")
            self.window_actions[window_id].setText(new_name)
            if window_id in self.open_windows:
                self._refreshDocumentTab(self.open_windows[window_id])
        else:
            self.logger.warning(f"Window {window_id} is not in the list of windows")

    def remove_window_from_menu(self, window_id):
        # Remove the window entry from the Window menu
        if window_id in self.window_actions:
            self.logger.debug(f"Removing window {window_id} from the window menu")
            # Remove the action from the window menu
            self.window_menu.removeAction(self.window_actions[window_id])
            # Remove the action from our dictionary
            self.window_actions.pop(window_id, None)
        
        # Remove the closed window from the open windows dictionary and its tab
        window = self.open_windows.pop(window_id, None)
        if window is not None and self.workbox.indexOf(window) >= 0:
            self.workbox.removeTab(self.workbox.indexOf(window))
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
            dialog = DraftTool(parent=self)
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
                    QMessageBox.warning(self, "Draft CommandLineTool", "No output file was produced or file missing.")
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
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        if self.active_window:
            self.active_window.menuValidate.emit()

    def onMenuConfiguration(self):
        """
        Open the configuration dialog to edit application settings.
        """
        self.logger.debug("Opening configuration dialog")
        
        from ConfigDialog import ConfigDialog
        dialog = ConfigDialog(self)
        
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
            self,
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
                    self,
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
                    self,
                    "Reset Failed",
                    f"Failed to reset configuration:\n{str(e)}"
                )

    def onMenuOpenFile(self):

        home_dir = workspaceFolders.currentFolder() or str(Path.home())
        fname=QFileDialog.getOpenFileName(
            self, 
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
            QMessageBox.warning(self, "No Document", "Please select a document first.")
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
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        else:
            aw=self.active_window
        # Use the current workspace folder by default, or fall back to existing file location or home directory
        if workspaceFolders.currentFolder():
            home_dir = workspaceFolders.currentFolder()
        elif self.active_window.file_path:
            home_dir = str(Path(self.active_window.file_path).parent)
        else:
            home_dir = str(Path.home())
            
        filters = "YAML (*.cwl);;YAML (*.yaml);;JSON (*.cwl);;JSON (*.json)"
        # Show the dialog and get the selected file path
        file_path, format = QFileDialog.getSaveFileName(
            self, 
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
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        if self.active_window:
            self.active_window.menuReloadFile.emit()
    
    def onMenuUpgradeVersion(self):
        if not self.active_window:
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        if self.active_window:
            self.active_window.menuUpgradeVersion.emit(None)
        
    def onMenuPackWorkflow(self):
        if not self.active_window:
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        if self.active_window:
            self.active_window.menuPackWorkflow.emit(None)

    def onMenuRestructureWorkflow(self):
        if not self.active_window:
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        if self.active_window:
            self.active_window.menuRestructureWorkflow.emit(None)

    def onMenuSaveDocumentation(self):
        if not self.active_window:
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        if self.active_window:
            self.active_window.menuSaveDocumentation.emit()

    def onMenuMakeTemplate(self):
        if not self.active_window:
            QMessageBox.warning(self, "No Document", "Please select a document first.")
            return None
        if self.active_window:
            # print(f"Emitting signal for menu make template")
            self.active_window.menuMakeTemplate.emit()

    def onMenuTroubleshooting(self):
        """Handle the Troubleshoot tool/workflow menu action."""
        if not self.active_window:
            QMessageBox.warning(self, "No Document", "Please select a document first.")
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
                    self,
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


    def onOpenWorkspace(self):
        """
        Show the workspace browser in the side panel and rescan the workspace.
        """
        self.logger.debug("Opening workspace browser")
        self.sidebar.show()
        self.sidebar_tabs.setCurrentIndex(self.sidebar_pages.indexOf(self.workspace_panel))
        self.workspace_panel.on_rescan_clicked()
        self.workspace_panel.search_box.setFocus()

    def onAddWorkspaceFolder(self):
        """
        Choose a folder and add it to the workspace (Composer "Add a Folder").
        """
        self.logger.debug("Adding a folder to the workspace")
        start_directory = workspaceFolders.currentFolder() or str(Path.home())
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
        status, related = workspaceFolders.addFolder(folder)
        if status == workspaceFolders.DUPLICATE:
            QMessageBox.information(self, "Add a Folder", f"{folder} is already in the workspace.")
            return False
        if status == workspaceFolders.NESTED:
            QMessageBox.information(self, "Add a Folder",
                                    f"{folder} is already in the workspace, inside {related[0]}.")
            return False
        self.updateWorkspaceViews()
        self.sidebar.show()
        self.sidebar_tabs.setCurrentIndex(self.sidebar_pages.indexOf(self.workspace_panel))
        self.workspace_panel.showFolder(workspaceFolders.currentFolder())
        message = f"Added {workspaceFolders.currentFolder()} to the workspace"
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
        open_documents = [window for window in self.open_windows.values()
                          if getattr(window, 'file_path', None)
                          and workspaceFolders.containingFolder(window.file_path) == folder]
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
        if workspaceFolders.removeFolder(folder):
            self.updateWorkspaceViews()
            self.statusBar().showMessage(f"Removed {folder} from the workspace", 5000)

    def onCurrentWorkspaceFolderChanged(self, folder: str):
        """The user works in another workspace folder: new files go there."""
        if workspaceFolders.setCurrentFolder(folder):
            self._updateWorkspaceStatus()
