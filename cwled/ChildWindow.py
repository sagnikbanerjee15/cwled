from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QObject, QPoint
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, 
    QWidget, QStatusBar, QToolBar,
    QComboBox, QLineEdit, QLabel, QPushButton,
    QFileDialog,
    QMessageBox,
    QAbstractScrollArea,
    QTextEdit,
    QPlainTextEdit
)
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QFontMetrics
from pathlib import Path, PurePath
from CWLparser import Parser
import json
from ruamel.yaml import YAML
import builtins
import data
import theme
import logging
import sys
import subprocess
import traceback
from TabInfoWindow import InfoWindow
from TabCodeEditor import CodeWindow
from TabToolEditor import ToolEditor
from TabSummary import WorkflowSummary
from CWLtoolFactory import CWLRunner
from widgets.qButtons import ErrorDialog
from TabWorkflowEditor import WorkflowEditor
from TabCommandLine import CommandLine
from cwl_utils.parser import save
from typing import Union, Any, List
import threading
import time
import tempfile
import os
from io import StringIO
from cwl_utils_handler import get_cwl_module, get_cwl_version
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from urllib.parse import urlparse
from copy import deepcopy
from ports import PortSplitter
from gitVersion import GitVersion
from LLM import Troubleshoot, TroubleshootResponseDialog
from BaseDialog import BaseDialog
import uuid
import shutil
import hashlib
logger = logging.getLogger(__name__)

# Global watchdog observer shared across windows to ensure all handlers
# receive the same events even when watching the same directories/files.
_GLOBAL_OBSERVER = None
_GLOBAL_OBSERVER_LOCK = threading.Lock()

# Track file paths saved internally by any ChildWindow so that other
# windows (e.g. workflows) can auto-reload silently instead of prompting.
_INTERNAL_SAVES: dict[str, float] = {}
_INTERNAL_SAVES_LOCK = threading.Lock()

def _mark_internal_save(path: str, seconds: float = 3.0) -> None:
    """Record that a file was saved internally by the application."""
    norm = str(Path(path).resolve())
    expiry = time.monotonic() + max(0.1, seconds)
    with _INTERNAL_SAVES_LOCK:
        _INTERNAL_SAVES[norm] = expiry

def _is_internal_save(path: str) -> bool:
    """Return True if *path* was recently saved by another ChildWindow."""
    now = time.monotonic()
    norm = str(Path(path).resolve())
    with _INTERNAL_SAVES_LOCK:
        expired = [p for p, t in _INTERNAL_SAVES.items() if t < now]
        for p in expired:
            _INTERNAL_SAVES.pop(p, None)
        expiry = _INTERNAL_SAVES.get(norm)
        return bool(expiry and expiry >= now)

def _get_global_observer() -> Observer:
    """Get or create the global file system observer.
    
    Returns a singleton Observer instance that is shared across all
    ChildWindow instances to monitor file system changes. This ensures
    all windows receive the same file system events.
    
    Returns:
        Observer: The global watchdog Observer instance.
    """
    global _GLOBAL_OBSERVER
    with _GLOBAL_OBSERVER_LOCK:
        if _GLOBAL_OBSERVER is None:
            _GLOBAL_OBSERVER = Observer()
            _GLOBAL_OBSERVER.start()
        return _GLOBAL_OBSERVER

class FileChangeHandler(QObject, FileSystemEventHandler):
    """Watchdog event handler to react to external file changes.

    This class monitors file system events and emits signals when tracked
    files are modified, created, or moved. The signals are thread-safe and
    are delivered from the watchdog thread to the GUI thread.
    
    Attributes:
        fileChanged: Signal emitted when a tracked file changes (str path).
    """
    # Signal emitted from watchdog thread; delivered to GUI thread (queued)
    fileChanged = pyqtSignal(str)

    def __init__(self, path: Union[List, str], parent: "ChildWindow") -> None:
        """Initialize the file change handler.
        
        Args:
            path: Path or list of paths to monitor for changes.
            parent: The ChildWindow instance that owns this handler.
        """
        QObject.__init__(self)
        FileSystemEventHandler.__init__(self)
        # Parse uris that start with file://
        
        # Normalize to a set of absolute file paths
        if isinstance(path, (list, tuple, set)):
            uris=[ urlparse(x).path for x in path ]
            
            self._targets = {str(Path(p).resolve()) for p in uris}
        else:
            uri=urlparse(path).path 
            self._targets = {str(Path(uri).resolve())}
        # Keep a weak-ish reference to the window
        # (do not use as QObject parent across threads)
        # print(f"Monitoring {self._targets}")
        self.window = parent

    def _is_target(self, event_path: str) -> bool:
        """Check if an event path matches one of the tracked files.
        
        Args:
            event_path: The file path from the file system event.
            
        Returns:
            bool: True if the path matches a tracked file, False otherwise.
        """
        try:
            return str(Path(event_path).resolve()) in self._targets
        except Exception:
            return False

    def promptReload(self, path: str) -> None:
        """Queue a reload prompt in the GUI thread by emitting a signal.
        
        This method is thread-safe and should be called from the watchdog
        worker thread. It emits a signal that will be processed in the
        GUI thread.
        
        Args:
            path: The file path that changed.
        """
        # Never touch Qt widgets here; this runs in watchdog's worker thread
        self.fileChanged.emit(path)

    # React when the file content is modified
    def on_modified(self, event):  # type: ignore[override]
        """Handle file modification events.
        
        Args:
            event: The file system event from watchdog.
        """
        if getattr(event, "is_directory", False):
            return
        path = getattr(event, "src_path", "")
        if self._is_target(path):
            msg = f"File changed: {path}"
            if hasattr(self.window, "logger") and self.window.logger:
                self.window.logger.info(f"\u2139 {msg}")
            # Drop events caused by our own save
            try:
                if hasattr(self.window, 'shouldIgnoreFileChange') and self.window.shouldIgnoreFileChange(path):
                    if hasattr(self.window, "logger") and self.window.logger:
                        self.window.logger.debug(f"Suppressed change event: {path}")
                    return
            except Exception:
                pass
            self.promptReload(path)

    # Handle file creations (some editors write new file and then move)
    def on_created(self, event):  # type: ignore[override]
        """Handle file creation events.
        
        Some editors create a new file before moving it to replace the
        original, so this handler captures those events.
        
        Args:
            event: The file system event from watchdog.
        """
        if getattr(event, "is_directory", False):
            return
        path = getattr(event, "src_path", "")
        if self._is_target(path):
            if hasattr(self.window, "logger") and self.window.logger:
                self.window.logger.info(f"\u2139 File created: {path}")
            try:
                if hasattr(self.window, 'shouldIgnoreFileChange') and self.window.shouldIgnoreFileChange(path):
                    if hasattr(self.window, "logger") and self.window.logger:
                        self.window.logger.debug(f"Suppressed create event: {path}")
                    return
            except Exception:
                pass
            self.promptReload(path)

    # Also handle file moves (some editors write via rename)
    def on_moved(self, event):  # type: ignore[override]
        """Handle file move/rename events.
        
        Many editors save files by writing to a temporary file and then
        atomically moving it to the target location. This handler captures
        those events.
        
        Args:
            event: The file system event from watchdog.
        """
        if getattr(event, "is_directory", False):
            return
        # A move could affect the target if the src was the file being watched
        src = getattr(event, "src_path", "")
        dest = getattr(event, "dest_path", "")
        matched_src = self._is_target(src)
        matched_dest = bool(dest) and self._is_target(dest)
        if matched_src or matched_dest:
            msg = f"File moved (changed): {src} -> {dest}"
            if hasattr(self.window, "logger") and self.window.logger:
                self.window.logger.info(f"\u2139 {msg}")
            # Prefer destination when it matches (common in atomic save)
            target = dest if matched_dest else src
            try:
                if hasattr(self.window, 'shouldIgnoreFileChange') and self.window.shouldIgnoreFileChange(target):
                    if hasattr(self.window, "logger") and self.window.logger:
                        self.window.logger.debug(f"Suppressed move event: {target}")
                    return
            except Exception:
                pass
            self.promptReload(target)


class GitCommitDialog(BaseDialog):
    """Compact dialog to collect commit message and target branch."""

    def __init__(
        self,
        branches: List[str],
        current_branch: str = None,
        default_message: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Git Commit")

        main_layout = QVBoxLayout(self)

        branch_label = QLabel("Branch", self)
        self.branch_combo = QComboBox(self)
        self.branch_combo.addItems(branches or [])
        if current_branch and current_branch in branches:
            self.branch_combo.setCurrentText(current_branch)
        main_layout.addWidget(branch_label)
        main_layout.addWidget(self.branch_combo)

        message_label = QLabel("Commit message", self)
        self.message_input = QLineEdit(self)
        self.message_input.setPlaceholderText("Describe your changes")
        self.message_input.setText(default_message or "")
        main_layout.addWidget(message_label)
        main_layout.addWidget(self.message_input)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        self.cancel_button = QPushButton("Cancel", self)
        self.commit_button = QPushButton("Commit", self)
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.commit_button)
        main_layout.addLayout(buttons_layout)

        self.cancel_button.clicked.connect(self.reject)
        self.commit_button.clicked.connect(self.accept)
        self.message_input.textChanged.connect(self._updateCommitButtonState)
        self._updateCommitButtonState()

    def _updateCommitButtonState(self) -> None:
        has_branch = self.branch_combo.count() > 0
        has_message = bool(self.message_input.text().strip())
        self.commit_button.setEnabled(has_branch and has_message)

    def getData(self) -> dict:
        """Return user-selected branch and commit message."""
        return {
            'branch': self.branch_combo.currentText().strip(),
            'message': self.message_input.text().strip(),
        }


class ChildWindow(QDialog):
    """
    Class for managing individual CWL document windows.
    
    This class represents a single window for editing a CWL document.
    It hosts all the tabs for different aspects of editing (info, code, tool-specific),
    and manages loading/saving of CWL files.
    
    Signals:
        menuActionSignal: Emitted when a menu action is triggered
        menuValidate: Emitted to trigger validation of the current CWL document
        menuUpgradeVersion: Emitted to upgrade the CWL version
        menuPackWorkflow: Emitted to pack a workflow
        menuMakeTemplate: Emitted to create a template from the CWL
        menuConfiguration: Emitted to open the configuration dialog
        updateMenuSignal: Emitted to update the window entry in the parent menu
        menuOpenFile: Received when a file should be opened
        menuSaveFile: Received when the document should be saved
        windowClosed: Emitted when the window is closed
    """
    menuActionSignal = pyqtSignal(str)
    menuValidate = pyqtSignal()
    menuUpgradeVersion = pyqtSignal(str)
    menuPackWorkflow = pyqtSignal(str)
    menuRestructureWorkflow = pyqtSignal(str)
    menuSaveDocumentation = pyqtSignal()
    menuMakeTemplate = pyqtSignal()
    menuTroubleshoot = pyqtSignal()  # Signal for troubleshooting
    menuConfiguration = pyqtSignal()  # Add a new signal for Configuration
    updateMenuSignal = pyqtSignal(int, str)  # send this signal to the main window 
    menuOpenFile = pyqtSignal(str)  # receive this signal when a file should be opened
    menuSaveFile = pyqtSignal(str, str)  # receive this signal when the document should be saved
    menuReloadFile = pyqtSignal()  # receive this signal when the file should be reloaded
    menuGitCommit = pyqtSignal()
    menuGitPush = pyqtSignal()
    menuGitPull = pyqtSignal()
    fileSaved = pyqtSignal(str)  # the document was written to this file (after Save, Save as...)
    windowClosed = pyqtSignal(int)  # signal to emit when window is closed, with window_id
    cwl_tool = None  # this is the cwl tool that we carry over in this window
    cwl_version=None # version of the tools
    file_path = None
    file_format = 'JSON'
    track_version = True # whether to track versions of the file (default from data.configuration.get('track_version'))
    hasChanged = False # to track if the file has been modified
    _saved_fingerprint = None # baseline fingerprint after load/save
    restructured_dir=None # remember the directory to store the restructured pipelines
    packed_dir=None # remember the directory to store packed pipelines
    _geometry_constrained_once = False

    def __init__(self, 
                 window_id: int = None, 
                 cwl_type: str = 'CommandLineTool', 
                 parent=None):
        """
        Initialize a new ChildWindow instance.
        
        Args:
            window_id (int, optional): Unique identifier for this window. Defaults to None.
            cwl_type (str, optional): Type of CWL document to create. Defaults to 'CommandLineTool'.
            parent (QWidget, optional): Parent widget. Defaults to None.
        """
        super().__init__(parent)
        # load the configuration
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        self.window_id = window_id
        self.parent_window = parent
        self.hasChanged = False
        self._saved_fingerprint = None
        self.logger.info(f"\u2139 Setting up {self.__class__.__name__}")
        self.logger.info(f"\u2139 Logging level set to {logging.getLevelName(self.logger.level)}")

        # Guard to suppress file change prompts caused by our own saves
        self._file_change_lock = threading.Lock()
        self._file_change_ignore = {}
        # Debounce repeated prompts per path (atomic saves fire multiple events)
        self._prompt_lock = threading.Lock()
        self._last_prompt = {}
        self._tab_change_guard = False
        self._previous_tab_index = 0
        self._tab_view_state = {}
        self._view_state_restore_guard = False
        
        # Configure the dialog properties
        self.setWindowModality(Qt.WindowModality.NonModal)  # Allow interaction with parent window
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowSystemMenuHint | 
                          Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)  # Make it function like a regular window
        
        # Set initial size from configuration with safe defaults
        self.resize(self._get_initial_window_size())
        
        self.hasChanged = False
        self.setup()
        self.menuActionSignal.connect(self.handle_menu_action)
        self.menuOpenFile.connect(self.onMenuOpenFile)
        self.menuSaveFile.connect(self.onMenuSaveFile)
        self.menuReloadFile.connect(self.onMenuReloadFile)
        self.menuGitCommit.connect(self.onToolbarGitCommit)
        self.menuGitPush.connect(self.onToolbarGitPush)
        self.menuGitPull.connect(self.onToolbarGitPull)
        self.menuValidate.connect(self.onMenuValidate)
        self.menuUpgradeVersion.connect(self.onMenuUpgradeVersion)
        self.menuPackWorkflow.connect(self.onMenuPackWorkflow)
        self.menuRestructureWorkflow.connect(self.onMenuRestructureWorkflow)
        self.menuSaveDocumentation.connect(self.onMenuSaveDocumentation)
        self.menuMakeTemplate.connect(self.onMenuMakeTemplate)
        self.menuTroubleshoot.connect(self.onMenuTroubleshoot)
        
        # Initialize a proper CWL object using cwl_utils 
        if not self.cwl_tool:
            p = Parser(cwl_type)
            self.cwl_tool = p.getCWL()
        self.setCWL( self.cwl_tool)
        self.cwl_type = self.cwl_tool.class_
        self.logger.info(f"\u2139 New ChildWindow with type {self.cwl_type}")
        self.track_version = data.configuration.get('track_version', False)
        # Create the basic layout and tabs initially
        self.initBasicUI() 
        
        # Set up type-specific tabs based on the current cwl_type
        self.setupTypeSpecificTabs()

    def _get_initial_window_size(self) -> QSize:
        """Return initial window size from configuration with safe defaults."""
        main_window_cfg = data.configuration.get('main_window', {}) if data.configuration else {}
        width = main_window_cfg.get('initial_width', 1200)
        height = main_window_cfg.get('initial_height', 900)

        try:
            width = int(width)
        except (TypeError, ValueError):
            width = 1200

        try:
            height = int(height)
        except (TypeError, ValueError):
            height = 900

        width = max(200, width)
        height = max(200, height)
        return QSize(width, height)

    def _get_target_screen_geometry(self):
        """Get available geometry for the most appropriate target screen."""
        screen = None

        if self.parent_window is not None:
            screen = self.parent_window.screen()

        if screen is None:
            screen = self.screen()

        if screen is None:
            screen = QApplication.primaryScreen()

        if screen is None:
            return None

        return screen.availableGeometry()

    def _constrain_geometry_to_screen(self, post_show: bool = False) -> None:
        """Clamp size and position to the target screen available geometry."""
        if not self.isWindow():
            # Embedded as a document tab of the main window
            return
        available = self._get_target_screen_geometry()
        if available is None:
            return

        max_ratio = 0.95
        max_width = max(200, int(available.width() * max_ratio))
        max_height = max(200, int(available.height() * max_ratio))

        if post_show:
            rect = self.frameGeometry()
        else:
            rect = self.geometry()

        width = min(max(rect.width(), 200), max_width)
        height = min(max(rect.height(), 200), max_height)

        x = rect.x()
        y = rect.y()

        min_x = available.x()
        min_y = available.y()
        max_x = available.x() + available.width() - width
        max_y = available.y() + available.height() - height

        x = min(max(x, min_x), max_x)
        y = min(max(y, min_y), max_y)

        if post_show:
            self.move(x, y)
            self.resize(width, height)
        else:
            self.setGeometry(x, y, width, height)

    def showEvent(self, event):
        """Ensure window geometry is constrained to the visible screen area."""
        super().showEvent(event)

        self._constrain_geometry_to_screen(post_show=False)

        if not self._geometry_constrained_once:
            self._geometry_constrained_once = True
            QTimer.singleShot(0, lambda: self._constrain_geometry_to_screen(post_show=True))

    def updateWindowTitle(self):
        """Update the title of the window.
        
        Uses either the file name, the tool id or the tool label to create
        a descriptive window title.
        """
        title = self.cwl_tool.label 
        if not title: 
            title = self.cwl_tool.id
        display_path = self.getDisplayFilePath()
        self.logger.debug(f"The new title contains cwl_type:{self.cwl_type}, title:{title}, path:{display_path}")
        
        # Add an asterisk to the title if there are unsaved changes
        changed_indicator = "*" if self.hasChanged else ""
        
        full_title=f"{changed_indicator}{title}: {display_path} ({self.cwl_version})"
        self.setWindowTitle(full_title)
        self.updateMenuSignal.emit(self.window_id, f"{self.cwl_type}: {title}")

    def _coerce_path_text(self, path_value: Any) -> str:
        """Normalize path/URI inputs (Path, bytes, str, None) to text."""
        if path_value is None:
            return ""
        if isinstance(path_value, bytes):
            return path_value.decode('utf-8', errors='ignore')
        if isinstance(path_value, os.PathLike):
            return os.fspath(path_value)
        return str(path_value)

    def _is_temporary_path(self, path_value: Any) -> bool:
        """Return True if the given path/URI points to an OS temporary directory."""
        path_text = self._coerce_path_text(path_value)
        if not path_text:
            return False
        try:
            parsed = urlparse(path_text)
            raw_path = parsed.path if parsed.scheme else path_text
            if not raw_path:
                return False
            p = Path(raw_path).expanduser()
            try:
                p = p.resolve()
            except Exception:
                pass
            temp_root = Path(tempfile.gettempdir())
            try:
                temp_root = temp_root.resolve()
            except Exception:
                pass
            return str(p).startswith(str(temp_root))
        except Exception:
            return False

    def _normalize_path_for_display(self, path_value: Any) -> str:
        """Convert file:// URIs to filesystem paths and keep plain paths unchanged."""
        path_text = self._coerce_path_text(path_value)
        if not path_text:
            return ""
        parsed = urlparse(path_text)
        if parsed.scheme == 'file':
            return parsed.path
        return path_text

    def setDiffStates(self, states: dict):
        """Mark the steps of the workflow that differ from another one in its graph (see TabDiff)."""
        editor = getattr(self, 'workflow_editor', None)
        if editor is not None:
            editor.graph.setDiffStates(states)

    def showStepInCode(self, step_id: str) -> bool:
        """Show the Code tab with the definition of a workflow step selected."""
        if not hasattr(self, 'code_editor'):
            return False
        self.tabs.setCurrentWidget(self.code_editor)
        # the tab change refreshes the code first
        QTimer.singleShot(0, lambda: not sip.isdeleted(self.code_editor) and self.code_editor.showStep(step_id))
        return True

    def workspaceDirectory(self):
        """
        The current workspace folder of the window that shows this document (a
        window that the tab was torn off into has a workspace of its own), or
        the one of the main window.
        """
        workspace = getattr(self.window(), 'workspace', None)
        current = workspace.currentFolder() if workspace is not None else None
        current = current or getattr(data, 'workspace_directory', None)
        return Path(current) if current else None

    def getDisplayFilePath(self) -> str:
        """Return a stable, user-facing path for titles; never show temp parser URIs."""
        current = self._normalize_path_for_display(self.file_path) if self.file_path else ""

        if current and not self._is_temporary_path(current):
            return current

        # Fallback to loadingOptions.fileuri only if it is non-temp
        if self.cwl_tool and hasattr(self.cwl_tool, 'loadingOptions'):
            lo_uri = getattr(self.cwl_tool.loadingOptions, 'fileuri', None)
            if isinstance(lo_uri, bytes):
                lo_uri = lo_uri.decode('utf-8')
            lo_uri = str(lo_uri) if lo_uri else ""
            lo_path = self._normalize_path_for_display(lo_uri)
            if lo_path and not self._is_temporary_path(lo_path):
                return lo_path

        return "<unsaved>"


    def handle_menu_action(self, action_name):
        """
        Handle menu actions received from the parent window.
        
        Args:
            action_name (str): The name of the action to handle.
        """
        self.logger.debug(f'Received {action_name}')

    def keyPressEvent(self, event):
        """Override to ignore Escape key presses."""
        if event.key() == Qt.Key.Key_Escape:
            # Ignore the Escape key - don't close the window
            event.ignore()
            return
        
        # Let the parent handle all other key events normally
        super().keyPressEvent(event)

    def onMenuReloadFile(self):
        """
        Handle request to reload the file from disk.
        
        Prompts the user for confirmation before reloading.
        """
        if not self.file_path:
            QMessageBox.warning(self, "No File", "No file is currently open to reload.")
            return
        
        # Get filename for display
        filename = Path(self.file_path).name
        
        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Reload File",
            f"Do you want to reload the file '{filename}' and overwrite all changes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.logger.info(f"Reloading file: {self.file_path}")
            self.loadCWL()
            self.logger.info(f"File reloaded successfully")

    def onToolbarSave(self):
        """Save from toolbar, reusing existing save behavior."""
        if self.file_path:
            self.onMenuSaveFile(str(self.file_path), self.file_format)
            return

        home_dir = str(self.workspaceDirectory() or Path.home())

        filters = "YAML (*.cwl);;YAML (*.yaml);;JSON (*.cwl);;JSON (*.json)"
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save As",
            home_dir,
            filters
        )
        if not file_path:
            return

        selected_format = 'YAML'
        selected_filter_upper = (selected_filter or '').upper()
        suffix = Path(file_path).suffix.lower()

        if 'JSON' in selected_filter_upper or suffix == '.json':
            selected_format = 'JSON'
        elif 'YAML' in selected_filter_upper or suffix in ['.yaml', '.yml']:
            selected_format = 'YAML'

        self.file_format = selected_format
        self.onMenuSaveFile(file_path, selected_format)

        if data.configuration_manager:
            data.configuration_manager.addRecentFile(file_path)

    def onToolbarRepackage(self):
        """Trigger repackage workflow action from toolbar."""
        if self.cwl_type != 'Workflow':
            return
        self.onMenuRestructureWorkflow(None)

    def onToolbarReload(self):
        """Trigger reload action from toolbar."""
        self.onMenuReloadFile()

    def _showPlannedGitCommand(self, command_title: str, command: str):
        """Show placeholder dialog for a git command planned for future implementation."""
        QMessageBox.information(
            self,
            command_title,
            "Git functionality is not implemented yet.\n\n"
            f"Will execute:\n{command}"
        )

    def onToolbarGitCommit(self):
        """Commit only the current document to a selected branch."""
        # Ensure the document has a path first.
        if not self.file_path:
            self.onToolbarSave()
            if not self.file_path:
                return

        # Commit should always use latest on-disk content.
        if self.hasChanged:
            self.onMenuSaveFile(str(self.file_path), self.file_format)
            if self.hasChanged:
                QMessageBox.warning(
                    self,
                    "Git Commit",
                    "Could not save all current changes before commit."
                )
                return

        default_message = ""
        try:
            if hasattr(self, 'info_window') and hasattr(self.info_window, 'git_commit_message'):
                default_message = self.info_window.git_commit_message.text().strip()
        except Exception:
            default_message = ""

        version = GitVersion(self.file_path)
        branch_info = version.listLocalBranches()
        branches = branch_info.get('branches', [])
        current_branch = branch_info.get('current_branch', None)

        if not branches:
            QMessageBox.warning(
                self,
                "Git Commit",
                "No local branches found in this repository.\n"
                "Create an initial commit/branch first, then retry."
            )
            return

        dialog = GitCommitDialog(
            branches=branches,
            current_branch=current_branch,
            default_message=default_message,
            parent=self,
        )
        dialog.show_next_to_main_window()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        form_data = dialog.getData()
        selected_branch = form_data.get('branch', '')
        commit_message = form_data.get('message', '')

        try:
            result = version.commitFileToBranch(
                branch_name=selected_branch,
                commit_message=commit_message,
            )
            short_hash = result.get('commit', '')[:12]
            QMessageBox.information(
                self,
                "Git Commit",
                "Commit created successfully.\n\n"
                f"Branch: {result.get('branch', '')}\n"
                f"File: {result.get('file', '')}\n"
                f"Commit: {short_hash}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Git Commit Failed",
                str(e)
            )

    def onToolbarGitPush(self):
        """Push the current branch to its default remote."""
        target_path = self.file_path
        if not target_path and self.workspaceDirectory():
            target_path = str(self.workspaceDirectory())

        version = GitVersion(target_path if target_path else "<unsaved>")
        try:
            result = version.pushCurrentBranch()
            details = (
                f"Branch: {result.get('branch', '')}\n"
                f"Remote: {result.get('remote', '')}"
            )
            summary = result.get('summary', '')
            if summary:
                details += f"\n\n{summary}"
            QMessageBox.information(self, "Git Push", f"Push completed successfully.\n\n{details}")
        except Exception as e:
            QMessageBox.critical(self, "Git Push Failed", str(e))

    def onToolbarGitPull(self):
        """Pull updates for the current branch from its default remote."""
        # Save before pull to avoid losing unsaved editor changes.
        if self.hasChanged and self.file_path:
            self.onMenuSaveFile(str(self.file_path), self.file_format)
            if self.hasChanged:
                QMessageBox.warning(
                    self,
                    "Git Pull",
                    "Could not save all current changes before pull."
                )
                return

        target_path = self.file_path
        if not target_path and self.workspaceDirectory():
            target_path = str(self.workspaceDirectory())

        version = GitVersion(target_path if target_path else "<unsaved>")
        try:
            result = version.pullCurrentBranch()
            details = (
                f"Branch: {result.get('branch', '')}\n"
                f"Remote: {result.get('remote', '')}"
            )
            summary = result.get('summary', '')
            if summary:
                details += f"\n\n{summary}"
            QMessageBox.information(self, "Git Pull", f"Pull completed successfully.\n\n{details}")
        except Exception as e:
            QMessageBox.critical(self, "Git Pull Failed", str(e))

    def _addToolbarAction(self, text: str, tooltip: str, handler, icon_key: str, fallback_key: str = None) -> QAction:
        """Create and add a toolbar action."""
        icon = theme.icon(icon_key, color=theme.TEXT)
        if icon.isNull() and fallback_key:
            icon = theme.icon(fallback_key, color=theme.TEXT)
        action = QAction(icon, text, self)
        action.setToolTip(tooltip)
        action.triggered.connect(handler)
        self.toolbar.addAction(action)
        return action

    def _setupToolbar(self):
        """Create and configure the top toolbar for common document actions."""
        self.toolbar = QToolBar("Document toolbar", self)
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(16, 16))

        self.toolbar_save_action = self._addToolbarAction(
            text="Save",
            tooltip="Save",
            handler=self.onToolbarSave,
            icon_key='save',
            fallback_key='edit'
        )
        self.toolbar_repackage_action = self._addToolbarAction(
            text="Repackage",
            tooltip="Repackage workflow with all tools",
            handler=self.onToolbarRepackage,
            icon_key='repackage',
            fallback_key='ai'
        )
        self.toolbar_reload_action = self._addToolbarAction(
            text="Reload",
            tooltip="Reload file",
            handler=self.onToolbarReload,
            icon_key='reload',
            fallback_key='downarrow'
        )
        self.toolbar_validate_action = self._addToolbarAction(
            text="Validate",
            tooltip="Validate tool/workflow",
            handler=self.onMenuValidate,
            icon_key='check-circle-o',
            fallback_key='programming'
        )

        self.toolbar.addSeparator()

        self.toolbar_git_commit_action = self._addToolbarAction(
            text="Git Commit",
            tooltip="Git commit",
            handler=self.menuGitCommit.emit,
            icon_key='gitcommit',
            fallback_key='add'
        )
        self.toolbar_git_push_action = self._addToolbarAction(
            text="Git Push",
            tooltip="Git push",
            handler=self.menuGitPush.emit,
            icon_key='gitpush',
            fallback_key='uparrow'
        )
        self.toolbar_git_pull_action = self._addToolbarAction(
            text="Git Pull",
            tooltip="Git pull",
            handler=self.menuGitPull.emit,
            icon_key='gitpull',
            fallback_key='downarrow'
        )

        self._git_toolbar_actions = [
            self.toolbar_git_commit_action,
            self.toolbar_git_push_action,
            self.toolbar_git_pull_action,
        ]
        self.updateGitToolbarActions()
        self.updateWorkflowToolbarActions()

    def updateGitToolbarActions(self):
        """Enable/disable git toolbar actions based on git tracking setting."""
        enabled = bool(self.track_version)
        for action in getattr(self, '_git_toolbar_actions', []):
            action.setEnabled(enabled)

    def updateWorkflowToolbarActions(self):
        """Enable workflow-only toolbar actions only for Workflow documents."""
        is_workflow = self.cwl_type == 'Workflow'
        if hasattr(self, 'toolbar_repackage_action'):
            self.toolbar_repackage_action.setEnabled(is_workflow)

    def onMenuUpgradeVersion(self, version:str=None):
        """
        Handle request to upgrade the CWL version.
        
        This will upgrade the CWL document to a newer version of the specification.
        Currently not implemented.
        """
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            caption="Save Upgraded Tool/Workflow As",
            directory=str(Path( self.file_path).parent),
            filter="CWL Files (*.cwl);;JSON Files (*.json);;YAML Files (*.yaml)"
        )
        
        if not file_path:
            self.logger.info("\u26A0 User canceled file selection")
            return None
        
        self.packed_dir=str(Path(file_path).parent)

        try:
            factory=CWLRunner()
            upgraded_filename=  factory.upgrade( 
                toversion='v1.2',
                input_filename=self.file_path, 
                output_filename=file_path
            )
            QMessageBox.information(
                self,
                "Upgrade file success",
                f"The file for {self.cwl_tool.id} <br>saved in file {str(upgraded_filename)}"
            )
            
        except Exception as e:
            traceback.print_exc()
            self.logger.error(f"Unable to upgrade this file, {e}. {traceback()}")

        resolved_path = Path(upgraded_filename).resolve()
        return resolved_path


    def _temporary_filename(self):
        """
        produce a temporary a temporary filename that is based on the
        workflow or tool id.

        """
        # if we have a file_path for the current tool/workflow
        # the directory is the parent of that cwl object
        if self.file_path:
                default_dir = Path(self.file_path).parent
        elif self.workspaceDirectory():
                default_dir = self.workspaceDirectory()
        else:
                default_dir = Path.home()
        # add a random string at the end
        random_str=str(uuid.uuid4())[0:5]
        # default_dir=default_dir / random_str

        if self.cwl_tool and hasattr(self.cwl_tool, 'id') and self.cwl_tool.id:
            tool_id = self.cwl_tool.id
            # cwl_tool.id may be a URI (e.g. "file:///path/to/tool.cwl") or a plain id.
            # Strip any URI scheme and extract only the final path component stem
            # so the temporary filename stays a valid flat filename.
            from urllib.parse import urlparse
            parsed = urlparse(tool_id)
            if parsed.scheme:
                base_name = Path(parsed.path).stem or parsed.scheme
            else:
                # plain id: replace path separators to keep it safe
                base_name = tool_id.replace('/', '_').replace('\\', '_')
            default_name = base_name + random_str
        else:
            default_name = str(uuid.uuid4())[1:8]
        default_name=default_name + ".cwl"

        if not default_dir.is_dir():
            default_dir.mkdir(parents=True, exist_ok=True)

        return Path( default_dir / default_name)
        


    def onMenuPackWorkflow(self, output_filename:str=None):
        """
        Handle request to pack a workflow.
        Args:
            output_filename (str, optional): If provided, the path to save the packed workflow. 
                                             If None, a file dialog will be shown. Defaults to None.
        
        This will combine all the referenced workflow steps into a single document.
        Currently not implemented.
        """
        # self.logger.critical(f"onMenuPackWorkflow is not implemented yet")
        # we will run the command line from cwlrunner.pack in the config file
        if not self.cwl_tool or self.cwl_tool.class_ != 'Workflow':
            self.logger.error("Current document is not a workflow, cannot pack")
            QMessageBox.warning(self, "Warning", 
                                 "Current document is not a workflow, cannot pack")
            return None
        # if this is a new workflow or took ask for its name
        if not self.file_path:
            QMessageBox.warning(
                parent=self, 
                title="Save current object", 
                text="You need to store the CWL first to a file"
            )
            self.onMenuSaveFile()    
        # Show the save dialog to get the target file path 
        # to store the packed workflow 
        if output_filename:
            file_path = output_filename
        else:
            file_path, selected_filter = QFileDialog.getSaveFileName(
                self,
                caption="Save Packed Workflow As",
                directory=self.packed_dir if self.packed_dir else str(Path( self.file_path).parent),
                filter="CWL Files (*.cwl);;JSON Files (*.json);;YAML Files (*.yaml)"
            )
        if not file_path:
            self.logger.info("\u26A0 User canceled file selection")
            return None
        self.packed_dir=str(Path(file_path).parent)

        try:
            factory=CWLRunner()
            factory.packWorkflow( 
                existing_filename=self.file_path,
                filename=file_path
            )
            QMessageBox.information(
                self,
                "Packed file success",
                f"The pipeline {self.cwl_tool.id} <br>saved in file {str(file_path)}"
            )
        except Exception as e:
            self.logger.error(f"Unable to pack this workflow, {e}. {traceback()}")

        return Path(file_path).resolve()
            

    def onMenuRestructureWorkflow(self, output_filename:str=None):
        """
        Handle request to pack a workflow.
        
        This will combine all the referenced workflow steps into a single document.
        and all the steps as separate files under the .steps directory.
        """
        # make sure that we have a valid path for our pipeline
        if not self.file_path:
            self.onMenuSaveFile()

        # ask the user where to store the restructured workflow
        if output_filename:
            file_path = output_filename
        else:

            # Determine the default filename based on cwl_tool.id
            default_filename = f"{self.cwl_tool.id}.cwl" if self.cwl_tool and self.cwl_tool.id else "stage.cwl"
        

            file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            caption="Save Restructured Workflow As",
            directory=str(Path(self.restructured_dir) / default_filename) if self.restructured_dir else str(Path(self.file_path).parent / default_filename),
            filter="CWL Files (*.cwl);;JSON Files (*.json);;YAML Files (*.yaml)"
        )
        if not file_path:
            self.logger.info("\u26A0 User canceled file selection")
            return None
        self.restructured_dir=str(Path(file_path).parent)
        # we need to create a temporary directory that will store the
        # packed workflow, 
        # which will then be expanded.
        try:
            factory=CWLRunner()
            factory.stageWorkflow(
                target_filename=file_path,
                existing_filename=self.file_path
            )
            QMessageBox.information(
                self,
                "Staging workflow success",
                f"The pipeline {self.cwl_tool.id} <br>saved in file {str(file_path)}"
            )
        except Exception as e:
            self.logger.error(f"Unable to stage this workflow, {e}. {traceback()}")  
        


        return Path(file_path).resolve()
            

    def onMenuSaveDocumentation(self):
        """
        Handle request to save workflow documentation.
        """
        # Determine the default filename based on cwl_tool.id
        default_filename = f"{self.cwl_tool.id}.html" if self.cwl_tool and self.cwl_tool.id else "documentation.html"
        
        # Determine the directory to use
        if self.file_path:
            default_dir = str(Path(self.file_path).parent / default_filename)
        else:
            default_dir = default_filename
        
        # Ask the user where to save the documentation
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            caption="Save Workflow Documentation As",
            directory=default_dir,
            filter="HTML Files (*.html);;All Files (*)"
        )
        
        if not file_path:
            self.logger.info("\u26A0 User canceled file selection")
            return None
        if not self.cwl_tool:
            self.logger.error("\u274C No CWL tool loaded to export documentation")
            QMessageBox.warning(
                self,
                "No Documentation",
                "No CWL tool is loaded."
            )
            return None

        doc_text = getattr(self.cwl_tool, 'doc', None)
        if not doc_text:
            self.logger.warning("\u26A0 CWL tool has no documentation to export")
            QMessageBox.warning(
                self,
                "No Documentation",
                "This CWL document has no description text to export."
            )
            return None

        try:
            import base64
            import markdown2

            png_data_uri = ""
            if hasattr(self, 'workflow_editor') and self.workflow_editor:
                temp_png_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_png:
                        temp_png_path = temp_png.name

                    self.workflow_editor.onExportImage(temp_png_path)

                    if temp_png_path and Path(temp_png_path).exists():
                        with open(temp_png_path, 'rb') as png_file:
                            png_base64 = base64.b64encode(png_file.read()).decode('ascii')
                            png_data_uri = f"data:image/png;base64,{png_base64}"
                except Exception as png_error:
                    self.logger.warning(f"\u26A0 Could not export workflow PNG: {str(png_error)}")
                finally:
                    if temp_png_path:
                        try:
                            os.remove(temp_png_path)
                        except Exception:
                            pass

            html_body = markdown2.markdown(doc_text)
            graph_section = ""
            if png_data_uri:
                graph_section = (
                    "<section>\n"
                    "  <h1>Pipeline graph</h1>\n"
                    f"  <img src=\"{png_data_uri}\" alt=\"Pipeline graph\" style=\"width: 300ch; max-width: 100%; height: auto;\" />\n"
                    "</section>\n"
                )
            html_content = (
                "<!DOCTYPE html>\n"
                "<html lang=\"en\">\n"
                "<head>\n"
                "  <meta charset=\"utf-8\">\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
                f"  <title>{self.cwl_tool.id if self.cwl_tool.id else 'Documentation'}</title>\n"
                "  <style>\n"
                "    body { margin: 0; padding: 24px; }\n"
                "    section { padding: 12px 0; }\n"
                "    article { padding: 12px 0; }\n"
                "  </style>\n"
                "</head>\n"
                "<body>\n"
                f"{graph_section}"
                f"<article>{html_body}</article>\n"
                "</body>\n"
                "</html>\n"
            )

            with open(file_path, 'w', encoding='utf-8') as doc_file:
                doc_file.write(html_content)

            self.logger.info(f"\u2705 Documentation exported to {file_path}")
            QMessageBox.information(
                self,
                "Documentation Saved",
                f"Documentation saved as HTML in file {file_path}"
            )
            return Path(file_path).resolve()
        except Exception as e:
            self.logger.error(f"\u274C Failed to save documentation: {str(e)}", exc_info=True)
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Unable to save documentation to {file_path}.\n\n{str(e)}"
            )
            return None
        
    def onMenuMakeTemplate(self):
        """
        Handle request to create a template from the current CWL document.
        
        Generates an input template for the current CWL tool using cwltool's
        --make-template feature, then opens a dialog for the user to edit
        the template values before saving to a file.
        """
        
        self.logger.info("\u23F3 Creating template for current CWL document")
        
        if not self.cwl_tool:
            self.logger.error("\u274C No CWL tool loaded to create template from")
            return
        
        try:
            # Save current CWL to a string
            serialized = save(self.cwl_tool)
            if isinstance(serialized, bytes):
                cwl_content = serialized.decode('utf-8', errors='replace')
            elif isinstance(serialized, str):
                cwl_content = serialized
            else:
                cwl_content = json.dumps(serialized, indent=2)
            
            # Create a CWLRunner instance
            cwl_runner = CWLRunner()
            
            # Generate the template
            template_dict = cwl_runner.makeTemplate(
                cwl_content,
                source_path=str(self.file_path) if self.file_path else None
            )
            
            if template_dict is not None:
                # Convert dict to YAML
                from io import StringIO
                yaml = YAML()
                yaml_string = StringIO()
                yaml.dump(template_dict, yaml_string)
                template_yaml = yaml_string.getvalue()
                
                # Create and show the template editor dialog
                from TemplateEditorDialog import TemplateEditorDialog
                template_dialog = TemplateEditorDialog(template_yaml, self)
                
                if template_dialog.exec() == template_dialog.DialogCode.Accepted:
                    self.logger.info("\u2705 Template created and saved by user")
                else:
                    self.logger.info("\u274C Template editing canceled by user")
            else:
                self.logger.error("\u274C Failed to generate template")
                details = ""
                if hasattr(cwl_runner, 'stdout') and cwl_runner.stdout:
                    details += f"Stdout:\n{cwl_runner.stdout}\n\n"
                if hasattr(cwl_runner, 'stderr') and cwl_runner.stderr:
                    details += f"Stderr:\n{cwl_runner.stderr}"
                if details.strip():
                    error_dialog = ErrorDialog(
                        error_message="Failed to create template for this document.",
                        details=details.strip()
                    )
                    error_dialog.exec()
                
        except Exception as e:
            self.logger.error(f"\u274C Error creating template: {str(e)}", 
                             exc_info=True)
            error_dialog = ErrorDialog(
                error_message="Error creating template",
                details=str(e)
            )
            error_dialog.exec()
            

    def onMenuTroubleshoot(self):
        """
        Handle request to troubleshoot the current CWL document.
        
        Opens a dialog to get the issue description from the user,
        then uses the Troubleshoot class from LLM.py to generate
        troubleshooting guidance.
        """
        
        self.logger.info("\u23F3 Starting troubleshooting for current CWL document")
        
        if not self.cwl_tool:
            self.logger.error("\u274C No CWL tool loaded to troubleshoot")
            QMessageBox.warning(self, "No Document", "Please load a CWL document first.")
            return
        
        try:
            # Get the configured LLM model from configuration
            model = data.configuration.get('llm', {}).get('model', 'gemini-2.5-flash')
            
            # Run the troubleshooting workflow
            result = Troubleshoot.runTroubleshooting(
                cwl_tool=self.cwl_tool,
                parent_widget=self,
                model=model
            )
            
            if result:
                self.logger.info("\u2705 Troubleshooting guidance generated successfully")
                # Get the file path from cwl_tool
                file_path = ""
                if self.file_path:
                    file_path = str(self.file_path)
                elif hasattr(self.cwl_tool, 'loadingOptions') and hasattr(self.cwl_tool.loadingOptions, 'fileuri'):
                    file_uri = self.cwl_tool.loadingOptions.fileuri
                    file_path = urlparse(file_uri).path
                
                # Show the result in a scrollable dialog
                response_dialog = TroubleshootResponseDialog(
                    guidance_text=result['guidance'],
                    issue_description=result['issue_description'],
                    file_path=file_path,
                    parent=self
                )
                response_dialog.exec()
            else:
                self.logger.info("\u274C Troubleshooting cancelled by user")
                
        except Exception as e:
            self.logger.error(f"\u274C Error during troubleshooting: {str(e)}", 
                             exc_info=True)
            error_dialog = ErrorDialog(
                error_message="Error during troubleshooting",
                details=str(e)
            )
            error_dialog.exec()


    def onMenuValidate(self):
        """
        Validate a CWL tool or workflow using cwltool --validate.
        
        Uses the configured validation command from the application settings.
        Displays the validation results to the user.
        
        It stores a temporary file with the current CWL content
        """
        self.logger.info(f"Validating the tool using {data.configuration.get('cwl_runner').get('validate')}")
        if not self.cwl_tool:
            self.logger.warning("No CWL tool loaded, cannot validate")
            return None

        def _validation_yaml_text_from_editor() -> str:
            """Build YAML text for validation from the current code editor buffer."""
            if not hasattr(self, 'code_editor') or self.code_editor is None:
                raise Exception("Code editor is not available")

            text = self.code_editor.editor.text()
            current_format = getattr(self.code_editor, 'format', 'YAML')

            if current_format == 'YAML':
                return text

            if current_format == 'JSON':
                parsed = json.loads(text)
                yaml = YAML()
                yaml.preserve_quotes = False
                yaml.default_flow_style = False
                yaml.default_style = None
                yaml.width = 4096
                yaml_string = StringIO()
                yaml.dump(parsed, yaml_string)
                return yaml_string.getvalue()

            raise Exception(f"Unsupported code editor format for validation: {current_format}")
        
        temp_filename = None
        try:
            # first we need to store the current CWL to a temporary file
            temp_filename=self._temporary_filename()
            self.logger.debug(f"Saving to temporary file: {temp_filename}")
            yaml_text = _validation_yaml_text_from_editor()
            temp_filename.write_text(yaml_text, encoding='utf-8')
            self.logger.debug("Validation input written as YAML from current code editor buffer")
            
            # then run the validation command
            self.logger.debug("Creating CWLRunner instance")
            cwlRunner = CWLRunner()
            
            self.logger.info("Running validation...")
            is_valid = cwlRunner.validate(str(temp_filename))
            
            try:
                details = cwlRunner.stderr
            except Exception as e:
                self.logger.error(f"Error getting validation details: {e}")
                details = str(e)
                
            if not is_valid:
                self.logger.warning(f"\u26A0 This tool cannot be validated")
                self.logger.warning(f"\n{details}")    
                error_dialog = ErrorDialog(error_message="This tool cannot be validated",
                                         details=f"{details}")
                error_dialog.exec()
            else:
                self.logger.info("✓ Validation successful")
                QMessageBox.information(
                    self, 
                    "Validation Results", 
                    f"Validation for the tool {self.cwl_tool.id} was successful"
                )
        except Exception as e:
            self.logger.error(f"Error during validation: {e}", exc_info=True)
            error_dialog = ErrorDialog(
                error_message="Validation Error",
                details=f"An error occurred during validation:\n{str(e)}"
            )
            error_dialog.exec()
        finally:
            # Clean up temp file
            if temp_filename and temp_filename.exists():
                try:
                    temp_filename.unlink()
                    self.logger.debug(f"Cleaned up temporary file: {temp_filename}")
                except Exception as e:
                    self.logger.warning(f"Could not remove temporary file {temp_filename}: {e}")
    
    def onMenuOpenFile(self, filename):
        """
        Handle request to open a file.
        
        Args:
            filename (str): Path to the file to open.
        """
        self.file_path = filename
        self.file_format = self._detectFileFormat(filename)
        try:
            self.loadCWL()
        except Exception as e:
            self.logger.critical(f"Unable to load file\n{e}")

    def _detectFileFormat(self, filename: str) -> str:
        """Detect CWL file format as 'JSON' or 'YAML'."""
        try:
            path = Path(filename)
            suffix = path.suffix.lower()

            if suffix == '.json':
                return 'JSON'
            if suffix in ['.yaml', '.yml']:
                return 'YAML'

            # For .cwl (or unknown extension), sniff first non-empty content
            text = path.read_text(encoding='utf-8', errors='ignore')
            stripped = text.lstrip()
            if stripped.startswith('{'):
                return 'JSON'
        except Exception as e:
            self.logger.debug(f"Could not detect format for {filename}: {e}")

        return 'YAML'

    def _normalizeSaveFormat(self, format_value: str = None, filename: str = None) -> str:
        """Normalize user/config format values to canonical 'JSON' or 'YAML'."""
        if format_value:
            fmt = str(format_value).upper()
            if 'JSON' in fmt:
                return 'JSON'
            if 'YAML' in fmt:
                return 'YAML'

        if filename:
            return self._detectFileFormat(filename)

        if self.file_format:
            fmt = str(self.file_format).upper()
            if 'JSON' in fmt:
                return 'JSON'

        return 'YAML'
            

    def onMenuSaveFile(self, filename=None, format=None):
        """
        Handle request to save the current document.
        
        Args:
            filename (str, optional): Path where to save the file. 
                                    Defaults to None (use current file_path).
            format (str, optional): Format to save as ('JSON' or 'YAML'). 
                                   Defaults to None (use current file_format).
        """
        if not filename and not self.file_path:
            self.logger.warning(f"\u26A0 It was requested to store a file, but no name was provided.")
            return None
        if filename:
            self.file_path = filename

        effective_format = self._normalizeSaveFormat(format, self.file_path)
        self.file_format = effective_format
        version=GitVersion(self.file_path)
        version_id=version.createVersionTag()
        if hasattr(self.cwl_tool, 'id') and self.cwl_tool.id:
            version_id=f"{self.cwl_tool.id}/{version_id}"
            version.createVersionTag(version_id)

        # need to add the version_id inside the CWL document
        if self.track_version:
            self.addMetadata(namespace='sc',
                             namespace_uri='http://schema.org/',
                             key='version', 
                             value=version_id)
        self.saveFile(file_path=self.file_path, format=effective_format)
        self._mark_clean_snapshot()
        self.logger.info(f"\u2705 Saved to file {self.file_path} with format {self.file_format}")
        # create the new git tag 
        if self.track_version:
            version.createGitVersionCommit()
            self.logger.info(f"\u2705 Created git tag {version_id} for file {self.file_path} ")
            self.info_window.doc_version.setText(f"{version_id}")
            
            # Create modeless message box with Ok and Push buttons
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("Tagged file Saved")
            msg_box.setText(
                f"File <b>{Path(self.file_path).name}</b><br>"+
                f"saved as a git tag <b>{version_id}</b>.<br>"+
                f"You can either commit/push directly the main branch <br>"+
                f"Or push the specific tag"
            )
            ok_btn = msg_box.addButton("Ok", QMessageBox.ButtonRole.AcceptRole)
            push_btn = msg_box.addButton("Push Tag", QMessageBox.ButtonRole.ActionRole)
            msg_box.setWindowModality(Qt.WindowModality.NonModal)  # Makes it modeless
            
            # Handler for Push button click
            def handle_push_button():
                try:
                    result = version.pushTagToRemote(version_id)
                    msg_box.close()
                    QMessageBox.information(
                        self,
                        "Tag Pushed Successfully",
                        f"Tag: <b>{result['tag']}</b><br>" +
                        f"Remote: <b>{result['remote']}</b><br>" +
                        f"{result['summary']}"
                    )
                except RuntimeError as e:
                    msg_box.close()
                    QMessageBox.critical(
                        self,
                        "Push Failed",
                        f"Failed to push tag '{version_id}':<br>{str(e)}"
                    )
            
            push_btn.clicked.connect(handle_push_button)
            msg_box.show()  # Use show() instead of exec() for non-blocking
            # Auto-close after 5 seconds
            QTimer.singleShot(5000, msg_box.close)
            # Keep a reference to prevent garbage collection
            self._version_msg_box = msg_box

        self.updateWindowTitle()

    def addMetadata(self,  key: str, value: Any, namespace: str, namespace_uri: str=None):
        """Add metadata to the CWL document using namespaced keys.

        This method adds custom metadata to the CWL tool or workflow by
        storing it in the extension_fields. It ensures the required namespace
        is defined in the document's $namespaces section before adding
        the metadata.

        Metadata is useful for adding semantic annotations, provenance
        information, or other descriptive properties to CWL documents.
        Common namespaces include 'sc' (schema.org) and 'edam' (EDAM ontology).

        Args:
            key: The metadata key name (without namespace prefix).
                Example: 'author', 'license', 'description'
            value: The metadata value. Can be any type (str, list, dict, etc.)
            namespace: The namespace prefix to use.
                Example: 'sc' for schema.org, 'edam' for EDAM ontology
            namespace_uri: The full URI for the namespace. Required if the
                namespace is not already defined in the document.
                Example: 'https://schema.org/' for 'sc' namespace

        Returns:
            None

        Example:
            # Add author metadata using schema.org namespace
            window.addMetadata(
                key='author',
                value='John Doe',
                namespace='sc',
                namespace_uri='https://schema.org/'
            )

            # This adds: "sc:author": "John Doe" to extension_fields
            # and ensures $namespaces contains: sc: https://schema.org/
        """
        # check it the proper namespace exists
        if hasattr(self.cwl_tool.loadingOptions, 'namespaces') and \
            not namespace in self.cwl_tool.loadingOptions.namespaces :
            if not namespace_uri:
                self.logger.error(f"Cannot add metadata with namespace {namespace} without a proper URI")
                return
            self.cwl_tool.loadingOptions.namespaces[namespace]=namespace_uri
        # now that the namespace exists we add the key value pair
        # we make sure that the key is namespaced e.g. if the namespace is sc the key should be sc:key

        namespaced_key=f"{namespace}:{key}"
        self.cwl_tool.extension_fields[namespaced_key]=value


    def setup(self):
        """
        Set up basic metrics and configuration options.
        
        Uses configuration parameters when necessary.
        Sets up global values used by other components.
        """
        font_metrics = QFontMetrics(self.font())
        average_character_width = font_metrics.horizontalAdvance('M') 
        builtins.labelWidth = 20 * average_character_width

        builtins.main_window = self

        self.setWindowTitle(data.configuration.get('title'))
        self.resize(self._get_initial_window_size())

    def getCWL(self) -> dict:
        """
        Get the updated CWL dictionary.
        
        Returns:
            dict: The CWL dictionary that contains all information about 
                 the tool or workflow managed in this window.
        """
        return self.cwl_tool
    
    def setCWL(self, cwl_tool: Any=None):
        """Set the CWL tool/workflow object for this window.
        
        Updates the internal CWL object and extracts the CWL version.
        
        Args:
            cwl_tool: The CWL object (CommandLineTool, Workflow, etc.)
                     to associate with this window.
        """
        self.cwl_tool = cwl_tool
        # print(f"Setting CWL tool: {save(self.cwl_tool)}    "  )
        self.cwl_version = get_cwl_version(self.cwl_tool)
        # Keep file_path stable and user-facing; never adopt temporary parser URIs.
        try:
            if (not self.file_path) or self._is_temporary_path(str(self.file_path)):
                if self.cwl_tool and hasattr(self.cwl_tool, 'loadingOptions'):
                    lo_uri = getattr(self.cwl_tool.loadingOptions, 'fileuri', None)
                    if isinstance(lo_uri, bytes):
                        lo_uri = lo_uri.decode('utf-8')
                    lo_uri = str(lo_uri) if lo_uri else ""
                    candidate = self._normalize_path_for_display(lo_uri)
                    if candidate and not self._is_temporary_path(candidate):
                        self.file_path = candidate
        except Exception:
            pass

        # print(f"####################### \n################\nSetting CWL version: {self.cwl_version}    "  )

    def _serialize_cwl_for_fingerprint(self) -> str:
        """Return deterministic JSON text for robust CWL change detection."""
        try:
            serialized = save(self.cwl_tool)
            if isinstance(serialized, bytes):
                serialized = serialized.decode('utf-8', errors='replace')

            payload = json.loads(serialized) if isinstance(serialized, str) else serialized
            if isinstance(payload, dict):
                # equivalent forms are the same document: "echo" / ["echo"],
                # an empty list / no list at all
                payload = dict(payload)
                if isinstance(payload.get('baseCommand'), str):
                    payload['baseCommand'] = [payload['baseCommand']]
                for key in ('baseCommand', 'arguments', 'requirements', 'hints'):
                    if payload.get(key) in ([], None):
                        payload.pop(key, None)
            return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        except Exception as e:
            self.logger.debug(f"Fingerprint serialization fallback used due to: {e}")
            try:
                fallback = save(self.cwl_tool)
                if isinstance(fallback, bytes):
                    return fallback.decode('utf-8', errors='replace')
                return str(fallback)
            except Exception:
                return str(self.cwl_tool)

    def _compute_cwl_fingerprint(self) -> str:
        """Compute SHA-256 fingerprint for the current CWL object."""
        serialized = self._serialize_cwl_for_fingerprint()
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    def _mark_clean_snapshot(self) -> None:
        """Store current CWL as baseline and clear dirty state."""
        self._saved_fingerprint = self._compute_cwl_fingerprint()
        self.hasChanged = False

    def _refresh_dirty_state(self) -> bool:
        """Refresh dirty state from fingerprint comparison; return whether state toggled."""
        previous = bool(self.hasChanged)
        current = self._compute_cwl_fingerprint()

        if self._saved_fingerprint is None:
            self._saved_fingerprint = current
            self.hasChanged = False
        else:
            self.hasChanged = (current != self._saved_fingerprint)

        return previous != self.hasChanged

    def _tabStateKey(self, tab_widget: QWidget) -> str:
        """Build a stable key used for storing per-tab view state."""
        try:
            idx = self.tabs.indexOf(tab_widget) if hasattr(self, 'tabs') else -1
            label = self.tabs.tabText(idx) if idx >= 0 else tab_widget.__class__.__name__
            return f"tab:{label}"
        except Exception:
            return f"tab:{tab_widget.__class__.__name__}"

    def _captureGenericWidgetViewState(self, widget: QWidget) -> dict:
        """Capture generic scroll/cursor state for common Qt scrollable widgets."""
        state = {
            'scroll_areas': [],
            'text_edits': []
        }

        scroll_areas = widget.findChildren(QAbstractScrollArea)
        for area in scroll_areas:
            try:
                state['scroll_areas'].append({
                    'name': area.objectName(),
                    'class': area.__class__.__name__,
                    'v': area.verticalScrollBar().value() if area.verticalScrollBar() else 0,
                    'h': area.horizontalScrollBar().value() if area.horizontalScrollBar() else 0,
                })
            except Exception:
                continue

        text_edits = widget.findChildren(QTextEdit) + widget.findChildren(QPlainTextEdit)
        for edit in text_edits:
            try:
                state['text_edits'].append({
                    'name': edit.objectName(),
                    'class': edit.__class__.__name__,
                    'cursor_pos': edit.textCursor().position()
                })
            except Exception:
                continue

        return state

    def _restoreGenericWidgetViewState(self, widget: QWidget, state: dict) -> None:
        """Restore generic scroll/cursor state for common Qt scrollable widgets."""
        if not state:
            return

        scroll_areas = widget.findChildren(QAbstractScrollArea)
        for idx, saved in enumerate(state.get('scroll_areas', [])):
            if idx >= len(scroll_areas):
                break
            area = scroll_areas[idx]
            try:
                if area.verticalScrollBar():
                    v_max = area.verticalScrollBar().maximum()
                    area.verticalScrollBar().setValue(max(0, min(saved.get('v', 0), v_max)))
                if area.horizontalScrollBar():
                    h_max = area.horizontalScrollBar().maximum()
                    area.horizontalScrollBar().setValue(max(0, min(saved.get('h', 0), h_max)))
            except Exception:
                continue

        text_edits = widget.findChildren(QTextEdit) + widget.findChildren(QPlainTextEdit)
        for idx, saved in enumerate(state.get('text_edits', [])):
            if idx >= len(text_edits):
                break
            edit = text_edits[idx]
            try:
                cursor = edit.textCursor()
                max_pos = len(edit.toPlainText())
                cursor.setPosition(max(0, min(saved.get('cursor_pos', 0), max_pos)))
                edit.setTextCursor(cursor)
            except Exception:
                continue

    def _captureTabViewState(self, tab_widget: QWidget) -> None:
        """Capture and cache view state for one tab widget."""
        if not tab_widget or self._view_state_restore_guard:
            return

        key = self._tabStateKey(tab_widget)
        try:
            if hasattr(tab_widget, 'captureViewState'):
                self._tab_view_state[key] = tab_widget.captureViewState()
            else:
                self._tab_view_state[key] = self._captureGenericWidgetViewState(tab_widget)
        except Exception as e:
            self.logger.debug(f"View-state capture skipped for {key}: {e}")

    def _restoreTabViewState(self, tab_widget: QWidget) -> None:
        """Restore cached view state for one tab widget."""
        if not tab_widget:
            return

        key = self._tabStateKey(tab_widget)
        state = self._tab_view_state.get(key)
        if not state:
            return

        try:
            self._view_state_restore_guard = True
            if hasattr(tab_widget, 'restoreViewState'):
                tab_widget.restoreViewState(state)
            else:
                self._restoreGenericWidgetViewState(tab_widget, state)
        except Exception as e:
            self.logger.debug(f"View-state restore skipped for {key}: {e}")
        finally:
            self._view_state_restore_guard = False

    def _captureAllTabViewStates(self) -> None:
        """Capture view state for all currently visible tabs."""
        if not hasattr(self, 'tabs'):
            return
        for i in range(self.tabs.count()):
            self._captureTabViewState(self.tabs.widget(i))

    def _populateTabPreservingView(self, tab_widget: QWidget, populate_call) -> None:
        """Run a tab populate call while preserving its remembered view state."""
        self._captureTabViewState(tab_widget)
        populate_call()
        self._restoreTabViewState(tab_widget)
        

    def populateFromCWL(self):
        """
        Set the CWL content to all UI elements.
        
        Calls onUpdateCWL to update all components with the current CWL dictionary.
        Also updates the window title based on the CWL content.
        """
        self.onUpdateCWL(None)
        self.updateWindowTitle()
        
        # Build list of files to watch. Always include the current document.
        file_paths = []
        if self.file_path:
            try:
                file_paths.append(str(Path(self.file_path).resolve()))
            except Exception:
                file_paths.append(self.file_path)

        # For workflows, also watch referenced step tools.
        if self.cwl_tool.class_ == "Workflow":
            base_dir = Path(self.file_path).parent if self.file_path else Path.cwd()
            # print(f"The base dir is {base_dir}")
            for s in self.cwl_tool.steps:
                if hasattr(s, 'run') and isinstance(s.run, str):
                    # Support file:// URIs and relative paths
                    p=self.normalizePath(  s.run )
                    file_paths.append(str(p))
        if file_paths:
            self.trackFileChange(file_paths)
                   

    def onUpdateCWL(self, message=None):
        """
        Update all tabs with the current CWL dictionary.
        
        This slot is called every time the CWL needs to be updated in 
        the various tabs. If it receives "CWL editor updated" message,
        it will update the cwl_dict using the code editor's text first.
        
        Args:
            message (str, optional): A message indicating the source of the update.
        """
        self.logger.info(f"\u23F3 Checking if we need to update the CWL from the various tabs. "
                         f"Message: {message}")
        self._captureAllTabViewStates()

        # Retrieve the updated CWL from the corresponding Tab
        # the tab is determined by the message that is received
        if message:
            self.logger.info(f"\u23F3 {message}. Retrieving updated CWL from the corresponding tab")
        if message == "CWL editor updated" and hasattr(self, 'code_editor'):
            editor_CWL = self.code_editor.getCWL() # receive the updated CWL from the editor
            # self.logger.debug(f"Retrieved text from code editor: {len(save(editor_CWL))} characters")
            self.setCWL(editor_CWL)  # the CWL object now contains the new edited 
            self.logger.info("\u2705 CWL document updated from the code editor")
        # we need to update the CWL object in the info window and the code editor
        if message == "CWL app updated" and hasattr(self, 'app_editor'):
            tool_CWL = self.app_editor.getCWL() # receive the updated CWL from the editor
            # self.logger.debug(f"Retrieved text from code editor: {len(save(tool_CWL))} characters")
            self.setCWL(tool_CWL)  # the CWL object now contains the new edited 
            self.logger.info("\u2705 CWL document updated from the app editor")
        if message == "CWL info updated" and hasattr(self, 'info_window'):
            info_CWL = self.info_window.getCWL() # receive the updated CWL from the editor
            # self.logger.debug(f"Retrieved text from info editor: {len(save(info_CWL))} characters")
            self.setCWL(info_CWL ) # the CWL object now contains the new edited 
            self.logger.info("\u2705 CWL document updated from the info editor")
        if message == "CWL workflow updated" and hasattr(self, 'workflow_editor'):
            workflow_CWL = self.workflow_editor.getCWL() # receive the updated CWL from the editor
            # self.logger.debug(f"Retrieved text from info editor: {len(save(info_CWL))} characters")
            self.setCWL(workflow_CWL ) # the CWL object now contains the new edited 
            self.logger.info("\u2705 CWL document updated from workflow editor")
        # no need to check for summary window, it does not edit the CWL
        self.logger.info(f"\u2139 Updated CWL object for {self.cwl_tool.id} with version {self.cwl_tool.cwlVersion}")

        # Set the CWL to all the other tabs
        # Update the info window if it exists
        self.logger.info("\u23F3 Updating all tabs with the current CWL document")
        if hasattr(self, 'info_window'):
            self.info_window.setCWLTool(self.cwl_tool)
            self._populateTabPreservingView(self.info_window, self.info_window.populateFromCWL)
            self.logger.info(f"\t\u2705 Info window updated with {self.cwl_type} object")
        # Update the code editor if it exists
        if hasattr(self, 'code_editor'):
            self.code_editor.setCWLTool( self.cwl_tool)
            self._populateTabPreservingView(self.code_editor, self.code_editor.populateFromCWL)
            self.logger.info(f"\t\u2705 Code editor updated with {self.cwl_type} object")
        else:
            self.logger.warning("\u26A0 Code editor not initialized yet, skipping update")

        # Update the type-specific editor
        self.cwl_type = self.cwl_tool.class_
        self.updateWorkflowToolbarActions()
        if (self.cwl_type in ['ExpressionTool', 'CommandLineTool'] and 
            hasattr(self, 'app_editor')):
            self.app_editor.setCWLTool(self.cwl_tool)
            self._populateTabPreservingView(self.app_editor, self.app_editor.populateFromCWL)
            self.logger.info(f"\t\u2705 Tool editor updated with {self.cwl_type} object")
            # Update command line status bar if it exists and type is CommandLineTool
            if (self.cwl_type == 'CommandLineTool' and 
                hasattr(self, 'command_line') and 
                self.command_line):
                self.command_line.setCWLTool(self.cwl_tool)
                self._captureTabViewState(self.command_line)
                self.command_line.populateFromCWL()
                self._restoreTabViewState(self.command_line)
                self.command_line.setVisible(True)
                self.logger.info(f"\t\u2705 Command line box updated with {self.cwl_type} object")
        elif self.cwl_type == 'Workflow':
            # Hide command line if type is Workflow
            if (hasattr(self, 'command_line') and 
                self.command_line):
                self.command_line.setVisible(False)
            if hasattr(self, 'workflow_editor'):
                self.workflow_editor.setCWLWorkflow(self.cwl_tool)
                self._populateTabPreservingView(self.workflow_editor, self.workflow_editor.populateFromCWL)
                self.logger.info(f"\t\u2705 Workflow editor updated with {self.cwl_type} object")
            if hasattr(self, 'workflow_summary'):
                self.workflow_summary.setCWLWorkflow(self.cwl_tool)
                self._populateTabPreservingView(
                    self.workflow_summary,
                    lambda: self.workflow_summary.populateFromCWL(self.file_path if hasattr(self, 'file_path') else None)
                )
                self.logger.info(f"\t\u2705 Workflow summary updated with {self.cwl_type} object")

        # Dirty-state is content-based: compare current CWL fingerprint to baseline.
        dirty_state_changed = self._refresh_dirty_state()
        if message or dirty_state_changed:
            self.updateWindowTitle()
        

    def loadCWL(self):
        """
        Load the CWL from a file.
        
        Assumes that the self.file_path variable has been set.
        After successfully loading a CWL document, it calls populateFromCWL
        to update all UI components.
        """
        input_cwl = self.file_path
        if input_cwl:
            self.file_format = self._detectFileFormat(input_cwl)
        self.logger.info(f"\u23F3 Loading CWL from file: {input_cwl}")

        try:
            p = Parser(input_cwl)
            self.logger.info(f"\u23F3 Loading file {input_cwl}.")
            self.logger.debug(f"Got {json.dumps(p.getDict(), indent=3)}")
        except FileNotFoundError as e:
            self.logger.critical(f"\u274C File not found: {e}")
            traceback.print_exc()
            return
        try:
            self.setCWL( p.getCWL( ) )
            self._mark_clean_snapshot()
            
            # Check if the CWL type has changed and update tabs accordingly
            new_cwl_type = self.cwl_tool.class_
            if new_cwl_type and new_cwl_type != self.cwl_type:
                self.logger.info(f"CWL type changed from {self.cwl_type} to {new_cwl_type}")
                self.cwl_type = new_cwl_type
                # Update the tabs to match the new CWL type
                self.setupTypeSpecificTabs()
                
        except Exception as e:
            self.logger.critical(f"\u274C Unable to load the contents of file. {e}")
            traceback.print_exc()


        if self.cwl_tool.cwlVersion != 'v1.2':
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("CWL Version Notice")
            msg_box.setText(
                f"The loaded CWL document is version {self.cwl_tool.cwlVersion}. "
                "Consider upgrading to version v1.2 for the latest features and improvements."
            )
            upgrade_btn = msg_box.addButton("Upgrade to v1.2", QMessageBox.ButtonRole.AcceptRole)
            continue_btn = msg_box.addButton("Continue as is", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(continue_btn)
            msg_box.exec()
            
            if msg_box.clickedButton() == upgrade_btn:
                fp=self.onMenuUpgradeVersion()

                
                logger.debug(f"\u23F3 Loading upgraded CWL from file: {str(fp)}")
                self.file_path=str(fp)
                self.loadCWL()
                return


        try:
            self.populateFromCWL()
        except Exception as e:
            self.logger.critical(f"\u274C Unable to load CWL. {e}")


    def saveFile(self, file_path=None, format='YAML'):
        """
        Save the current CWL document to a file.
        
        Args:
            file_path (str, optional): Path where to save the file.
                                     Defaults to None (use current file_path).
            format (str, optional): Format to save as ('JSON' or 'YAML').
                                   Defaults to 'YAML'.
        """
        if file_path:
            if format:
                self.file_format = format
            # self.logger.critical("saveFile has not been updated")
            # sys.exit(23)
            self.logger.debug(f"File selected: {file_path}, with format {self.file_format}")
            # Suppress reload prompts for a short window around our own save
            try:
                self.suppressFileChangeFor(str(Path(file_path).resolve()), seconds=2.0)
            except Exception:
                pass

            parser=Parser(self.cwl_tool)
            format= format if format else self.file_format
            try:
                parser.saveFile( filename=file_path, format=format) 
          
                self.file_path = file_path
                self.logger.info(f"\u2705 CWL saved in {file_path}")
                self.fileSaved.emit(str(file_path))
            except Exception as e:
                self.logger.error(f"\u274C Unable to save the contents to file. {e}")
                
            # Suppress reload prompts for a short window after our own save
            try:
                self.suppressFileChangeFor(str(Path(file_path).resolve()), seconds=2.0)
            except Exception:
                # Best-effort; ignore if path resolution fails
                pass

            # Notify other windows (e.g. workflows) that this was an internal save
            # so they can auto-reload silently instead of prompting the user.
            try:
                _mark_internal_save(str(Path(file_path).resolve()), seconds=3.0)
            except Exception:
                pass

    def suppressFileChangeFor(self, path: str, seconds: float = 1.5) -> None:
        """Temporarily ignore external change events for a path.

        Used to prevent reload prompts for changes that we ourselves
        initiated (e.g., when saving a file).

        Args:
            path: Absolute file path to suppress events for.
            seconds: Duration to suppress (defaults to 1.5 seconds).
        """
        # Normalize path similarly to handler
        norm = str(Path(path).resolve())
        expiry = time.monotonic() + max(0.1, seconds)
        with self._file_change_lock:
            self._file_change_ignore[norm] = expiry

    def shouldIgnoreFileChange(self, path: str) -> bool:
        """Return True if a change for path should be ignored now.
        
        Checks if the path is in the suppression window (set by
        suppressFileChangeFor) and cleans up expired entries.
        
        Args:
            path: The file path to check.
            
        Returns:
            bool: True if events for this path should be ignored.
        """
        now = time.monotonic()
        norm = str(Path(path).resolve())
        with self._file_change_lock:
            # Cleanup expired entries
            expired = [p for p, t in self._file_change_ignore.items() if t < now]
            for p in expired:
                self._file_change_ignore.pop(p, None)
            expiry = self._file_change_ignore.get(norm)
            return bool(expiry and expiry >= now)

    def initBasicUI(self):
        """
        Initialize the basic UI elements common to all CWL types.
        
        Sets up the tab container but doesn't add type-specific tabs yet.
        Creates the Info and Code tabs that are common to all CWL documents.
        """
        # Create main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create tab widget for content. Like Composer's editor action bar,
        # the tabs sit on the left and the document actions on the right.
        self.tabs = QTabWidget()
        self.tabs.setObjectName('editorTabs')
        self.tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        main_layout.addWidget(self.tabs)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setMovable(False)

        # Create toolbar for common actions.
        self._setupToolbar()
        self.tabs.setCornerWidget(self.toolbar, Qt.Corner.TopRightCorner)
        
        # Create status bar area at the bottom, initially hidden
        self.command_line = None
        
        # Create and add info window for all CWL types
        self.info_window = InfoWindow(cwl_tool=self.cwl_tool, parent=self)
        self.tabs.addTab(self.info_window, 'App Info')
        
        # Create and add code editor for all CWL types
        self.code_editor = CodeWindow(cwl_tool=self.cwl_tool, parent=self)
        self.tabs.addTab(self.code_editor, 'Code')
        
        # Connect the codeUpdated signal from the code editor to onUpdateCWL
        self.code_editor.codeUpdated.connect(self.onUpdateCWL)
        
        self.info_window.codeUpdated.connect(self.onUpdateCWL)
        
        # Track tab switches so we can auto-apply Code edits before leaving the tab.
        self._previous_tab_index = self.tabs.currentIndex()
        self.tabs.currentChanged.connect(self.onTabChanged)
        
        # Set the layout
        self.setLayout(main_layout)

    def onTabChanged(self, index: int):
        """Handle tab switches and auto-apply pending Code editor changes."""
        if self._tab_change_guard:
            return

        previous_index = self._previous_tab_index
        code_tab_index = self.tabs.indexOf(self.code_editor) if hasattr(self, 'code_editor') else -1
        leaving_code_tab = (previous_index == code_tab_index and index != code_tab_index)

        try:
            if leaving_code_tab and hasattr(self, 'code_editor'):
                if self.code_editor.hasUnappliedChanges():
                    self.logger.info("Auto-applying pending Code tab changes before tab switch")
                    self.code_editor.applyEditorChanges(emit_signal=False)
                    self.onUpdateCWL("CWL editor updated")
                    self.logger.info("Code tab auto-apply succeeded")
                else:
                    self.onUpdateCWL(None)
            else:
                self.onUpdateCWL(None)

            self._previous_tab_index = index
        except Exception as e:
            self.logger.warning(f"Blocking tab change due to invalid Code editor content: {e}")
            self._tab_change_guard = True
            self.tabs.blockSignals(True)
            try:
                self.tabs.setCurrentIndex(previous_index)
            finally:
                self.tabs.blockSignals(False)
                self._tab_change_guard = False
            self._previous_tab_index = previous_index

    def setupTypeSpecificTabs(self):
        """
        Set up the tabs specific to the CWL document type.
        
        Called when the CWL type is known or changes.
        Adds/removes tabs based on whether the document is a CommandLineTool,
        ExpressionTool, or Workflow.
        """
        # Get the actual CWL type
        if hasattr(self.cwl_tool, 'class_'):
            self.cwl_type = self.cwl_tool.class_
            self.updateWorkflowToolbarActions()
            # self.logger.info(f"Setting up type-specific tabs for {self.cwl_type}")
        else:
            error = "The parsed CWL object does not have a class defined"
            raise Exception(error)
        
        # Check if we need to add or remove tabs based on CWL type
        has_app_tab = False
        has_workflow_tab = False
        
        # Check for existing tabs
        has_app_tab = hasattr(self, 'app_editor') and self.tabs.indexOf(self.app_editor) >= 0
        has_workflow_tab = hasattr(self, 'workflow_editor') and self.tabs.indexOf(self.workflow_editor) >= 0
                
        # Make command line visible or hidden based on CWL type
        if hasattr(self, 'command_line') and self.command_line:
            if self.cwl_type == 'CommandLineTool':
                self.command_line.setVisible(True)
                self.command_line.setCWLTool(self.cwl_tool)
                self.command_line.populateFromCWL()
            else:
                self.command_line.setVisible(False)
        
        # Add or remove tabs based on CWL type
        if self.cwl_type in ['CommandLineTool', 'ExpressionTool']:
            # Remove workflow tab if it exists
            if has_workflow_tab:
                self.tabs.removeTab(self.tabs.indexOf(self.workflow_editor))
                self.workflow_editor.deleteLater()
                delattr(self, 'workflow_editor')
                if hasattr(self, 'workflow_summary'):
                    if self.tabs.indexOf(self.workflow_summary) >= 0:
                        self.tabs.removeTab(self.tabs.indexOf(self.workflow_summary))
                    self.workflow_summary.deleteLater()
                    delattr(self, 'workflow_summary')
            
            # Add app tab if it doesn't exist
            if not has_app_tab:
                self.app_editor = ToolEditor(cwl_tool=self.cwl_tool, parent=self)
                self.tabs.insertTab(1, self.app_editor, 'Visual Editor')  # Insert before the Code tab
                
                self.app_editor.codeUpdated.connect(self.onUpdateCWL)
                # For CommandLineTool and ExpressionTool, switch to the visual editor
                self.tabs.setCurrentWidget(self.app_editor)
            
            # Add command line status bar for CommandLineTool if not exists
            if self.cwl_type == 'CommandLineTool' and not self.command_line:
                # Create command line status area
                self.command_line = CommandLine(cwl_tool=self.cwl_tool, parent=self)
                # Set height for 4 lines of text
                font_metrics = QFontMetrics(self.command_line.font())
                line_height = font_metrics.height()
                self.command_line.setFixedHeight(line_height * 4 + 16)
                
                # Get main layout and add command line at the bottom
                main_layout = self.layout()
                if main_layout:  # Add safety check
                    main_layout.addWidget(self.command_line)
            
        elif self.cwl_type == 'Workflow':
            # Remove app tab if it exists
            if has_app_tab:
                self.tabs.removeTab(self.tabs.indexOf(self.app_editor))
                self.app_editor.deleteLater()
                delattr(self, 'app_editor')
            
            # Add workflow tab if it doesn't exist
            if not has_workflow_tab:
                self.workflow_editor = WorkflowEditor(cwl_workflow=self.cwl_tool, parent=self, file_location=self.file_path)
                self.tabs.insertTab(1, self.workflow_editor, 'Visual Editor')  # Insert before the Code tab
                self.workflow_editor.codeUpdated.connect(self.onUpdateCWL)

                self.workflow_summary= WorkflowSummary(
                    cwl_workflow=self.cwl_tool, 
                    parent=self,
                    file_location=self.file_path
                )
                self.tabs.insertTab(2, self.workflow_summary, 'Summary')  # Insert before the Code tab
                # A workflow opens on its Visual Editor (the graph), like a tool
                self.tabs.setCurrentWidget(self.workflow_editor)
                self.logger.debug("Automatically switched to the Workflow Visual Editor tab")
             

    def closeEvent(self, event):
        """
        Handle the window close event.
        
        Signals the MainWindow that this window is being closed so it can
        remove the window from the Window menu.
        
        Args:
            event (QCloseEvent): The close event
        """
        self.logger.debug(f"ChildWindow {self.window_id} is being closed")
        # Unschedule any file watches registered by this window
        try:
            if hasattr(self, '_file_watches') and self._file_watches:
                observer = _get_global_observer()
                for w in self._file_watches:
                    try:
                        observer.unschedule(w)
                    except Exception:
                        pass
                self._file_watches.clear()
        except Exception:
            pass

        # Prompt to save if there are unsaved changes
        if self.hasChanged:
            reply = self.questionCentered(
                title="Save Changes?",
                text="You have unsaved changes. Do you want to save before closing?",
                show_cancel=True
            )
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.StandardButton.Yes:
                self.onMenuSaveFile()

        # Emit signal to the main window with this window's ID
        self.windowClosed.emit(self.window_id)
        # Call the parent class closeEvent to handle normal closing behavior
        super().closeEvent(event)

    def resizeEvent(self, event):
        """
        Handle resize events to adjust the CommandLine status bar height.
        
        Args:
            event: The resize event
        """
        super().resizeEvent(event)
        
        # Update CommandLine height if it exists and is visible
        if hasattr(self, 'command_line') and self.command_line and self.command_line.isVisible():
            # Set fixed height for command line view (4 lines of text)
            font_metrics = QFontMetrics(self.command_line.font())
            line_height = font_metrics.height()
            self.command_line.setFixedHeight(line_height * 4 + 16)


    def trackFileChange(self, path: Union[List, str]):
        """Start tracking changes to the specified file(s).
        
        Uses watchdog to monitor files and their parent directories for
        changes. When changes are detected, the user is prompted to reload
        the document.
        
        Args:
            path: A single path or list of paths to monitor for changes.
        """
        if isinstance(path,list):
            path=list(set(path))  # remove duplicates
        # Create handler and schedule on the shared observer
        self.file_event_handler = FileChangeHandler(path, self)
        # Route background thread events to GUI thread
        self.file_event_handler.fileChanged.connect(self.onExternalFileChanged)

        # Support single file or list of files; schedule by parent directory
        if isinstance(path, (list, tuple, set)):
            targets = [Path(p) for p in path]
        else:
            targets = [Path(path)]
        parent_dirs = {str(p.parent) for p in targets}

        # Keep watch handles for potential future unschedule needs
        self._file_watches = []
        observer = _get_global_observer()
        for d in parent_dirs:
            try:
                watch = observer.schedule(
                    self.file_event_handler,
                    d,
                    recursive=False,
                )
                self._file_watches.append(watch)
            except Exception as e:
                if hasattr(self, 'logger') and self.logger:
                    self.logger.error(
                        f"Failed to schedule file watcher on {d}: {e}"
                    )
        self.logger.info(f"\u2139 Now tracking changes to {json.dumps(path, indent=2)}")

    def onExternalFileChanged(self, path: str) -> None:
        """Handle external file changes in the GUI thread.

        Prompts the user to reload the document when an external change
        is detected. This method runs in the GUI thread and is safe to
        call Qt widgets and dialogs.

        The method includes debouncing to avoid multiple prompts for the
        same file, and respects the suppression window for our own saves.

        Args:
            path: The file path that changed.
        """
        # Normalize path for consistent suppression/debounce
        norm_path = self.normalizePath(path)

        # If this change was initiated by us recently, skip
        try:
            if self.shouldIgnoreFileChange(norm_path):
                self.logger.debug(f"Ignoring change event from our own save: {norm_path}")
                return
        except Exception:
            pass

        # If window is closing or hidden, skip prompt
        if not self.isVisible():
            return

        # Debounce multiple back-to-back events for the same file
        if self.shouldDebouncePrompt(norm_path, seconds=1.0):
            self.logger.debug(f"Debounced repeated change event: {norm_path}")
            return
        # Mark now to avoid subsequent duplicates while the dialog is open
        self.markPrompt(norm_path)

        # If the change was caused by another ChildWindow saving,
        # auto-reload silently instead of prompting the user.
        if _is_internal_save(norm_path):
            self.logger.info(f"Auto-reloading after internal save: {norm_path}")
            try:
                if self.file_path:
                    self.loadCWL()
            except Exception as e:
                if hasattr(self, 'logger') and self.logger:
                    self.logger.error(f"Failed to auto-reload after internal save: {e}")
            return

        reply = self.questionCentered(
            title="File changed",
            text=f"The file has changed on disk:\n{norm_path}\n\nReload it?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # If this is the current file, reload; otherwise, you could
                # choose to refresh only affected tabs/components.
                if self.file_path:
                    self.loadCWL()
            except Exception as e:
                if hasattr(self, 'logger') and self.logger:
                    self.logger.error(f"Failed to reload after change: {e}")

    def normalizePath(self, path: str) -> str:
        """Normalize a file path for consistent comparison.
        
        Handles both regular file paths and file:// URIs. Resolves
        relative paths to absolute paths.
        
        Args:
            path: A file path or file:// URI.
            
        Returns:
            str: The normalized absolute path.
        """
        try:
            # get the path from the file uri
            pp=str(Path(urlparse(path).path))
            # get the path of the current workflow
            wp=str(Path(self.file_path).parent.resolve())
            return os.path.abspath( os.path.join( wp , pp ) )
        except Exception:
            return path

    def shouldDebouncePrompt(self, path: str, seconds: float = 1.0) -> bool:
        """Check if a reload prompt for this path should be debounced.
        
        Prevents showing multiple prompts in quick succession for the
        same file (e.g., when atomic saves trigger multiple events).
        
        Args:
            path: The file path to check.
            seconds: The debounce window in seconds (default 1.0).
            
        Returns:
            bool: True if the prompt should be suppressed.
        """
        now = time.monotonic()
        with self._prompt_lock:
            last = self._last_prompt.get(path)
            if last is not None and (now - last) < max(0.1, seconds):
                return True
            return False

    def markPrompt(self, path: str) -> None:
        """Mark that a reload prompt was shown for this path.
        
        Used by the debouncing mechanism to track when prompts were shown.
        
        Args:
            path: The file path for which a prompt was shown.
        """
        with self._prompt_lock:
            self._last_prompt[path] = time.monotonic()

    def questionCentered(
        self, title: str, text: str, show_cancel: bool = False
    ) -> QMessageBox.StandardButton:
        """Show a question dialog centered over this window.
        
        Creates a modal question dialog that is positioned at the center
        of this window and stays on top. Used for prompting the user
        about file reloads and other important decisions.
        
        Args:
            title: The dialog window title.
            text: The question text to display.
            show_cancel: Whether to include a Cancel button.
            
        Returns:
            QMessageBox.StandardButton: The button that was clicked
                                       (Yes, No, or Cancel).
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        box.setText(text)
        
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        if show_cancel:
            buttons |= QMessageBox.StandardButton.Cancel
            
        box.setStandardButtons(buttons)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        # Use ApplicationModal to avoid nested modal dialog issues
        # (ChildWindow is itself a QDialog, so WindowModal creates nesting)
        box.setWindowModality(Qt.WindowModality.ApplicationModal)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        # Compute centered position using sizeHint without showing first
        size = box.sizeHint()
        parent_center = self.frameGeometry().center()
        top_left = QPoint(
            parent_center.x() - size.width() // 2,
            parent_center.y() - size.height() // 2,
        )
        box.move(top_left)
        return QMessageBox.StandardButton(box.exec())
