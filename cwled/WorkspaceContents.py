from PyQt6 import sip
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTreeView, 
                            QDialogButtonBox, QPushButton, QLabel, QHBoxLayout, QLineEdit,
                            QApplication, QStyledItemDelegate, QStyle, QToolButton,
                            QStyleOptionViewItem, QHeaderView, QMenu)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QIcon, QColor
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QModelIndex, QFileSystemWatcher, QTimer
from pathlib import Path
from collections import Counter
import logging
import os, re
from CWLparser import Parser
from schema_salad.exceptions import ValidationException
import data
import theme

# The files the tree lists
CWL_SUFFIXES = ('.cwl', '.json', '.yaml')
# Folders that are never listed, nor searched for documents (version control, caches, environments)
IGNORED_FOLDERS = {'.git', '.hg', '.svn', '__pycache__', 'node_modules', '.venv', 'venv', '.tox'}
# At most this many folders are watched for changes (the operating systems limit the watches)
MAX_WATCHED_FOLDERS = 150
REFRESH_DELAY_MS = 500

# Custom data roles for lazy loading
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_IS_LOADED = Qt.ItemDataRole.UserRole + 1
ROLE_IS_DIRECTORY = Qt.ItemDataRole.UserRole + 2


class VersionColumnDelegate(QStyledItemDelegate):
    """Center Version column content (icon or text)."""

    def paint(self, painter, option, index):
        if index.column() != 1:
            super().paint(painter, option, index)
            return

        painter.save()

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        if icon:
            base = option.decorationSize if option.decorationSize.isValid() else QSize(20, 20)
            target_size = QSize(int(base.width() * 1.5), int(base.height() * 1.5 ))
            pixmap = icon.pixmap(target_size)
            x = option.rect.x() + (option.rect.width() - pixmap.width()) // 2
            y = option.rect.y() + option.rect.height() - pixmap.height()
            painter.drawPixmap(x, y, pixmap)
        else:
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, str(text))

        painter.restore()

class SidebarItemDelegate(QStyledItemDelegate):
    """Composer tree look: folder / file icons for entries without a CWL icon."""

    def __init__(self, tree_view):
        super().__init__(tree_view)
        self._tree_view = tree_view
        self._folder = theme.icon('folder')
        self._folder_open = theme.icon('folder-open')
        self._file = theme.icon('file-o', color=theme.SMOKE)

    def initStyleOption(self, option: QStyleOptionViewItem, index):
        super().initStyleOption(option, index)
        if index.column() != 0 or not option.icon.isNull() or index.data(ROLE_PATH) is None:
            # placeholders ("No search results...") have no icon
            return
        model = index.model()
        is_directory = index.data(ROLE_IS_DIRECTORY) or model.hasChildren(index)
        if is_directory:
            option.icon = self._folder_open if self._tree_view.isExpanded(index) else self._folder
        else:
            option.icon = self._file
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration


class WorkspaceContents(QMainWindow):
    """
    A class that displays the contents of a workspace in a tree view.
    Shows all files with .cwl, .json, .yaml extensions in a tree structure,
    with one root per workspace folder (Composer "Local Files").
    """
    fileSelected = pyqtSignal(str)  # Signal emitted when a file is selected
    addFolderRequested = pyqtSignal()  # "Add a Folder" was clicked
    removeFolderRequested = pyqtSignal(str)  # "Remove from Workspace" on a workspace folder
    currentFolderChanged = pyqtSignal(str)  # workspace folder of the selected item
    showHiddenChanged = pyqtSignal(bool)    # the "show hidden folders" setting changed
    followDocumentChanged = pyqtSignal(bool)  # the "follow the open document" setting changed
    
    def __init__(self, workspace_path=None, parent=None, sidebar=False):
        """
        Initialize the workspace contents view.
        
        Args:
            workspace_path (str | list, optional): Path to the workspace directory,
                or a list of workspace folders
            parent (QWidget, optional): Parent widget
            sidebar (bool, optional): Compact layout for the main window side
                panel (search on top, name column only, icon buttons).
        """
        super().__init__(parent)
        self.sidebar = sidebar
        
        # Set up logging
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        
        self.workspace_folders = self._folderList(workspace_path)
        self._shown_roots = []    # roots of the last full tree (to keep their expansion)
        self._search_text = ""    # the active search, if any
        self._showing_search = False      # the tree shows search results
        self._full_tree_expanded = None   # expanded folders of the full tree during a search
        self._revealing = False           # the selection is moved by revealFile(), not by the user
        configuration = data.configuration or {}
        self.show_hidden = bool(configuration.get('workspace_show_hidden', False))   # list folders starting with a dot
        self.follow_document = bool(configuration.get('workspace_follow_document', True))  # select the open document
        self._cwl_folders = {}            # folder -> does it hold documents (valid until the tree is rebuilt)
        self._metadata_cache = {}         # file -> ((mtime, size), (class, version, format))
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._onFolderChanged)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(REFRESH_DELAY_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(0)
        self._watch_timer.timeout.connect(self._syncWatches)

        # Unique window identifier
        self.window_id = "WorkspaceContents"
        
        self.initUI()
        
        # Populate tree if a workspace path was provided
        if self.workspace_folders:
            self.populate_tree()
        self._updateEmptyState()

    @property
    def workspace_path(self):
        """The first workspace folder (the tree used to show a single folder)."""
        return self.workspace_folders[0] if self.workspace_folders else None

    @workspace_path.setter
    def workspace_path(self, path):
        self.workspace_folders = self._folderList(path)

    @staticmethod
    def _folderList(paths) -> list:
        """A workspace folder or a list of them, as a list of strings."""
        if not paths:
            return []
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        return [str(path) for path in paths]

    def setWorkspaceFolders(self, folders):
        """Show these workspace folders (each one is a root of the tree)."""
        folders = self._folderList(folders)
        if folders == self.workspace_folders:
            return
        self.workspace_folders = folders
        self.refresh()

    def refresh(self):
        """
        Rebuild the tree: the search results while searching, else the folders.
        The folders that were expanded stay expanded, and so do the selection and
        the scroll position.
        """
        self._refresh_timer.stop()
        self._cwl_folders.clear()
        selected = self._selectedPath()
        scroll = self.tree_view.verticalScrollBar().value()
        if self._search_text:
            self.filter_tree_by_name(self._search_text)
        else:
            self.populate_tree()
        if selected:
            self._selectPath(selected)
        self.tree_view.verticalScrollBar().setValue(scroll)

    def _selectedPath(self):
        index = self.tree_view.currentIndex()
        return index.siblingAtColumn(0).data(ROLE_PATH) if index.isValid() else None

    def _selectPath(self, path):
        """Select an entry that is shown (expanded folders only), without it being the user's choice."""
        index = self._indexOfPath(path, expand=False)
        if index is not None:
            self._revealing = True
            try:
                self.tree_view.setCurrentIndex(index)
            finally:
                self._revealing = False

    # -- settings ----------------------------------------------------------------------------------
    def _saveSetting(self, key, value):
        configuration = data.configuration
        if configuration is None:
            return
        configuration[key] = value
        if data.configuration_manager:
            try:
                data.configuration_manager.saveConfiguration()
            except Exception as e:
                self.logger.error(f"Cannot save the setting {key}: {e}")

    def setShowHidden(self, show: bool):
        """List (or not) the folders whose name starts with a dot, such as the ``.steps`` of a repackaged workflow."""
        show = bool(show)
        if show == self.show_hidden:
            return
        self.show_hidden = show
        self._saveSetting('workspace_show_hidden', show)
        self.showHiddenChanged.emit(show)
        self.refresh()

    def setFollowDocument(self, follow: bool):
        """Select the file of the open document in the tree (see WorkbenchWindow)."""
        follow = bool(follow)
        if follow == self.follow_document:
            return
        self.follow_document = follow
        self._saveSetting('workspace_follow_document', follow)
        self.followDocumentChanged.emit(follow)
    
    def initUI(self):
        """Initialize the UI components"""
        self.setWindowTitle("Workspace Contents")
        self.resize(500, 600)
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Add path label
        self.path_label = QLabel("Workspace: Not set")
        main_layout.addWidget(self.path_label)
        
        # Create tree view
        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(False)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.doubleClicked.connect(self.on_item_double_clicked)
        # Set icon size to 20x20 pixels
        self.tree_view.setIconSize(QSize(20, 20))
        
        # Create model with three columns: Name, Version, Date Modified
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(['Name', 'Version', 'Format', 'Date Modified'])
        self.tree_view.setModel(self.model)
        self.tree_view.setItemDelegateForColumn(1, VersionColumnDelegate(self.tree_view))
        self.tree_view.setSortingEnabled(True)
        self.tree_view.header().setSortIndicatorShown(True)
        self.tree_view.header().setSectionsClickable(True)
        self.tree_view.header().sectionClicked.connect(self.on_treeview_section_clicked)
        
        main_layout.addWidget(self.tree_view)

        # Shown instead of the tree when the workspace has no folder
        self.empty_state = self._buildEmptyState()
        main_layout.addWidget(self.empty_state, 1)
        
        # Add buttons at the bottom
        button_box = QDialogButtonBox()
        
        # Rescan button to refresh the workspace view
        rescan_btn = QPushButton("Rescan")
        rescan_btn.clicked.connect(self.on_rescan_clicked)
        button_box.addButton(rescan_btn, QDialogButtonBox.ButtonRole.ActionRole)

        # Add a folder to the workspace
        add_folder_btn = QPushButton("Add Folder...")
        add_folder_btn.clicked.connect(self.addFolderRequested)
        button_box.addButton(add_folder_btn, QDialogButtonBox.ButtonRole.ActionRole)
        
        # Open button to open selected file
        open_btn = QPushButton("Open Selected File")
        open_btn.clicked.connect(self.on_open_clicked)
        button_box.addButton(open_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_box.addButton(close_btn, QDialogButtonBox.ButtonRole.RejectRole)
        
        main_layout.addWidget(button_box)

        # Sorting controls
        sort_layout = QHBoxLayout()
        self.sort_by_name_btn = QPushButton("Sort by Name (Asc)")
        self.sort_by_name_btn.clicked.connect(self.on_sort_by_name)
        sort_layout.addWidget(self.sort_by_name_btn)
        self.sort_by_time_btn = QPushButton("Sort by Date Modified (Asc)")
        self.sort_by_time_btn.clicked.connect(self.on_sort_by_time)
        sort_layout.addWidget(self.sort_by_time_btn)
        main_layout.addLayout(sort_layout)

        # Sorting state
        self.sort_mode = 'name'  # or 'time'
        self.sort_ascending = True

        # Resize the filename column to fit the longest name after population
        self.tree_view.header().setSectionResizeMode(0, self.tree_view.header().ResizeToContents)
        self.tree_view.header().setSectionResizeMode(1, self.tree_view.header().ResizeToContents)
        self.tree_view.header().setSectionResizeMode(2, self.tree_view.header().ResizeToContents)
        self.tree_view.header().setSectionResizeMode(3, self.tree_view.header().ResizeToContents)
        self.tree_view.expanded.connect(self._on_item_expanded)
        self.tree_view.expanded.connect(lambda _index: self._watch_timer.start())
        self.tree_view.collapsed.connect(lambda _index: self._watch_timer.start())
        self.tree_view.collapsed.connect(lambda idx: self._fitNameColumn())

        # Add search box and button
        search_layout = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search names...")
        search_layout.addWidget(self.search_box)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.search_box.returnPressed.connect(
            lambda: self.search_btn.click() if self.search_box.text().strip() else None
        )
        search_layout.addWidget(self.search_btn)
        self.cancel_search_btn = QPushButton("Clear")
        self.cancel_search_btn.clicked.connect(self.on_cancel_search_clicked)
        search_layout.addWidget(self.cancel_search_btn)
        main_layout.addLayout(search_layout)

        if self.sidebar:
            self._arrangeAsSidebar(main_layout, button_box, sort_layout, search_layout)

        # Enable drag from tree view
        self.tree_view.setDragEnabled(True)
        self.tree_view.viewport().setAcceptDrops(False)
        self.tree_view.setSelectionMode(self.tree_view.SelectionMode.SingleSelection)
        # Install event filter for custom drag logic
        self.tree_view.viewport().installEventFilter(self)

        # "Remove from Workspace" on the workspace folders, "Add a Folder" elsewhere
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._showContextMenu)
        # follow the workspace folder the user works in
        self.tree_view.selectionModel().currentChanged.connect(self._onCurrentChanged)

    def _buildEmptyState(self) -> QWidget:
        """Message shown when the workspace has no folder."""
        empty_state = QWidget(self)
        layout = QVBoxLayout(empty_state)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(10)
        icon_label = QLabel(empty_state)
        icon_label.setPixmap(theme.icon('folder-open').pixmap(QSize(48, 48), self.devicePixelRatioF()))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        message = QLabel("The workspace is empty.\n"
                         "Add one or more folders from your computer to the workspace.", empty_state)
        message.setProperty('muted', True)
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        add_button = QPushButton("Add a Folder", empty_state)
        add_button.clicked.connect(self.addFolderRequested)
        layout.addWidget(add_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        empty_state.hide()
        return empty_state

    def _updateEmptyState(self):
        empty = not self.workspace_folders
        self.tree_view.setVisible(not empty)
        self.empty_state.setVisible(empty)
    


    def _arrangeAsSidebar(self, main_layout, button_box, sort_layout, search_layout):
        """
        Re-arrange the widgets for the side panel (Composer "My Projects"):
        a search field with icon buttons above a name-only tree.
        """
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.path_label.hide()
        button_box.hide()
        for layout in (sort_layout, search_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
            main_layout.removeItem(layout)

        # Search row
        search_row = QHBoxLayout()
        search_row.setContentsMargins(8, 8, 8, 8)
        search_row.setSpacing(2)
        self.search_box.setPlaceholderText("Search")
        self.search_box.addAction(theme.icon('search'), QLineEdit.ActionPosition.LeadingPosition)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.show()
        self.search_box.textChanged.connect(
            lambda text: self.on_cancel_search_clicked() if not text.strip() else None)
        search_row.addWidget(self.search_box, 1)

        self.sort_by_name_btn = self._sidebarButton('sort-alpha-asc', "Sort by name (click again to reverse)",
                                                    self.on_sort_by_name)
        self.sort_by_time_btn = self._sidebarButton('clock-o', "Sort by date modified (click again to reverse)",
                                                    self.on_sort_by_time)
        rescan_btn = self._sidebarButton('refresh', "Rescan the workspace", self.on_rescan_clicked)
        self.hidden_btn = self._sidebarButton('eye-slash', "Show the hidden folders (their name starts with a dot)",
                                              lambda checked: self.setShowHidden(checked), checkable=True)
        self.hidden_btn.setChecked(self.show_hidden)
        self.showHiddenChanged.connect(self.hidden_btn.setChecked)
        self.follow_btn = self._sidebarButton('crosshairs', "Select the open document in the list",
                                              lambda checked: self.setFollowDocument(checked), checkable=True)
        self.follow_btn.setChecked(self.follow_document)
        self.followDocumentChanged.connect(self.follow_btn.setChecked)
        for button in (self.sort_by_name_btn, self.sort_by_time_btn, rescan_btn):
            search_row.addWidget(button)
        main_layout.insertLayout(0, search_row)

        # "+ Add a Folder" link (Composer: "+ Open a Project")
        add_folder_row = QHBoxLayout()
        add_folder_row.setContentsMargins(10, 0, 8, 4)
        self.add_folder_link = QPushButton("Add a Folder", self)
        self.add_folder_link.setIcon(theme.icon('add'))
        self.add_folder_link.setIconSize(QSize(12, 12))
        self.add_folder_link.setToolTip("Add a folder to the workspace")
        self.add_folder_link.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.setButtonRole(self.add_folder_link, 'link')
        self.add_folder_link.clicked.connect(self.addFolderRequested)
        add_folder_row.addWidget(self.add_folder_link)
        add_folder_row.addStretch(1)
        # the settings of the list, here where there is room (the search field needs the width above)
        add_folder_row.addWidget(self.hidden_btn)
        add_folder_row.addWidget(self.follow_btn)
        main_layout.insertLayout(1, add_folder_row)

        self.tree_view.setHeaderHidden(True)
        self.tree_view.setAlternatingRowColors(False)
        self.tree_view.setIconSize(QSize(16, 16))
        self.tree_view.setIndentation(14)
        self.tree_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree_view.setItemDelegateForColumn(0, SidebarItemDelegate(self.tree_view))
        self._applyColumnMode()

    def _sidebarButton(self, glyph, tooltip, handler, checkable=False) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(theme.icon(glyph))
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        button.clicked.connect(handler)
        return button

    def _applyColumnMode(self):
        """In the side panel only the name column is shown."""
        if not getattr(self, 'sidebar', False):
            return
        for column in (1, 2, 3):
            self.tree_view.setColumnHidden(column, True)
        self.tree_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def eventFilter(self, source, event):
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        # Custom drag logic: only allow files to be dragged
        if source == self.tree_view.viewport():
            # The viewport tracks the mouse (hover highlighting), so MouseMove
            # also arrives without a button pressed: only start a drag once the
            # left button is held and the mouse moved past the drag distance.
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = event.position().toPoint()
            elif event.type() == event.Type.MouseButtonRelease:
                self._drag_start_pos = None
        start_pos = getattr(self, '_drag_start_pos', None)
        if source == self.tree_view.viewport() and event.type() == event.Type.MouseMove \
                and event.buttons() & Qt.MouseButton.LeftButton and start_pos is not None \
                and (event.position().toPoint() - start_pos).manhattanLength() >= QApplication.startDragDistance():
            self._drag_start_pos = None
            index = self.tree_view.indexAt(start_pos)
            item = self.model.itemFromIndex(index)
            if item:
                path = item.data(ROLE_PATH)
                if path and os.path.isfile(path):
                    from PyQt6.QtCore import QMimeData, QUrl
                    from PyQt6.QtGui import QDrag
                    mime_data = QMimeData()
                    mime_data.setUrls([QUrl.fromLocalFile(path)])
                    drag = QDrag(self.tree_view)
                    drag.setMimeData(mime_data)
                    drag.exec(Qt.DropAction.CopyAction)
                    return True
        return super().eventFilter(source, event)

  



    def _showContextMenu(self, position):
        menu = self._contextMenu(self.tree_view.indexAt(position))
        if menu is not None:
            menu.exec(self.tree_view.viewport().mapToGlobal(position))
            menu.deleteLater()

    def _contextMenu(self, index):
        """
        Context menu of a tree entry (Composer): "Remove from Workspace" on a
        workspace folder, "Add a Folder..." on the empty area.
        """
        folder = None
        if index.isValid():
            folder = self._folderOfRoot(index) if not index.parent().isValid() else None
            if folder is None:
                return None
        menu = QMenu(self)
        if folder is None:
            add_action = menu.addAction("Add a Folder...")
            add_action.triggered.connect(self.addFolderRequested)
        else:
            remove_action = menu.addAction("Remove from Workspace")
            remove_action.setToolTip(folder)
            remove_action.triggered.connect(lambda _checked=False, f=folder: self.removeFolderRequested.emit(f))
        return menu

    def _folderOfRoot(self, index):
        """The workspace folder whose root contains ``index`` (None for placeholders)."""
        if not index.isValid():
            return None
        while index.parent().isValid():
            index = index.parent()
        folder = index.siblingAtColumn(0).data(ROLE_PATH)
        return folder if folder in self.workspace_folders else None

    def _onCurrentChanged(self, current, _previous):
        if self._revealing:
            # only navigation: where new files go stays as it is
            return
        folder = self._folderOfRoot(current)
        if folder is not None:
            self.currentFolderChanged.emit(folder)

    def revealFile(self, file_path, clear_search: bool = True, allow_hidden: bool = True) -> bool:
        """
        Select a file in the tree and scroll to it, expanding the folders on the
        way (folders are loaded when they are expanded). A search in progress is
        cleared, so that the file is not hidden by it (unless ``clear_search`` is
        False: then a file that the search hides is not shown). A file in a hidden
        folder turns on "show hidden folders" (unless ``allow_hidden`` is False: then
        it is not shown). This is navigation only: it does not change the current
        workspace folder.

        Returns:
            True if the file is shown; False if it does not exist, is not inside a
            workspace folder, or is not listed by the tree (only .cwl, .json and
            .yaml files outside the ignored folders are).
        """
        try:
            target = Path(file_path).resolve()
        except (OSError, RuntimeError, ValueError, TypeError):
            return False
        if not target.is_file():
            return False
        located = self._locate(target)
        if located is None:
            return False
        searching = bool(self._search_text or self._showing_search)
        if searching and clear_search:
            self.on_cancel_search_clicked()
            searching = False
        # (while the search results are shown, only a file they list can be shown)
        if not searching and not self.show_hidden and any(part.startswith('.') for part in located[1].parts[:-1]):
            if not allow_hidden:
                return False
            self.setShowHidden(True)
        index = self._indexOfPath(str(target), expand=True)
        if index is None:
            return False
        if self._selectedPath() == index.siblingAtColumn(0).data(ROLE_PATH):
            self.tree_view.scrollTo(index, QTreeView.ScrollHint.EnsureVisible)
            return True
        self._revealing = True
        try:
            self.tree_view.setCurrentIndex(index)
            self.tree_view.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)
        finally:
            self._revealing = False
        return True

    def _locate(self, target: Path):
        """(workspace folder as listed, path of ``target`` inside it) or None."""
        for folder in self.workspace_folders:
            try:
                return Path(folder), target.relative_to(Path(folder).resolve())
            except ValueError:
                continue
        return None

    def _indexOfPath(self, path, expand: bool):
        """
        The index of the entry of a file or folder of the workspace, or None. With
        ``expand`` the folders on the way are expanded (and loaded); without it
        only entries that are already shown are found.
        """
        try:
            located = self._locate(Path(path).resolve())
        except (OSError, RuntimeError, ValueError, TypeError):
            return None
        if located is None:
            return None
        root, relative = located
        index = self._childByName(QModelIndex(), root.name, str(root))
        for part in relative.parts:
            if index is None:
                return None
            if expand:
                self.tree_view.expand(index)    # loads the folder if it was not yet
            elif not self.tree_view.isExpanded(index):
                return None
            index = self._childByName(index, part)
        return index

    def _childByName(self, parent_index, name, path=None):
        """
        The index of the child of ``parent_index`` with this file name (the top
        level entry of the workspace folder ``path``), or None. Names are
        compared ignoring the case when none matches exactly, as file systems
        of macOS and Windows do.
        """
        fallback = None
        for row in range(self.model.rowCount(parent_index)):
            index = self.model.index(row, 0, parent_index)
            entry = index.data(ROLE_PATH)
            if entry is None:
                continue
            if path is not None:
                if entry == path:
                    return index
                continue
            entry_name = Path(entry).name
            if entry_name == name:
                return index
            if fallback is None and entry_name.casefold() == name.casefold():
                fallback = index
        return fallback

    def showFolder(self, folder):
        """Select the root of a workspace folder and scroll to it."""
        for row in range(self.model.rowCount()):
            index = self.model.index(row, 0)
            if index.data(ROLE_PATH) == str(folder):
                self.tree_view.setCurrentIndex(index)
                self.tree_view.scrollTo(index, QTreeView.ScrollHint.PositionAtTop)
                return

    def _rootLabels(self) -> dict:
        """Root names: the folder name, with its parent when two folders share a name."""
        names = Counter(Path(folder).name for folder in self.workspace_folders)
        labels = {}
        for folder in self.workspace_folders:
            path = Path(folder)
            label = path.name or str(path)
            if names[path.name] > 1:
                label = f"{label}  \u2014  {path.parent.name or str(path.parent)}"
            labels[folder] = label
        return labels

    def _makeRootRow(self, root_path: Path, label: str) -> list:
        """The row of a workspace folder at the top level of the tree."""
        root_item = QStandardItem(label)
        root_item.setToolTip(str(root_path))
        root_mtime = root_path.stat().st_mtime if root_path.exists() else None
        root_item.setData(str(root_path), ROLE_PATH)
        root_item.setData(True, ROLE_IS_DIRECTORY)
        root_item.setData(False, ROLE_IS_LOADED)
        return [root_item, QStandardItem(""), QStandardItem(""), QStandardItem(self._format_mtime(root_mtime))]

    def _resetModel(self):
        self.model.clear()
        self.model.setHorizontalHeaderLabels(['Name', 'Version', 'Format', 'Date Modified'])
        self.path_label.setText(f"Workspace: {', '.join(self.workspace_folders) or 'Not set'}")

    def _expandedPaths(self, parent_index=QModelIndex(), paths=None) -> set:
        """Paths of the expanded entries of the tree."""
        paths = set() if paths is None else paths
        for row in range(self.model.rowCount(parent_index)):
            index = self.model.index(row, 0, parent_index)
            if self.tree_view.isExpanded(index):
                paths.add(index.data(ROLE_PATH))
                self._expandedPaths(index, paths)
        return paths

    def _restoreExpansion(self, expanded, parent_index):
        """Expand the sub-folders that were expanded before the tree was rebuilt."""
        for row in range(self.model.rowCount(parent_index)):
            index = self.model.index(row, 0, parent_index)
            if index.data(ROLE_PATH) in expanded:
                self.tree_view.expand(index)   # loads the folder (lazy loading)
                self._restoreExpansion(expanded, index)

    def populate_tree(self, path=None):
        """
        Populate the tree with a root for each workspace folder and its
        immediate children. Uses lazy loading - subdirectories are loaded
        when expanded. Folders that were expanded stay expanded; new
        workspace folders are expanded.
        
        Args:
            path (str | list, optional): Workspace folder(s) to show instead of
                the current ones
        """
        if path is not None:
            self.workspace_folders = self._folderList(path)
        self.logger.debug(f"Populating tree with files from {', '.join(self.workspace_folders)}")
        if self._showing_search:
            expanded = self._full_tree_expanded or set()
            self._showing_search = False
        else:
            expanded = self._expandedPaths()
        known_roots = set(self._shown_roots)
        self._resetModel()
        labels = self._rootLabels()
        for folder in self.workspace_folders:
            root_path = Path(folder)
            row = self._makeRootRow(root_path, labels[folder])
            root_item = row[0]
            self.model.appendRow(row)
            
            # Load the root directory's immediate children
            self._load_directory_children(root_item, root_path)
            root_item.setData(True, ROLE_IS_LOADED)
            
            root_index = self.model.indexFromItem(root_item)
            if folder not in known_roots or folder in expanded:
                self.tree_view.expand(root_index)
                self._restoreExpansion(expanded, root_index)
        self._shown_roots = list(self.workspace_folders)
        self._fitNameColumn()
        self._applyColumnMode()
        self._updateEmptyState()
        self._watch_timer.start()
    
    # -- changes on disk ---------------------------------------------------------------------------------
    def _syncWatches(self):
        """Watch the workspace folders and the folders that are expanded: the tree follows files added or removed."""
        wanted = [folder for folder in self.workspace_folders if os.path.isdir(folder)]
        expanded = sorted(path for path in self._expandedPaths()
                          if path and path not in wanted and os.path.isdir(path))
        wanted = (wanted + expanded)[:MAX_WATCHED_FOLDERS]
        watched = set(self._watcher.directories())
        stale = list(watched - set(wanted))
        if stale:
            self._watcher.removePaths(stale)
        new = [path for path in wanted if path not in watched]
        if new:
            self._watcher.addPaths(new)

    def _onFolderChanged(self, _path):
        # a burst of changes (a tool writing its outputs) gives one refresh
        self._refresh_timer.start()
    
    def _fitNameColumn(self):
        """
        Size the name column to its contents. The side panel does not need it (the
        column stretches), and measuring every row after each folder that is
        expanded made expanding a large workspace take many seconds.
        """
        if not self.sidebar:
            self.tree_view.resizeColumnToContents(0)

    def _on_item_expanded(self, index):
        """
        Handle expansion of a tree item. Lazy loads children if not already loaded.
        
        Args:
            index (QModelIndex): Index of the expanded item.
        """
        item = self.model.itemFromIndex(index)
        if item and item.data(ROLE_IS_DIRECTORY) and not item.data(ROLE_IS_LOADED):
            # Remove placeholder and load actual children
            path = Path(item.data(ROLE_PATH))
            self.logger.debug(f"Lazy loading directory: {path}")
            
            # Show busy cursor during loading
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                # Clear placeholder children
                item.removeRows(0, item.rowCount())
                self._load_directory_children(item, path)
                item.setData(True, ROLE_IS_LOADED)
            finally:
                QApplication.restoreOverrideCursor()
        
        self._fitNameColumn()
    
    def _isListedFolder(self, name: str) -> bool:
        """False for the folders the tree never lists (see IGNORED_FOLDERS) and, unless asked for, hidden ones."""
        return name not in IGNORED_FOLDERS and (self.show_hidden or not name.startswith('.'))

    def _load_directory_children(self, parent_item, dir_path):
        """
        Load the immediate children of a directory into the tree.
        Adds placeholder children to subdirectories for lazy loading.
        
        Args:
            parent_item (QStandardItem): The parent item in the tree.
            dir_path (Path): Path to the directory to load.
        """
        directories = []
        files = []
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir():
                            # only folders that hold documents are listed
                            if self._isListedFolder(entry.name) and self._hasCwlFiles(entry.path):
                                directories.append(entry)
                        elif entry.is_file() and os.path.splitext(entry.name)[1] in CWL_SUFFIXES:
                            files.append(entry)
                    except OSError as e:
                        self.logger.warning(f"Error accessing {entry.path}: {e}")
        except PermissionError as e:
            self.logger.warning(f"Permission denied accessing {dir_path}: {e}")
            return
        except OSError as e:
            self.logger.warning(f"Error accessing {dir_path}: {e}")
            return

        def sort_key(entry):
            return entry.name.lower() if self.sort_mode == 'name' else entry.stat().st_mtime

        directories.sort(key=sort_key, reverse=not self.sort_ascending)
        files.sort(key=sort_key, reverse=not self.sort_ascending)

        # Add directories with placeholder children for lazy loading
        for entry in directories:
            dir_item = QStandardItem(entry.name)
            dir_date_item = QStandardItem(self._format_mtime(self._mtime(entry)))
            dir_item.setData(entry.path, ROLE_PATH)
            dir_item.setData(True, ROLE_IS_DIRECTORY)
            dir_item.setData(False, ROLE_IS_LOADED)
            
            # Add a placeholder child so the expand arrow appears
            placeholder = QStandardItem("Loading...")
            dir_item.appendRow([placeholder, QStandardItem(""), QStandardItem(""), QStandardItem("")])
            
            parent_item.appendRow([dir_item, QStandardItem(""), QStandardItem(""), dir_date_item])
        
        # Add files
        for entry in files:
            try:
                c, cwl_version, file_format = self._cachedMetadata(entry.path, entry.stat())
                self._add_file_item(parent_item, Path(entry.path), c, cwl_version, file_format,
                                    mtime=self._mtime(entry))
            except Exception as e:
                self.logger.warning(f"Error parsing file {entry.path}: {e}")

    @staticmethod
    def _mtime(entry):
        try:
            return entry.stat().st_mtime
        except OSError:
            return None

    def _cachedMetadata(self, path, stat=None):
        """getDocumentMetadata() of a file, read again only when the file changed."""
        path = str(path)
        stat = stat or os.stat(path)
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self._metadata_cache.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
        metadata = self.getDocumentMetadata(path)
        self._metadata_cache[path] = (key, metadata)
        return metadata

    def _hasCwlFiles(self, dir_path: str) -> bool:
        """
        Whether a directory or the folders below it hold any document. The answer
        is kept until the tree is rebuilt; folders that are not listed are skipped.
        """
        known = self._cwl_folders.get(dir_path)
        if known is not None:
            return known
        found = False
        subfolders = []
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_file() and os.path.splitext(entry.name)[1] in CWL_SUFFIXES:
                        found = True
                        break
                    # symbolic links are not followed: a link to a parent folder would never end
                    if entry.is_dir(follow_symlinks=False) and self._isListedFolder(entry.name):
                        subfolders.append(entry.path)
        except OSError:
            found = False
        if not found:
            found = any(self._hasCwlFiles(folder) for folder in subfolders)
        self._cwl_folders[dir_path] = found
        return found

    def _directory_has_cwl_files(self, dir_path):
        """Check if a directory or its subdirectories contain any relevant files (.cwl, .json or .yaml)."""
        return self._hasCwlFiles(str(dir_path))

    def _add_file_item(self, parent_item, file_path, class_, cwl_version=None, file_format=None, mtime=None):
        """
        Add a file item to the tree.
        
        Args:
            parent_item (QStandardItem): The parent item in the tree.
            file_path (Path): Path to the file.
            class_ (str): The CWL class of the file (CommandLineTool, ExpressionTool, Workflow).
            cwl_version (str, optional): CWL version detected from file metadata.
            file_format (str, optional): File format ('JSON' or 'YAML').
        """
        file_item = QStandardItem(file_path.name)
        file_item.setData(str(file_path), ROLE_PATH)
        file_item.setData(False, ROLE_IS_DIRECTORY)
        tooltip = str(file_path)
        if class_:
            tooltip += f"\nClass: {class_}"
        if cwl_version:
            tooltip += f"\nCWL Version: {cwl_version}"
        file_item.setToolTip(tooltip)
        file_mtime = mtime if mtime is not None else (file_path.stat().st_mtime if file_path.exists() else None)
        file_date_item = QStandardItem(self._format_mtime(file_mtime))
        version_item = self._make_version_item(cwl_version)
        format_item = QStandardItem(file_format or "")
        
        # Set the tool icon for the file
        icon_key = {'CommandLineTool': 'tool', 'ExpressionTool': 'expressiontool',
                    'Workflow': 'workflow'}.get(class_)
        if icon_key:
            file_item.setIcon(theme.icon(icon_key))
            
        parent_item.appendRow([file_item, version_item, format_item, file_date_item])
    
    
    
    def add_file_to_tree(self, file_path, root_path, dir_nodes, class_, cwl_version=None, file_format=None):
        """
        Add a file to the tree view, creating directory nodes as needed.
        
        Args:
            file_path (Path): Path to the file
            root_path (Path): Root workspace path
            dir_nodes (dict): Dictionary mapping directory paths to tree nodes
        """
        # Get the relative path from the workspace root
        rel_path = file_path.relative_to(root_path)
        
        # Current parent is the root node
        current_path = root_path
        parent_item = dir_nodes[str(root_path)]
        
        # Create directory nodes along the path if they don't exist
        for part in rel_path.parts[:-1]:  # All parts except the filename
            current_path = current_path / part
            if str(current_path) not in dir_nodes:
                # Create a new directory node
                dir_item = QStandardItem(part)
                dir_mtime = current_path.stat().st_mtime if current_path.exists() else None
                dir_date_item = QStandardItem(self._format_mtime(dir_mtime))
                dir_item.setData(str(current_path), ROLE_PATH)
                parent_item.appendRow([dir_item, QStandardItem(""), QStandardItem(""), dir_date_item])
                dir_nodes[str(current_path)] = dir_item
            
            # Move to the next parent
            parent_item = dir_nodes[str(current_path)]
        
        # Add the file as a leaf node with an icon
        file_item = QStandardItem(rel_path.name)
        file_item.setData(str(file_path), ROLE_PATH)
        file_item.setToolTip(str(file_path))
        file_mtime = file_path.stat().st_mtime if file_path.exists() else None
        file_date_item = QStandardItem(self._format_mtime(file_mtime))
        
        # Set the tool icon for the file
        icon_key = {'CommandLineTool': 'tool', 'ExpressionTool': 'expressiontool',
                    'Workflow': 'workflow'}.get(class_)
        if icon_key:
            file_item.setIcon(theme.icon(icon_key))
            
        version_item = self._make_version_item(cwl_version)
        format_item = QStandardItem(file_format or "")
        parent_item.appendRow([file_item, version_item, format_item, file_date_item])

    def _make_version_item(self, cwl_version):
        """Build the CWL Version cell with icon fallback to text."""
        version_item = QStandardItem("")
        if not cwl_version:
            return version_item

        iconv_path = data.configuration.get('icons', {}).get(cwl_version)
        if iconv_path and os.path.exists(iconv_path):
            version_item.setIcon(QIcon(iconv_path))
            version_item.setToolTip(cwl_version)
        else:
            version_item.setText(cwl_version)
            version_item.setToolTip(cwl_version)

        return version_item

    def _format_mtime(self, mtime):
        """
        Format a modification time (timestamp) as a string.

        Args:
            mtime (float or None): Modification time as a Unix timestamp.

        Returns:
            str: Formatted date string, or empty string if mtime is None.
        """
        if mtime is None:
            return ""
        import datetime
        dt = datetime.datetime.fromtimestamp(mtime)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    def on_item_double_clicked(self, index):
        """
        Handle double-click on a tree item. Emits the fileSelected signal if a file is selected.

        Args:
            index (QModelIndex): Index of the clicked item.
        """
        item = self.model.itemFromIndex(index)
        if item:
            path = item.data(ROLE_PATH)
            if path and os.path.isfile(path):
                self.logger.debug(f"File selected: {path}")
                self.fileSelected.emit(path)
                # self.close()
    
    def on_open_clicked(self):
        """
        Handle click on the Open button. Emits the fileSelected signal if a file is selected.
        """
        selected_indexes = self.tree_view.selectedIndexes()
        if selected_indexes:
            item = self.model.itemFromIndex(selected_indexes[0])
            path = item.data(ROLE_PATH)
            if path and os.path.isfile(path):
                self.logger.debug(f"Opening file: {path}")
                self.fileSelected.emit(path)
                # self.close()
    
    def on_rescan_clicked(self):
        """
        Handle click on the Rescan button by refreshing the file tree.
        """
        if self.workspace_folders:
            self.logger.debug(f"Rescanning workspace: {', '.join(self.workspace_folders)}")
            self.refresh()
        else:
            self.logger.warning("Cannot rescan - no workspace path set")

    def on_sort_by_name(self):
        """
        Sort the tree view by file/directory name, toggling ascending/descending order.
        """
        self.sort_mode = 'name'
        self.sort_ascending = not self.sort_ascending
        order = "Asc" if self.sort_ascending else "Desc"
        self.sort_by_name_btn.setText(f"Sort by Name ({order})")
        self.sort_by_time_btn.setText(
            "Sort by Date Modified (Asc)" if self.sort_mode != 'time' else self.sort_by_time_btn.text()
        )
        if self.workspace_folders:
            self.refresh()

    def on_sort_by_time(self):
        """
        Sort the tree view by date modified, toggling ascending/descending order.
        """
        self.sort_mode = 'time'
        self.sort_ascending = not self.sort_ascending
        order = "Asc" if self.sort_ascending else "Desc"
        self.sort_by_time_btn.setText(f"Sort by Date Modified ({order})")
        self.sort_by_name_btn.setText(
            "Sort by Name (Asc)" if self.sort_mode != 'name' else self.sort_by_name_btn.text()
        )
        if self.workspace_folders:
            self.refresh()

    def on_treeview_section_clicked(self, logicalIndex):
        """
        Handle sorting when a column header is clicked.

        Args:
            logicalIndex (int): 0 for Name, 1 for Version, 2 for Format, 3 for Date Modified.
        """
        # Toggle sort order if the same column is clicked again
        if logicalIndex == 0:
            self.on_sort_by_name()
        elif logicalIndex == 3:
            self.on_sort_by_time()

    def on_search_clicked(self):
        """
        Handle click on the Search button. Filters the tree view by the search string.
        """
        search_text = self.search_box.text().strip().lower()
        if not search_text:
            # Show all items
            self._search_text = ""
            if self.workspace_folders:
                self.populate_tree()
            return
        # Filter items by search text
        self._search_text = search_text
        self.filter_tree_by_name(search_text)

    def on_cancel_search_clicked(self):
        """
        Handle click on the Cancel button. Clears the search box and shows all files.
        """
        self._search_text = ""
        self.search_box.clear()
        if self.workspace_folders:
            self.populate_tree()

    def filter_tree_by_name(self, search_text):
        """
        Filter the tree view to show only items matching the search string,
        in every workspace folder. Folders without a match are left out.
        Note: Search does a full scan and doesn't use lazy loading.

        Args:
            search_text (str): The string to search for in file and directory names.
        """
        if not self._showing_search:
            # remember the expanded folders to restore them after the search
            self._full_tree_expanded = self._expandedPaths()
            self._showing_search = True
        self._resetModel()
        labels = self._rootLabels()
        for folder in self.workspace_folders:
            row = self._makeRootRow(Path(folder), labels[folder])
            self._filter_folder(row[0], Path(folder), search_text)
            row[0].setData(True, ROLE_IS_LOADED)   # the results are not lazily loaded
            if row[0].rowCount():
                self.model.appendRow(row)
                self.tree_view.expand(self.model.indexFromItem(row[0]))
        if self.model.rowCount() == 0 and self.workspace_folders:
            no_results = QStandardItem(f"No search results for \u201c{self.search_box.text().strip() or search_text}.\u201d")
            no_results.setFlags(Qt.ItemFlag.NoItemFlags)
            no_results.setForeground(QColor(theme.TEXT_MUTED))
            self.model.appendRow(no_results)
        self._fitNameColumn()
        self._applyColumnMode()
        self._updateEmptyState()

    def _filter_folder(self, root_item, root_path, search_text):
        """Add the entries of a workspace folder matching the search string under its root item."""
        dir_nodes = {str(root_path): root_item}
        # Gather all files and directories (the folders that are not listed are not searched)
        all_files = []
        all_dirs = set()
        for current, folders, names in os.walk(root_path):
            folders[:] = [name for name in folders if self._isListedFolder(name)]
            for name in names:
                if os.path.splitext(name)[1] in CWL_SUFFIXES:
                    file_path = Path(current) / name
                    all_files.append(file_path)
                    for parent in file_path.parents:
                        if parent != root_path and str(parent).startswith(str(root_path)):
                            all_dirs.add(parent)
        # Sort directories
        sorted_dirs = sorted(all_dirs, key=lambda d: str(d).lower(), reverse=not self.sort_ascending)
        # Add matching directories
        for dir_path in sorted_dirs:
            rel_path = dir_path.relative_to(root_path)
            current_path = root_path
            parent_item = dir_nodes[str(root_path)]
            for part in rel_path.parts:
                current_path = current_path / part
                if str(current_path) not in dir_nodes:
                    if search_text in part.lower():
                        dir_item = QStandardItem(part)
                        dir_mtime = current_path.stat().st_mtime if current_path.exists() else None
                        dir_date_item = QStandardItem(self._format_mtime(dir_mtime))
                        dir_item.setData(str(current_path), ROLE_PATH)
                        parent_item.appendRow([dir_item, QStandardItem(""), QStandardItem(""), dir_date_item])
                        dir_nodes[str(current_path)] = dir_item
                    else:
                        dir_nodes[str(current_path)] = parent_item
                parent_item = dir_nodes[str(current_path)]
        # Sort files
        if self.sort_mode == 'name':
            all_files.sort(key=lambda f: f.name.lower(), reverse=not self.sort_ascending)
        else:
            all_files.sort(key=lambda f: f.stat().st_mtime, reverse=not self.sort_ascending)
        # Add matching files
        for file_path in all_files:
            if search_text in file_path.name.lower():
                try:
                    c, cwl_version, file_format = self._cachedMetadata(file_path)
                    self.add_file_to_tree(file_path, root_path, dir_nodes, c, cwl_version, file_format)
                except Exception as e:
                    self.logger.warning(f"Error parsing file: {e}")

    def getDocumentMetadata(self, file_path):
        """
        Lightweight metadata scan to detect document class and CWL version.

        Returns:
            tuple[str|None, str|None, str]: (class, cwl_version, file_format)
        """
        valid_classes = {'CommandLineTool', 'ExpressionTool', 'Workflow'}
        class_ = None
        cwl_version = None
        ext = Path(file_path).suffix.lower()
        file_format = 'JSON' if ext == '.json' else 'YAML'

        class_pattern = re.compile(r'^\s*["\']?class["\']?\s*:\s*["\']?([A-Za-z]+)["\']?')
        version_pattern = re.compile(r'^\s*["\']?cwlVersion["\']?\s*:\s*["\']?([^"\'\s#,]+)["\']?')

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if class_ is None:
                        class_match = class_pattern.search(line)
                        if class_match:
                            candidate = class_match.group(1)
                            if candidate in valid_classes:
                                class_ = candidate

                    if cwl_version is None:
                        version_match = version_pattern.search(line)
                        if version_match:
                            cwl_version = version_match.group(1)

                    if class_ is not None and cwl_version is not None:
                        break
        except Exception as e:
            self.logger.error(f"Error reading file {file_path}: {e}")

        return class_, cwl_version, file_format

    def getDocumentClass(self, file_path):
        """
        Scan a file for a line matching 'class: <value>' where value is CommandLineTool, ExpressionTool, or Workflow.
        Returns the value if found, else None.

        Args:
            file_path (str or Path): Path to the file to scan.

        Returns:
            str or None: The class value if found, otherwise None.
        """
        class_, _, _ = self.getDocumentMetadata(file_path)
        return class_


