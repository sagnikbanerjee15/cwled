"""
Folders of remote machines (EC2 instances...) in the workspace, over ssh.

A remote folder is *mirrored*: the CWL documents of the folder (``.cwl``, ``.yml``,
``.yaml`` and ``.json`` files, without hidden folders) are copied into a folder of the
user's machine, and that copy is a workspace folder like any other. Everything the
application does with a folder (the tree, search, opening, relative paths between
workflows and tools, the file watcher) therefore works the same on it. What is different:

* the copy is refreshed from the remote machine when it is added and by *Sync from
  Remote* (a file that was changed here and not uploaded yet is kept, not overwritten);
* saving a document of the copy uploads it to the remote machine at once;
* the root of the folder in the Workspace panel is named ``host:/remote/path``.

Only the ``ssh`` program of the user is used (so ``~/.ssh/config``, keys, the agent, jump
hosts and Session Manager proxies all work as they do in a terminal), with ``BatchMode``:
it never asks for a password, so the key has to be usable without being typed (an agent,
or no passphrase) and the host key has to be known already (connect once in a terminal).
The remote machine needs nothing but a POSIX shell with ``find``, ``tar`` and ``cat``.

Files that come from the remote machine are not trusted: the archive is read entry by
entry, only regular files with a plain relative name are written, and only inside the
copy of the folder.
"""
import logging
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

import data

logger = logging.getLogger(__name__)

SUFFIXES = ('.cwl', '.yml', '.yaml', '.json')       # the files that are copied
MAX_FILE_BYTES = 2 * 1024 * 1024                    # larger files are not copied
MAX_FILES = 5000                                    # a folder with more documents is cut here
CONNECT_TIMEOUT = 15
CONFIG_KEY = 'remote_folders'
PART_SUFFIX = '.cwled-part'


class RemoteError(Exception):
    """Something went wrong with a remote machine; the text says what, for the user."""


# ------------------------------------------------------------------------------------------------ transports
class Transport:
    """Runs a shell script on a machine. ``SshTransport`` is the real one; tests use ``LocalTransport``."""

    def argv(self, script: str) -> List[str]:
        raise NotImplementedError

    def describe(self) -> str:
        return 'the machine'

    def popen(self, script: str, stdin=None, stdout=subprocess.PIPE, stderr=None) -> subprocess.Popen:
        try:
            return subprocess.Popen(self.argv(script), stdin=stdin, stdout=stdout, stderr=stderr)
        except FileNotFoundError as e:
            raise RemoteError(f"The program {self.argv(script)[0]!r} was not found: {e}") from e

    def run(self, script: str, stdin: Optional[bytes] = None, timeout: float = 60) -> Tuple[bytes, str]:
        """Run a script and return what it printed; an error (also a failing script) is a RemoteError."""
        try:
            with tempfile.TemporaryFile() as errors:
                process = self.popen(script, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                     stderr=errors)
                try:
                    output, _ = process.communicate(stdin, timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise RemoteError(f"{self.describe()} did not answer within {timeout:g} seconds") from None
                errors.seek(0)
                message = errors.read().decode('utf-8', errors='replace').strip()
        except OSError as e:
            raise RemoteError(f"{self.describe()} cannot be reached: {e}") from e
        if process.returncode != 0:
            raise RemoteError(self.failure(process.returncode, message))
        return output, message

    def failure(self, code: int, message: str) -> str:
        return message or f"the command failed on {self.describe()} (exit code {code})"


class SshTransport(Transport):
    """The ssh program, with the host given as in the SSH configuration (an alias or ``user@host``)."""
    OPTIONS = ['-T', '-o', 'BatchMode=yes', '-o', f'ConnectTimeout={CONNECT_TIMEOUT}',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3']

    def __init__(self, host: str, executable: Optional[str] = None):
        if not host or host.startswith('-') or any(char.isspace() for char in host):
            raise RemoteError(f"{host!r} is not a host name")
        self.host = host
        self.executable = executable or shutil.which('ssh') or 'ssh'

    def argv(self, script: str) -> List[str]:
        # the script goes through "sh -c" whatever the login shell of the user is (csh, fish...)
        return [self.executable, *self.OPTIONS, '--', self.host, 'sh -c ' + shlex.quote(script)]

    def describe(self) -> str:
        return self.host

    def failure(self, code: int, message: str) -> str:
        if code == 255 or 'Permission denied' in message or 'Host key verification' in message:
            hint = ""
            if 'Host key verification failed' in message:
                hint = "\n\nConnect to the host once in a terminal (ssh " + self.host + ") to accept its host key."
            elif 'Permission denied' in message:
                hint = ("\n\nCWLed never asks for a password: the key has to be loaded in the ssh agent "
                        "(ssh-add) or have no passphrase.")
            return f"Cannot connect to {self.host}: {message or 'ssh failed'}{hint}"
        return message or f"the command failed on {self.host} (exit code {code})"


class LocalTransport(Transport):
    """Runs the scripts on this machine, in a shell: the same scripts, without a network (for tests)."""

    def argv(self, script: str) -> List[str]:
        return ['sh', '-c', script]

    def describe(self) -> str:
        return 'this machine'


# ------------------------------------------------------------------------------------------------ remote paths
def remoteExpr(path: str) -> str:
    """A path as a shell word: ``~`` stands for the home directory of the user on the remote machine."""
    if path == '~':
        return '"$HOME"'
    if path.startswith('~/'):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)


@dataclass
class RemoteEntry:
    name: str
    is_dir: bool


def resolvePath(transport: Transport, path: str) -> str:
    """The absolute path of a folder of the remote machine (``~`` and links resolved); it must exist."""
    output, _ = transport.run(f'cd -- {remoteExpr(path or "~")} >/dev/null && pwd -P')
    resolved = output.decode('utf-8', errors='replace').strip().splitlines()
    if not resolved:
        raise RemoteError(f"{path} could not be opened on {transport.describe()}")
    return resolved[-1]


def listDirectory(transport: Transport, path: str) -> Tuple[str, List[RemoteEntry]]:
    """The absolute path of a remote folder and what it holds (folders first)."""
    output, _ = transport.run(f'cd -- {remoteExpr(path or "~")} >/dev/null && pwd -P && LC_ALL=C ls -1Ap')
    lines = output.decode('utf-8', errors='replace').splitlines()
    if not lines:
        raise RemoteError(f"{path} could not be listed on {transport.describe()}")
    resolved, entries = lines[0], []
    for line in lines[1:]:
        if not line:
            continue
        is_dir = line.endswith('/')
        entries.append(RemoteEntry(line.rstrip('/') if is_dir else line, is_dir))
    entries.sort(key=lambda entry: (not entry.is_dir, entry.name.casefold()))
    return resolved, entries


# ------------------------------------------------------------------------------------------------ copying
@dataclass
class PullResult:
    files: int = 0                                         # files copied (new or changed)
    unchanged: int = 0                                     # files that were up to date
    kept_local: List[str] = field(default_factory=list)    # files changed here and not uploaded: left alone
    skipped: List[str] = field(default_factory=list)       # entries that were refused (unsafe or too large)
    truncated: bool = False                                # more than MAX_FILES documents: the rest is not copied

    def summary(self) -> str:
        parts = [f"{self.files} file{'s' if self.files != 1 else ''} copied"]
        if self.unchanged:
            parts.append(f"{self.unchanged} up to date")
        if self.kept_local:
            parts.append(f"{len(self.kept_local)} changed here, not overwritten")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        if self.truncated:
            parts.append(f"only the first {MAX_FILES} documents")
        return ", ".join(parts)


def _pullScript(path: str) -> str:
    names = ' -o '.join(f'-name "*{suffix}"' for suffix in SUFFIXES)
    blocks = MAX_FILE_BYTES // 512 + 1
    return (f'cd -- {remoteExpr(path)} >/dev/null || exit 3\n'
            f'files=$(find . -type f \\( {names} \\) -size -{blocks} -not -path "*/.*" '
            f'-not -path "*/node_modules/*" -not -path "*/__pycache__/*" | head -n {MAX_FILES + 1})\n'
            f'[ -n "$files" ] || exit 0\n'
            f'printf "%s\\n" "$files" | tar -cf - -T -\n')


def _safeRelativePath(name: str) -> Optional[PurePosixPath]:
    """The name of an archive entry as a plain relative path, or None if it could lead out of the folder."""
    path = PurePosixPath(name)
    if path.is_absolute():
        return None
    parts = [part for part in path.parts if part not in ('', '.')]
    if not parts or '..' in parts or any('\x00' in part or '\\' in part for part in parts):
        return None
    return PurePosixPath(*parts)


def pullFolder(transport: Transport, remote_path: str, mirror: Path) -> PullResult:
    """
    Copy the documents of a remote folder into ``mirror``. When a file differs on both sides the
    newer one wins: a file that was changed here and could not be uploaded is kept, and a file that
    was changed on the remote machine since is copied.
    """
    result = PullResult()
    mirror = Path(mirror)
    mirror.mkdir(parents=True, exist_ok=True)
    root = mirror.resolve()
    with tempfile.TemporaryFile() as errors:
        process = transport.popen(_pullScript(remote_path), stdin=subprocess.DEVNULL, stderr=errors)
        count = 0
        try:
            try:
                with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                    for member in archive:
                        count += 1
                        if count > MAX_FILES:
                            result.truncated = True
                            break
                        _extractMember(archive, member, root, result)
            except tarfile.ReadError as e:
                if 'empty' not in str(e).lower():
                    raise RemoteError(f"{transport.describe()} did not send a list of files ({e}). Does a "
                                      f"login script of the account print text?") from e
        finally:
            process.stdout.close()
            process.wait()
            errors.seek(0)
            message = errors.read().decode('utf-8', errors='replace').strip()
    if process.returncode != 0 and not result.truncated:
        if process.returncode == 3:
            raise RemoteError(f"The folder {remote_path} cannot be opened on {transport.describe()}"
                              + (f": {message}" if message else ""))
        raise RemoteError(transport.failure(process.returncode, message))
    return result


def _extractMember(archive: tarfile.TarFile, member: tarfile.TarInfo, root: Path, result: PullResult):
    if member.isdir():
        return
    relative = _safeRelativePath(member.name)
    if (not member.isreg() or relative is None or not str(relative).lower().endswith(SUFFIXES)
            or member.size > MAX_FILE_BYTES):
        result.skipped.append(member.name)
        return
    target = root.joinpath(*relative.parts)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        inside = parent.resolve() == root or root in parent.resolve().parents
    except OSError:
        inside = False
    if not inside or target.is_symlink():
        result.skipped.append(member.name)       # a link in the copy that leads somewhere else
        return
    body = archive.extractfile(member).read()
    if target.exists():
        if target.read_bytes() == body:
            result.unchanged += 1
            return
        if target.stat().st_mtime > member.mtime:
            # changed here after the remote file was written, and not uploaded (or the machine
            # was not reached): the newer file wins
            result.kept_local.append(str(relative))
            return
    partial = target.with_name(target.name + PART_SUFFIX)
    partial.write_bytes(body)
    os.replace(partial, target)
    os.utime(target, (member.mtime, member.mtime))
    result.files += 1


def pushFile(transport: Transport, local: Path, remote_path: str):
    """
    Write a file on the remote machine: through a temporary file that replaces the old one (which
    keeps its mode), so that a connection that breaks leaves the old file, not half of the new one.
    """
    body = Path(local).read_bytes()
    target = remoteExpr(remote_path)
    script = (f'p={target}\n'
              f'mkdir -p -- "$(dirname -- "$p")" || exit 3\n'
              f'tmp="$p.cwled-part.$$"\n'
              f'if [ -e "$p" ]; then cp -p -- "$p" "$tmp" || exit 4; fi\n'
              f'cat > "$tmp" && mv -f -- "$tmp" "$p" || {{ rm -f -- "$tmp"; exit 5; }}\n')
    transport.run(script, stdin=body, timeout=120)


# ------------------------------------------------------------------------------------------------ the folders
def defaultRoot() -> Path:
    """Where the copies of the remote folders are kept: the data folder of the application."""
    from platformdirs import user_data_path
    return Path(user_data_path(appname='cwled')) / 'remote'


def _plain(name: str) -> str:
    """A name that is safe as a folder name."""
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('.') or '_'
    return name


@dataclass
class RemoteFolder:
    host: str           # as given to ssh (an alias of the SSH configuration, or user@host)
    path: str           # the absolute path on the remote machine
    mirror: str         # the folder here that holds the copy
    synced: float = 0.0   # when it was last copied

    @property
    def label(self) -> str:
        return f"{self.host}:{self.path}"

    def contains(self, local_path) -> bool:
        try:
            Path(local_path).resolve().relative_to(Path(self.mirror).resolve())
            return True
        except ValueError:
            return False

    def remotePathOf(self, local_path) -> str:
        relative = Path(local_path).resolve().relative_to(Path(self.mirror).resolve())
        return posixpath.join(self.path, *relative.parts)


class _Signals(QObject):
    done = pyqtSignal(object, object)       # the result, the error (RemoteError or other) or None


class _Job(QRunnable):
    def __init__(self, function: Callable, signals: _Signals):
        super().__init__()
        self.function = function
        self.signals = signals

    def run(self):
        try:
            result, error = self.function(), None
        except Exception as e:                           # shown to the user, by whoever asked
            result, error = None, e
        self.signals.done.emit(result, error)


class RemoteFolders(QObject):
    """
    The remote folders of the workspace: what is copied from where, and the work with the machines
    (listing, copying, uploading), which is done in other threads so that the window does not freeze.
    """
    changed = pyqtSignal()                       # the list of remote folders changed
    synced = pyqtSignal(str, object)             # the copy that was refreshed, what was done (a PullResult)
    syncFailed = pyqtSignal(str, str)            # the copy that could not be refreshed, why
    uploaded = pyqtSignal(str, str)              # the file, where it went (label of the remote file)
    uploadFailed = pyqtSignal(str, str)          # the file, why

    def __init__(self, root: Optional[Path] = None, transport_factory: Optional[Callable[[str], Transport]] = None,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self.root = Path(root) if root is not None else defaultRoot()
        self.transportFor = transport_factory or (lambda host: SshTransport(host))
        self._folders: List[RemoteFolder] = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._running = set()
        self._uploading: Dict[str, bool] = {}     # file -> another upload of it is waiting
        self.load()

    # -- the list ----------------------------------------------------------------------------------------------
    def load(self):
        """Read the list from the configuration."""
        self._folders = []
        for entry in (data.configuration or {}).get(CONFIG_KEY) or []:
            try:
                self._folders.append(RemoteFolder(str(entry['host']), str(entry['path']), str(entry['mirror']),
                                                  float(entry.get('synced') or 0.0)))
            except (KeyError, TypeError, ValueError):
                logger.warning(f"Ignoring an entry of {CONFIG_KEY} in the configuration: {entry!r}")

    def save(self):
        if data.configuration is None:
            return
        data.configuration[CONFIG_KEY] = [{'host': f.host, 'path': f.path, 'mirror': f.mirror, 'synced': f.synced}
                                          for f in self._folders]
        if data.configuration_manager:
            try:
                data.configuration_manager.saveConfiguration()
            except Exception as e:
                logger.error(f"Cannot save the remote folders in the configuration: {e}")

    def folders(self) -> List[RemoteFolder]:
        return list(self._folders)

    def labels(self) -> Dict[str, str]:
        """Local copy -> ``host:/remote/path``, for naming the roots of the Workspace panel."""
        return {str(Path(f.mirror).resolve()): f.label for f in self._folders}

    def folderFor(self, local_path) -> Optional[RemoteFolder]:
        """The remote folder whose copy holds a file or folder here (the innermost one), if any."""
        found = [f for f in self._folders if f.contains(local_path)]
        return max(found, key=lambda f: len(Path(f.mirror).parts)) if found else None

    def mirrorFor(self, host: str, remote_path: str) -> Path:
        parts = [_plain(part) for part in PurePosixPath(remote_path).parts if part != '/']
        return self.root.joinpath(_plain(host), *parts)

    def remove(self, mirror: str):
        """Forget a remote folder (the copy is left on the disk)."""
        key = str(Path(mirror))
        self._folders = [f for f in self._folders if str(Path(f.mirror)) != key]
        self.save()
        self.changed.emit()

    # -- work with the machines ---------------------------------------------------------------------------------
    def submit(self, function: Callable, callback: Callable[[object, Optional[Exception]], None]):
        """Run ``function`` in another thread; ``callback(result, error)`` is called in this one when it is done."""
        signals = _Signals()
        self._running.add(signals)

        def finished(result, error):
            self._running.discard(signals)
            signals.deleteLater()
            callback(result, error)

        signals.done.connect(finished)
        self._pool.start(_Job(function, signals))

    def addFolder(self, host: str, remote_path: str, callback: Callable[[Optional[RemoteFolder], Optional[Exception]], None]):
        """
        Copy a remote folder and add it to the list. ``callback(folder, error)`` is called when it
        is done; nothing is added when the copy fails (the machine cannot be reached, no such folder).
        """
        def work():
            transport = self.transportFor(host)
            absolute = resolvePath(transport, remote_path)
            mirror = self.mirrorFor(host, absolute)
            result = pullFolder(transport, absolute, mirror)
            return absolute, mirror, result

        def done(outcome, error):
            if error is not None:
                callback(None, error)
                return
            absolute, mirror, result = outcome
            folder = next((f for f in self._folders if f.host == host and f.path == absolute), None)
            if folder is None:
                folder = RemoteFolder(host, absolute, str(mirror))
                self._folders.append(folder)
            folder.synced = _now()
            self.save()
            self.changed.emit()
            self.synced.emit(folder.mirror, result)
            callback(folder, None)

        self.submit(work, done)

    def sync(self, mirror: str):
        """Copy the remote folder again; ``synced`` or ``syncFailed`` tells what became of it."""
        folder = self.folderFor(mirror)
        if folder is None:
            return

        def work():
            return pullFolder(self.transportFor(folder.host), folder.path, Path(folder.mirror))

        def done(result, error):
            if error is not None:
                self.syncFailed.emit(folder.mirror, str(error))
                return
            folder.synced = _now()
            self.save()
            self.synced.emit(folder.mirror, result)

        self.submit(work, done)

    def syncAll(self):
        for folder in self._folders:
            self.sync(folder.mirror)

    def upload(self, local_path) -> bool:
        """Write a file of a copy on the remote machine. False if the file is not in a copy."""
        folder = self.folderFor(local_path)
        if folder is None or not Path(local_path).is_file():
            return False
        key = str(Path(local_path).resolve())
        if key in self._uploading:
            self._uploading[key] = True          # saved again meanwhile: upload once more afterwards
            return True
        self._uploading[key] = False
        remote = folder.remotePathOf(local_path)

        def work():
            pushFile(self.transportFor(folder.host), Path(local_path), remote)

        def done(_result, error):
            again = self._uploading.pop(key, False)
            if error is not None:
                self.uploadFailed.emit(str(local_path), f"{folder.host}:{remote}: {error}")
            else:
                self.uploaded.emit(str(local_path), f"{folder.host}:{remote}")
            if again:
                self.upload(local_path)

        self.submit(work, done)
        return True


def _now() -> float:
    import time
    return time.time()
