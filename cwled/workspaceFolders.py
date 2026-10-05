"""
The folders of the workspace.

Like the "Local Files" of Rabix Composer, the workspace can hold several
folders; each one is a root of the Workspace panel.

* ``data.workspace_folders`` is the ordered list of the folders (absolute,
  resolved paths).
* ``data.workspace_directory`` is the *current* workspace folder: the default
  location of the file dialogs and of new documents, and the working
  directory. It starts as the first folder and follows the folder the user
  works in (the root of the item selected in the Workspace panel, or the
  folder just added).

The list is saved in the user configuration as ``workspace_folders``. The
former single-folder setting ``workspace`` is kept equal to the first folder,
so an existing workspace becomes the first folder and older versions of the
application still find it.

Every window of the application has a ``Workspace``. The one of the main
window is the *primary* workspace described above; the module level functions
(``folders()``, ``addFolder()``...) work on it. A window that tabs were torn
off into gets its own, independent workspace (seeded from the window the tab
came from): it is not saved and does not change the working directory. When
tabs are moved back, the folders of the workspaces are merged
(``Workspace.merge``).
"""
import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union
import data

logger = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]

# results of addFolder()
ADDED = 'added'          # the folder is a new root (it may replace roots nested in it)
DUPLICATE = 'duplicate'  # the folder is already a root
NESTED = 'nested'        # the folder is inside a root, it is already in the workspace


def normalise(path: PathLike) -> str:
    """Absolute path with symbolic links resolved, as stored in the list."""
    return str(Path(path).expanduser().resolve())


def _isWithin(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _merged(current: List[str], folder: str) -> Tuple[List[str], str, List[str]]:
    """
    Add ``folder`` (normalised) to the list ``current``.

    Returns:
        (folders, status, related): the new list; ADDED, DUPLICATE or NESTED;
        for NESTED the root containing the folder, for ADDED the roots nested
        in the folder that it replaces (it takes the place of the first one,
        otherwise it is appended, like Composer does).
    """
    if folder in current:
        return current, DUPLICATE, [folder]
    path = Path(folder)
    for root in current:
        if _isWithin(path, Path(root)):
            return current, NESTED, [root]
    nested = [root for root in current if _isWithin(Path(root), path)]
    if not nested:
        return current + [folder], ADDED, []
    position = current.index(nested[0])
    remaining = [root for root in current if root not in nested]
    remaining.insert(position, folder)
    return remaining, ADDED, nested


class Workspace:
    """
    The folders of one window and its current folder.

    This base class keeps its state in the object: it is the workspace of a
    window that tabs were torn off into. ``PrimaryWorkspace`` keeps it in the
    ``data`` module instead, saves it, and follows it with the working
    directory.
    """

    def __init__(self, folders: Optional[Iterable[PathLike]] = None,
                 current: Optional[PathLike] = None):
        self._folders: List[str] = []
        for folder in folders or []:
            self._folders, _, _ = _merged(self._folders, normalise(folder))
        self._current: Optional[str] = None
        if current:
            self.setCurrentFolder(current)
        if self._current is None and self._folders:
            self._current = self._folders[0]

    # -- state (overridden by PrimaryWorkspace) ------------------------------
    def folders(self) -> List[str]:
        """The workspace folders, in the order of the Workspace panel."""
        return list(self._folders)

    def currentFolder(self) -> Optional[str]:
        """The current workspace folder (default location of new files)."""
        return self._current

    def _setFolders(self, folders: List[str]):
        self._folders = list(folders)

    def _setCurrent(self, folder: Optional[str]):
        self._current = folder

    def _foldersChanged(self):
        """The list of folders changed (the primary workspace saves it)."""

    def _currentChanged(self, folder: str):
        """The current folder changed (the primary workspace changes the working directory)."""

    # -- queries --------------------------------------------------------------
    def containingFolder(self, path: PathLike) -> Optional[str]:
        """The workspace folder that contains ``path``, or None."""
        try:
            resolved = Path(normalise(path))
        except (OSError, RuntimeError, ValueError):
            return None
        for folder in self.folders():
            if _isWithin(resolved, Path(folder)):
                return folder
        return None

    def isInsideWorkspace(self, path: PathLike) -> bool:
        """True if ``path`` is inside one of the workspace folders."""
        return self.containingFolder(path) is not None

    def copy(self) -> 'Workspace':
        """An independent workspace with the same folders and current folder."""
        return Workspace(self.folders(), self.currentFolder())

    # -- changes --------------------------------------------------------------
    def setCurrentFolder(self, folder: Optional[PathLike]) -> bool:
        """
        Make ``folder`` (a workspace folder) the current one: file dialogs and new
        documents start there.

        Returns:
            True if the current folder changed.
        """
        folder = normalise(folder) if folder else None
        if folder is not None and folder not in self.folders():
            logger.warning(f"{folder} is not a workspace folder")
            return False
        if folder == self.currentFolder():
            return False
        self._setCurrent(folder)
        if folder:
            self._currentChanged(folder)
        logger.debug(f"Current workspace folder: {folder}")
        return True

    def addFolder(self, folder: PathLike) -> Tuple[str, List[str]]:
        """
        Add a folder to the workspace. A folder already in the workspace (or
        inside one of its folders) is not added; roots nested in the new folder
        are replaced by it. The added folder becomes the current one.

        Returns:
            (status, related) as described in ``_merged``.
        """
        folder = normalise(folder)
        updated, status, related = _merged(self.folders(), folder)
        if status == ADDED:
            self._setFolders(updated)
            self.setCurrentFolder(folder)
            self._foldersChanged()
            logger.info(f"Added {folder} to the workspace")
        return status, related

    def removeFolder(self, folder: PathLike) -> bool:
        """
        Remove a folder from the workspace (the files are not touched). If it
        was the current folder, the first folder becomes current.

        Returns:
            True if the folder was part of the workspace.
        """
        folder = normalise(folder)
        current = self.folders()
        if folder not in current:
            return False
        current.remove(folder)
        self._setFolders(current)
        if self.currentFolder() not in current:
            self._setCurrent(None)
            if current:
                self.setCurrentFolder(current[0])
        self._foldersChanged()
        logger.info(f"Removed {folder} from the workspace")
        return True

    def merge(self, folders: Iterable[PathLike]) -> List[str]:
        """
        Take the folders of another workspace into this one, when tabs move
        between windows. Folders that are already here, or inside one of the
        folders here, are skipped; folders here that are inside a merged folder
        are replaced by it. The current folder stays, unless the folder that
        replaces it becomes the current one.

        Returns:
            The folders that were added.
        """
        before = self.folders()
        merged = list(before)
        for folder in folders:
            try:
                folder = normalise(folder)
            except (OSError, RuntimeError, ValueError, TypeError):
                continue
            if not Path(folder).is_dir():
                logger.warning(f"Not merging the workspace folder {folder}: not found")
                continue
            merged, _, _ = _merged(merged, folder)
        if merged == before:
            return []
        self._setFolders(merged)
        current = self.currentFolder()
        if current not in merged:
            # the current folder was replaced by the folder containing it
            self._setCurrent(None)
            replacement = next((root for root in merged
                                if current and _isWithin(Path(current), Path(root))), None)
            self.setCurrentFolder(replacement or merged[0])
        self._foldersChanged()
        added = [folder for folder in merged if folder not in before]
        logger.info(f"Merged {', '.join(added) or 'no new folder'} into the workspace")
        return added


class PrimaryWorkspace(Workspace):
    """
    The workspace of the main window. It lives in ``data.workspace_folders`` and
    ``data.workspace_directory``, it is saved in the user configuration and its
    current folder is the working directory.
    """

    def __init__(self):
        pass  # the state is in the data module

    def folders(self) -> List[str]:
        return list(getattr(data, 'workspace_folders', None) or [])

    def currentFolder(self) -> Optional[str]:
        current = getattr(data, 'workspace_directory', None)
        return str(current) if current else None

    def _setFolders(self, folders: List[str]):
        data.workspace_folders = list(folders)

    def _setCurrent(self, folder: Optional[str]):
        data.workspace_directory = Path(folder) if folder else ""

    def _foldersChanged(self):
        self.save()

    def _currentChanged(self, folder: str):
        try:
            os.chdir(folder)
        except OSError as e:
            logger.warning(f"Cannot change the working directory to {folder}: {e}")

    def save(self):
        """Save the folders in the user configuration."""
        configuration = data.configuration
        if configuration is None:
            return
        configuration['workspace_folders'] = self.folders()
        configuration['workspace'] = self.folders()[0] if self.folders() else None
        if data.configuration_manager:
            try:
                data.configuration_manager.saveConfiguration()
            except Exception as e:
                logger.error(f"Cannot save the workspace folders: {e}")


# The workspace of the main window; the functions below work on it
PRIMARY = PrimaryWorkspace()


def folders() -> List[str]:
    """The folders of the primary workspace, in the order of the Workspace panel."""
    return PRIMARY.folders()


def currentFolder() -> Optional[str]:
    """The current folder of the primary workspace (default location of new files)."""
    return PRIMARY.currentFolder()


def containingFolder(path: PathLike) -> Optional[str]:
    """The primary workspace folder that contains ``path``, or None."""
    return PRIMARY.containingFolder(path)


def isInsideWorkspace(path: PathLike) -> bool:
    """True if ``path`` is inside one of the primary workspace folders."""
    return PRIMARY.isInsideWorkspace(path)


def initialise(primary: Optional[PathLike] = None) -> List[str]:
    """
    Set up the workspace folders at start-up.

    The folder given on the command line (``primary``) comes first, then the
    single workspace folder of the configuration (``workspace``) and the saved
    ``workspace_folders``. Without any of them the working directory is used.
    Nothing is saved until the user adds or removes a folder.
    """
    configuration = data.configuration or {}
    candidates = []
    if primary:
        candidates.append(primary)
    if configuration.get('workspace'):
        candidates.append(configuration['workspace'])
    saved = configuration.get('workspace_folders') or []
    if isinstance(saved, (str, os.PathLike)):
        saved = [saved]
    candidates += list(saved)

    result = []
    for candidate in candidates:
        try:
            folder = normalise(candidate)
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning(f"Ignoring the workspace folder {candidate}: {e}")
            continue
        if not Path(folder).is_dir():
            logger.warning(f"⚠ Workspace folder {folder} not found")
            continue
        result, status, related = _merged(result, folder)
        if status == NESTED:
            logger.info(f"Workspace folder {folder} is inside {related[0]}; not added again")
    if not result:
        result = [normalise(Path.cwd())]
    data.workspace_folders = result
    setCurrentFolder(result[0])
    logger.info(f"ℹ Workspace folders: {', '.join(result)}")
    return result


def setCurrentFolder(folder: Optional[PathLike]) -> bool:
    """
    Make ``folder`` (a primary workspace folder) the current one: file dialogs
    and new documents start there and it becomes the working directory.

    Returns:
        True if the current folder changed.
    """
    return PRIMARY.setCurrentFolder(folder)


def addFolder(folder: PathLike) -> Tuple[str, List[str]]:
    """
    Add a folder to the primary workspace and save the list. A folder already
    in the workspace (or inside one of its folders) is not added; roots nested
    in the new folder are replaced by it. The added folder becomes the current one.

    Returns:
        (status, related) as described in ``_merged``.
    """
    return PRIMARY.addFolder(folder)


def removeFolder(folder: PathLike) -> bool:
    """
    Remove a folder from the primary workspace (the files are not touched) and
    save the list. If it was the current folder, the first folder becomes current.

    Returns:
        True if the folder was part of the workspace.
    """
    return PRIMARY.removeFolder(folder)


def save():
    """Save the folders of the primary workspace in the user configuration."""
    PRIMARY.save()
