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
"""
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple, Union
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


def folders() -> List[str]:
    """The workspace folders, in the order of the Workspace panel."""
    return list(getattr(data, 'workspace_folders', None) or [])


def currentFolder() -> Optional[str]:
    """The current workspace folder (default location of new files)."""
    current = getattr(data, 'workspace_directory', None)
    return str(current) if current else None


def _isWithin(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def containingFolder(path: PathLike) -> Optional[str]:
    """The workspace folder that contains ``path``, or None."""
    try:
        resolved = Path(normalise(path))
    except (OSError, RuntimeError, ValueError):
        return None
    for folder in folders():
        if _isWithin(resolved, Path(folder)):
            return folder
    return None


def isInsideWorkspace(path: PathLike) -> bool:
    """True if ``path`` is inside one of the workspace folders."""
    return containingFolder(path) is not None


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
    Make ``folder`` (a workspace folder) the current one: file dialogs and new
    documents start there and it becomes the working directory.

    Returns:
        True if the current folder changed.
    """
    folder = normalise(folder) if folder else None
    if folder is not None and folder not in folders():
        logger.warning(f"{folder} is not a workspace folder")
        return False
    if folder == currentFolder():
        return False
    data.workspace_directory = Path(folder) if folder else ""
    if folder:
        try:
            os.chdir(folder)
        except OSError as e:
            logger.warning(f"Cannot change the working directory to {folder}: {e}")
    logger.debug(f"Current workspace folder: {folder}")
    return True


def addFolder(folder: PathLike) -> Tuple[str, List[str]]:
    """
    Add a folder to the workspace and save the list. A folder already in the
    workspace (or inside one of its folders) is not added; roots nested in
    the new folder are replaced by it. The added folder becomes the current one.

    Returns:
        (status, related) as described in ``_merged``.
    """
    folder = normalise(folder)
    updated, status, related = _merged(folders(), folder)
    if status == ADDED:
        data.workspace_folders = updated
        setCurrentFolder(folder)
        save()
        logger.info(f"Added {folder} to the workspace")
    return status, related


def removeFolder(folder: PathLike) -> bool:
    """
    Remove a folder from the workspace (the files are not touched) and save
    the list. If it was the current folder, the first folder becomes current.

    Returns:
        True if the folder was part of the workspace.
    """
    folder = normalise(folder)
    current = folders()
    if folder not in current:
        return False
    current.remove(folder)
    data.workspace_folders = current
    if currentFolder() not in current:
        data.workspace_directory = ""
        if current:
            setCurrentFolder(current[0])
    save()
    logger.info(f"Removed {folder} from the workspace")
    return True


def save():
    """Save the folders in the user configuration."""
    configuration = data.configuration
    if configuration is None:
        return
    configuration['workspace_folders'] = folders()
    configuration['workspace'] = folders()[0] if folders() else None
    if data.configuration_manager:
        try:
            data.configuration_manager.saveConfiguration()
        except Exception as e:
            logger.error(f"Cannot save the workspace folders: {e}")
