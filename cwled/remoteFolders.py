"""
Folders of remote machines (EC2 instances...) in the workspace, over ssh.

A remote folder is *mirrored*: the CWL documents of the folder (``.cwl``, ``.yml``,
``.yaml`` and ``.json`` files, without hidden folders) are copied into a folder of the
user's machine, and that copy is a workspace folder like any other. Everything the
application does with a folder (the tree, search, opening, relative paths between
workflows and tools, the file watcher) therefore works the same on it. What is different:

* the copy is made level by level: when the folder is added only its first level is read
  (its documents, and its sub-folders as empty folders), and a sub-folder is read when it is
  opened in the Workspace panel (``RemoteFolders.fetchLevel``), so that a large folder
  appears at once;
* the folders that were read are read again by *Sync from Remote* (a file that was changed
  here and not uploaded yet is kept, not overwritten), and when they are opened in a later session;
* saving a document of the copy uploads it to the remote machine at once;
* the root of the folder in the Workspace panel is named ``host:/remote/path``.

Only the ``ssh`` program of the user is used (so ``~/.ssh/config``, keys, the agent, jump
hosts and Session Manager proxies all work as they do in a terminal), with ``BatchMode``:
it never asks for a password, so the key has to be usable without being typed (an agent,
or no passphrase) and the host key has to be known already (connect once in a terminal).
The remote machine needs nothing but a POSIX shell with ``find``, ``tar`` and ``cat``.

Files that come from the remote machine are not trusted: the archive is read entry by
entry, only regular files and folders with a plain relative name are written, and only
inside the copy of the folder.
"""
import logging
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import hashlib
import json
import tarfile
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

import data

logger = logging.getLogger(__name__)

SUFFIXES = ('.cwl', '.yml', '.yaml', '.json')       # the files that are copied
MAX_FILE_BYTES = 2 * 1024 * 1024                    # larger files are not copied
MAX_DEPENDENCY_ROUNDS = 12                          # how many times, at most, files are asked for to follow what documents refer to
MAX_ENTRIES = 5000                                  # a folder with more documents and folders is cut here
CONNECT_TIMEOUT = 15
CONFIG_KEY = 'remote_folders'
PART_SUFFIX = '.cwled-part'
INDEX_NAME = '.cwled-remote-index'                 # in a copy: what was last known to be on the machine
IGNORED_FOLDERS = ('node_modules', '__pycache__')   # never listed (the hidden ones are not either)


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
    folders: int = 0                                       # sub-folders found (made here as empty folders)
    removed: int = 0                                       # files that are gone from the machine (renamed, deleted) and were removed here
    kept_local: List[str] = field(default_factory=list)    # files changed here and not uploaded: left alone
    skipped: List[str] = field(default_factory=list)       # entries that were refused (unsafe or too large)
    truncated: bool = False                                # more than MAX_ENTRIES in a folder: the rest is not read

    def summary(self) -> str:
        parts = [f"{self.files} file{'s' if self.files != 1 else ''} copied"]
        if self.unchanged:
            parts.append(f"{self.unchanged} up to date")
        if self.folders:
            parts.append(f"{self.folders} folder{'s' if self.folders != 1 else ''}")
        if self.removed:
            parts.append(f"{self.removed} removed (gone from the machine)")
        if self.kept_local:
            parts.append(f"{len(self.kept_local)} changed here, not overwritten")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        if self.truncated:
            parts.append(f"only the first {MAX_ENTRIES} entries of a folder")
        return ", ".join(parts)


def _levelScript(path: str) -> str:
    """
    The script that sends one level of each folder it is given on its input (relative to ``path``, one
    per line, "." for ``path`` itself): the documents of the folder and its sub-folders, as a tar
    archive without the contents of the sub-folders.
    """
    names = ' -o '.join(f'-name "*{suffix}"' for suffix in SUFFIXES)
    blocks = MAX_FILE_BYTES // 512 + 1
    folders = '-type d -not -name ".*" -not -name node_modules -not -name __pycache__'
    files = f'-type f \\( {names} \\) -size -{blocks} -not -name ".*"'
    return (f'cd -- {remoteExpr(path)} >/dev/null || exit 3\n'
            f'list=$(while IFS= read -r d; do\n'
            f'  [ -d "$d" ] || continue\n'
            f'  printf "%s\\n" "$d"\n'
            f'  find "$d" -mindepth 1 -maxdepth 1 \\( \\( {folders} \\) -o \\( {files} \\) \\) 2>/dev/null\n'
            f'done | head -n {MAX_ENTRIES + 1})\n'
            f'[ -n "$list" ] || exit 0\n'
            f'printf "%s\\n" "$list" | tar -cf - --no-recursion -T -\n')


def _safeRelativePath(name: str) -> Optional[PurePosixPath]:
    """The name of an archive entry as a plain relative path, or None if it could lead out of the folder."""
    path = PurePosixPath(name)
    if path.is_absolute():
        return None
    parts = [part for part in path.parts if part not in ('', '.')]
    if not parts or '..' in parts or any('\x00' in part or '\\' in part for part in parts):
        return None
    return PurePosixPath(*parts)


def pullLevels(transport: Transport, remote_path: str, folders: List[str], mirror: Path) -> PullResult:
    """
    Copy one level of some folders of a remote folder into ``mirror``: the documents they hold and
    their sub-folders (made here as empty folders, which are read when they are opened). ``folders``
    are relative to ``remote_path``; ``''`` is the folder itself. When a file differs on both sides
    the one that changed since they were last the same wins (the newer one when both did): a file that
    was changed here and could not be uploaded is kept, and a file that was changed on the remote machine
    since is copied. What the machine no longer has (a folder or document that was renamed or deleted
    there) is removed here, unless it was changed here.
    """
    wanted = ['.' if not folder else './' + folder.strip('/') for folder in folders if '\n' not in folder]
    return _pull(transport, remote_path, _levelScript(remote_path), wanted, mirror, None, prune=True)


def pullFiles(transport: Transport, remote_path: str, files: List[str], mirror: Path) -> PullResult:
    """
    Copy some files of a remote folder into ``mirror`` whatever their suffix (the files that a workflow
    refers to: its tools, what it imports or includes). ``files`` are relative to ``remote_path``; one that
    does not exist on the machine is left out.
    """
    wanted = [file.strip('/') for file in files if '\n' not in file and file.strip('/')]
    return _pull(transport, remote_path, _filesScript(remote_path), wanted, mirror, set(wanted))


def _filesScript(path: str) -> str:
    """The script that sends the files it is given on its input (relative to ``path``, one per line), if they exist."""
    return (f'cd -- {remoteExpr(path)} >/dev/null || exit 3\n'
            f'list=$(while IFS= read -r f; do [ -f "./$f" ] && printf "%s\\n" "./$f"; done)\n'
            f'[ -n "$list" ] || exit 0\n'
            f'printf "%s\\n" "$list" | tar -chf - --no-recursion -T -\n')


class MirrorIndex:
    """
    What was last known to be on the machine for each file of a copy: the sha1 of its content, when it was copied from
    the machine or written to it. A file is *changed here* when its content differs from that, *changed on the machine*
    when what the machine has differs from it: that does not depend on the clocks of the two computers, and it is what
    lets a file that is gone from the machine (renamed, deleted) be removed here only when nobody changed it here.
    It is a hidden file in the copy (``INDEX_NAME``).
    """
    lock = threading.Lock()

    def __init__(self, root: Path):
        self.path = Path(root) / INDEX_NAME
        self.files: Dict[str, str] = {}
        self._set: Dict[str, str] = {}
        self._removed: set = set()
        try:
            self.files = dict(json.loads(self.path.read_text(encoding='utf-8')).get('files') or {})
        except (OSError, ValueError, AttributeError):
            self.files = {}

    def get(self, relative: str) -> Optional[str]:
        return self.files.get(relative)

    def set(self, relative: str, digest: str):
        self.files[relative] = digest
        self._set[relative] = digest
        self._removed.discard(relative)

    def discard(self, relative: str):
        self.files.pop(relative, None)
        self._set.pop(relative, None)
        self._removed.add(relative)

    def commit(self):
        """Write what changed (merged with what another thread wrote meanwhile)."""
        if not self._set and not self._removed:
            return
        with MirrorIndex.lock:
            try:
                current = dict(json.loads(self.path.read_text(encoding='utf-8')).get('files') or {})
            except (OSError, ValueError, AttributeError):
                current = {}
            current.update(self._set)
            for relative in self._removed:
                current.pop(relative, None)
            partial = self.path.with_name(self.path.name + PART_SUFFIX)
            try:
                partial.write_text(json.dumps({'files': current}, indent=0, sort_keys=True), encoding='utf-8')
                os.replace(partial, self.path)
            except OSError as e:
                logger.warning(f"Cannot write {self.path}: {e}")
        self._set, self._removed = {}, set()

    @staticmethod
    def record(root: Path, relative: str, digest: str):
        """A file of the copy was written on the machine: that is what the machine has now."""
        index = MirrorIndex(root)
        index.set(relative, digest)
        index.commit()


def _sha1(body: bytes) -> str:
    return hashlib.sha1(body).hexdigest()


class _Puller:
    """Reads the archive that a script sends and writes what is in it into a copy; then removes what is gone."""

    def __init__(self, root: Path, result: PullResult, allowed: Optional[set], requested: Optional[List[str]]):
        self.root, self.result, self.allowed = root, result, allowed
        self.index = MirrorIndex(root)
        self.requested = {name.strip('/').removeprefix('./').removeprefix('.') for name in (requested or [])} if requested else set()
        self.present: set = set()                           # the requested folders that the machine has
        self.listing: Dict[str, set] = {}                   # folder -> the names that the machine has in it
        self.seen: set = set()

    # -- what is sent ---------------------------------------------------------------------------------------------
    def extract(self, archive: tarfile.TarFile, member: tarfile.TarInfo):
        result, root = self.result, self.root
        relative = _safeRelativePath(member.name)
        if relative is None:
            if member.isdir() and not PurePosixPath(member.name).is_absolute() \
                    and all(part in ('', '.') for part in PurePosixPath(member.name).parts):
                self.present.add('')                         # the folder itself ("./")
            else:
                result.skipped.append(member.name)
            return
        text = relative.as_posix()
        target = root.joinpath(*relative.parts)
        if member.isdir():
            if not _inside(target, root) or target.is_symlink():
                result.skipped.append(member.name)
                return
            if text in self.requested:
                self.present.add(text)
            parent = relative.parent.as_posix()
            self.listing.setdefault('' if parent == '.' else parent, set()).add(relative.name)
            if text not in self.seen:
                self.seen.add(text)
                target.mkdir(parents=True, exist_ok=True)
                result.folders += 1
            return
        # a file that was asked for by name may have any suffix, otherwise only documents are taken
        named = text in self.allowed if self.allowed is not None else text.lower().endswith(SUFFIXES)
        if (not member.isreg() or not named or member.size > MAX_FILE_BYTES
                or not _inside(target.parent, root) or target.is_symlink()):
            result.skipped.append(member.name)       # not a plain document, or a link in the copy that leads elsewhere
            return
        parent = relative.parent.as_posix()
        self.listing.setdefault('' if parent == '.' else parent, set()).add(relative.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        body = archive.extractfile(member).read()
        digest = _sha1(body)
        if target.exists():
            local = target.read_bytes()
            if local == body:
                result.unchanged += 1
                self.index.set(text, digest)
                return
            base = self.index.get(text)
            if base is not None:
                changed_here, changed_there = _sha1(local) != base, digest != base
                keep = changed_here and (not changed_there or target.stat().st_mtime > member.mtime)
            else:
                keep = target.stat().st_mtime > member.mtime          # nothing known: the newer file wins
            if keep:
                # changed here and not uploaded (the machine was not reached), or newer than what the machine has
                result.kept_local.append(text)
                return
        partial = target.with_name(target.name + PART_SUFFIX)
        partial.write_bytes(body)
        os.replace(partial, target)
        os.utime(target, (member.mtime, member.mtime))
        self.index.set(text, digest)
        result.files += 1

    # -- what is gone ---------------------------------------------------------------------------------------------
    def prune(self):
        """
        Remove, from the folders that were read, what the machine no longer has: a folder or document that was renamed
        or deleted there. Only documents that are as they were copied (or written to the machine) are removed, and
        folders only when they are empty then: what was changed here, or never copied, stays.
        """
        for level in sorted(self.requested):
            base = self.root.joinpath(*PurePosixPath(level).parts) if level else self.root
            if level not in self.present:
                if level and base.is_dir() and not base.is_symlink():
                    self._pruneTree(base)                   # the folder itself is gone
                continue
            names = self.listing.get(level, set())
            try:
                entries = list(os.scandir(base))
            except OSError:
                continue
            for entry in entries:
                if entry.name in names or entry.name.startswith('.') or entry.name in IGNORED_FOLDERS or entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    self._pruneTree(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(SUFFIXES):
                    self._pruneFile(Path(entry.path))

    def _pruneFile(self, path: Path):
        relative = path.relative_to(self.root).as_posix()
        base = self.index.get(relative)
        if base is None:
            return                                          # never copied from the machine: not ours to remove
        try:
            if _sha1(path.read_bytes()) == base:
                path.unlink()
                self.index.discard(relative)
                self.result.removed += 1
        except OSError:
            pass

    def _pruneTree(self, folder: Path):
        for current, folders, files in os.walk(folder, topdown=False, followlinks=False):
            for name in files:
                path = Path(current) / name
                if not name.startswith('.') and name.lower().endswith(SUFFIXES) and not path.is_symlink():
                    self._pruneFile(path)
            try:
                os.rmdir(current)                           # only if it is empty now
            except OSError:
                pass

    def finish(self):
        self.index.commit()


def _pull(transport: Transport, remote_path: str, script: str, wanted: List[str], mirror: Path,
          allowed: Optional[set], prune: bool = False) -> PullResult:
    result = PullResult()
    mirror = Path(mirror)
    mirror.mkdir(parents=True, exist_ok=True)
    root = mirror.resolve()
    puller = _Puller(root, result, allowed, wanted if prune else None)
    with tempfile.TemporaryFile() as errors:
        process = transport.popen(script, stdin=subprocess.PIPE, stderr=errors)
        count = 0
        try:
            try:
                process.stdin.write(('\n'.join(wanted) + '\n').encode('utf-8'))
                process.stdin.close()
            except OSError:
                pass                                        # the script ended already: its answer says why
            try:
                with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                    for member in archive:
                        count += 1
                        if count > MAX_ENTRIES:
                            result.truncated = True
                            break
                        puller.extract(archive, member)
            except tarfile.ReadError as e:
                if 'empty' not in str(e).lower():
                    raise RemoteError(f"{transport.describe()} did not send a list of files ({e}). Does a "
                                      f"login script of the account print text?") from e
        finally:
            process.stdout.close()
            process.wait()
            errors.seek(0)
            message = errors.read().decode('utf-8', errors='replace').strip()
    complete = process.returncode == 0 and not result.truncated
    if process.returncode != 0 and not result.truncated:
        puller.finish()
        if process.returncode == 3:
            raise RemoteError(f"The folder {remote_path} cannot be opened on {transport.describe()}"
                              + (f": {message}" if message else ""))
        raise RemoteError(transport.failure(process.returncode, message))
    if prune and complete:
        puller.prune()                                      # only from a complete answer: a cut one lists too little
    puller.finish()
    return result


def _inside(path: Path, root: Path) -> bool:
    """Whether a path, with the links it goes through resolved (also those that exist only in part), is in ``root``."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved == root or root in resolved.parents


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
    return _sha1(body)           # what the machine has now


# ------------------------------------------------------------------------------------------------ what a document refers to
REFERENCE_KEYS = ('run', '$import', '$include', '$mixin')


def documentReferences(path: Path) -> List[str]:
    """
    The files that a CWL document refers to, as it writes them: the ``run`` of its steps (a tool or a workflow)
    and what it imports, includes or mixes in. Nothing for a file that is not a document (or cannot be read).
    """
    try:
        from ruamel.yaml import YAML
        document = YAML(typ='safe').load(Path(path).read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return []
    found: List[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in REFERENCE_KEYS and isinstance(value, str):
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    return found


def referencedPath(document: Path, reference: str) -> Optional[str]:
    """
    Where a reference leads, as a normalised path (no ``..``) without looking at the disk: relative to the document that
    has it, without the ``#fragment``, a ``file:`` URL as the path it names. None for what is no file (``#id``, ``http:``).
    """
    reference = reference.strip()
    if not reference or reference.startswith('#'):
        return None
    parts = urlsplit(reference)
    if parts.scheme not in ('', 'file'):
        return None
    path = unquote(parts.path if parts.scheme == 'file' else reference.split('#', 1)[0])
    if not path:
        return None
    candidate = path if os.path.isabs(path) else os.path.join(os.fspath(Path(document).parent), path)
    return os.path.normpath(candidate)


@dataclass
class Dependencies:
    """The files that a document needs (what it refers to, and what those refer to)."""
    missing: List[str] = field(default_factory=list)    # in the remote folder but not in the copy: relative to the copy
    outside: List[str] = field(default_factory=list)    # outside the remote folder: they cannot be copied
    fetched: int = 0                                    # files copied from the machine for it


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
    levelFetched = pyqtSignal(str, object)       # a folder of a copy was read (the local folder, a PullResult)
    levelFailed = pyqtSignal(str, str)           # a folder of a copy could not be read, why
    dependenciesFetched = pyqtSignal(str, object)   # files that a document refers to were copied (the document, Dependencies)
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
        self._mirror_keys: List[Tuple[str, RemoteFolder]] = []   # (resolved copy, folder), for quick tests of a path
        self._fetched = set()                     # (resolved copy, folder in it) that were read in this session
        self._fetching = set()                    # the same, being read now
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
        self._indexMirrors()

    def _indexMirrors(self):
        self._mirror_keys = [(str(Path(f.mirror).resolve()), f) for f in self._folders]

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
        self._indexMirrors()
        resolved = str(Path(mirror).resolve())
        self._fetched = {entry for entry in self._fetched if entry[0] != resolved}
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

    def _locate(self, local_dir) -> Optional[Tuple[str, RemoteFolder, str]]:
        """(resolved copy, remote folder, folder relative to it) for a folder of a copy; None for any other path."""
        text = os.fspath(local_dir)
        for key, folder in self._mirror_keys:
            if text == key:
                return key, folder, ''
            if text.startswith(key + os.sep):
                return key, folder, text[len(key) + 1:].replace(os.sep, '/')
        return None

    def isRemotePath(self, local_path) -> bool:
        """True for a folder or file of the copy of a remote folder (compared as it is, like ``isUnfetched``)."""
        return self._locate(local_path) is not None

    def isUnfetched(self, local_dir) -> bool:
        """
        True for a folder of a copy that has not been read from the machine in this session: what is
        here is what an earlier session left (a folder that was never opened has no document yet).
        The path is compared as it is (the tree gives paths with their links resolved), because this is asked
        for every folder that is listed, also those of the other workspace folders.
        """
        found = self._locate(local_dir)
        return found is not None and (found[0], found[2]) not in self._fetched

    def addFolder(self, host: str, remote_path: str, callback: Callable[[Optional[RemoteFolder], Optional[Exception]], None]):
        """
        Add a remote folder: only its first level is read (the documents of the folder and the names of
        its sub-folders), the others when they are opened (``fetchLevel``). ``callback(folder, error)``
        is called when it is done; nothing is added when it fails (the machine cannot be reached, no such folder).
        """
        def work():
            transport = self.transportFor(host)
            absolute = resolvePath(transport, remote_path)
            mirror = self.mirrorFor(host, absolute)
            result = pullLevels(transport, absolute, [''], mirror)
            return absolute, mirror, result

        def done(outcome, error):
            if error is not None:
                callback(None, error)
                return
            absolute, mirror, result = outcome
            folder = next((f for f in self._folders if f.host == host and f.path == absolute), None)
            if folder is None:
                folder = RemoteFolder(host, absolute, str(Path(mirror).resolve()))     # with its links resolved
                self._folders.append(folder)
                self._indexMirrors()
            self._fetched.add((str(Path(folder.mirror).resolve()), ''))
            folder.synced = _now()
            self.save()
            self.changed.emit()
            self.synced.emit(folder.mirror, result)
            callback(folder, None)

        self.submit(work, done)

    def fetchLevel(self, local_dir) -> bool:
        """
        Read a folder of a copy from the machine (its documents and the names of its sub-folders), when it
        is opened for the first time in the session. ``levelFetched`` or ``levelFailed`` tells what became of
        it. False if nothing is to be done (not a folder of a copy, or read or being read already).
        """
        found = self._locate(os.path.realpath(local_dir))
        if found is None:
            return False
        key, folder, relative = found
        entry = (key, relative)
        if entry in self._fetched or entry in self._fetching:
            return False
        self._fetching.add(entry)
        local = os.fspath(local_dir)

        def work():
            return pullLevels(self.transportFor(folder.host), folder.path, [relative], Path(folder.mirror))

        def done(result, error):
            self._fetching.discard(entry)
            if error is not None:
                self.levelFailed.emit(local, str(error))
                return
            self._fetched.add(entry)
            self.levelFetched.emit(local, result)

        self.submit(work, done)
        return True

    def sync(self, mirror: str):
        """
        Read the remote folder again: its first level and the folders that were opened since (the others
        are read when they are opened). ``synced`` or ``syncFailed`` tells what became of it.
        """
        found = self._locate(str(Path(mirror).resolve()))
        if found is None:
            return
        key, folder, _relative = found
        levels = sorted({relative for (copy, relative) in self._fetched if copy == key} | {''})

        def work():
            return pullLevels(self.transportFor(folder.host), folder.path, levels, Path(folder.mirror))

        def done(result, error):
            if error is not None:
                self.syncFailed.emit(folder.mirror, str(error))
                return
            self._fetched.update((key, relative) for relative in levels)
            folder.synced = _now()
            self.save()
            self.synced.emit(folder.mirror, result)

        self.submit(work, done)

    def syncAll(self):
        for folder in self._folders:
            self.sync(folder.mirror)

    def dependencies(self, local_path) -> Dependencies:
        """
        What a document of a copy refers to (its steps' tools, what it imports...), and what those refer to in turn,
        that is not in the copy yet (``missing``: relative to the copy) or cannot be (``outside``: it leads out of
        the remote folder). Only the disk is looked at.
        """
        found = Dependencies()
        folder = self.folderFor(local_path)
        if folder is None:
            return found
        mirror = Path(folder.mirror).resolve()
        remote_root = folder.path.rstrip('/')
        missing, outside, seen = set(), set(), set()
        queue = [Path(local_path).resolve()]
        while queue:
            document = queue.pop()
            if document in seen:
                continue
            seen.add(document)
            for reference in documentReferences(document):
                target = referencedPath(document, reference)
                if target is None:
                    continue
                if target == remote_root or target.startswith(remote_root + '/'):    # written as a path on the machine
                    target = os.path.join(str(mirror), target[len(remote_root):].lstrip('/'))
                try:
                    relative = Path(target).relative_to(mirror)
                except ValueError:
                    outside.add(target)
                    continue
                if Path(target).is_file():
                    if target.lower().endswith(SUFFIXES):
                        queue.append(Path(target))                  # what it refers to is needed too
                else:
                    missing.add(relative.as_posix())
        found.missing, found.outside = sorted(missing), sorted(outside)
        return found

    def fetchDependencies(self, local_path, callback: Callable[[Optional[Dependencies], Optional[Exception]], None]):
        """
        Copy what a document refers to and is not here (a workflow opened from a remote folder needs its tools, which
        are in folders that were not read): a few rounds, because what is copied may refer to more files.
        ``callback(dependencies, error)`` tells what is still missing (it does not exist on the machine) or why not.
        """
        folder = self.folderFor(local_path)
        if folder is None:
            callback(Dependencies(), None)
            return

        def work():
            transport = self.transportFor(folder.host)
            asked, fetched = set(), 0
            for _round in range(MAX_DEPENDENCY_ROUNDS):
                needed = [name for name in self.dependencies(local_path).missing if name not in asked]
                if not needed:
                    break
                asked.update(needed)
                fetched += pullFiles(transport, folder.path, needed, Path(folder.mirror)).files
            result = self.dependencies(local_path)
            result.fetched = fetched
            return result

        def done(result, error):
            if error is None and result.fetched:
                self.dependenciesFetched.emit(str(local_path), result)
            callback(result, error)

        self.submit(work, done)

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
            digest = pushFile(self.transportFor(folder.host), Path(local_path), remote)
            # the machine has this now: a later sync tells what changed there since by comparing with it
            mirror = Path(folder.mirror).resolve()
            MirrorIndex.record(mirror, Path(local_path).resolve().relative_to(mirror).as_posix(), digest)

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
