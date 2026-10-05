"""
Folders of remote machines: the copying with ssh (here with a shell on this machine instead of ssh, so the
same scripts run without a network), the list of remote folders, the dialogs and the windows.
"""
import shutil
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

import data
import remoteFolders as rf
from conftest import FIXTURES
from qt_helpers import pump, wait_until
from RemoteFolderDialog import RemoteFolderBrowser, RemoteFolderDialog

CONFIG = """\
Host dev-box
    HostName ec2-3-90-1-2.compute-1.amazonaws.com
    User ec2-user
    IdentityFile ~/.ssh/dev.pem

Host build
    HostName ec2-4-4-4-4.compute-1.amazonaws.com
    User ubuntu

Host laptop
    HostName 192.168.1.20
"""


@pytest.fixture
def remote_dir(tmp_path):
    """The "remote machine": a folder with documents (the test documents), hidden and other files."""
    root = tmp_path / 'remote' / 'home' / 'ec2-user' / 'project'
    (root / 'tools').mkdir(parents=True)
    (root / '.hidden').mkdir()
    (root / 'node_modules' / 'x').mkdir(parents=True)
    (root / 'with space').mkdir()
    for name in ('echo.cwl', 'uppercase.cwl', '50-workflow.cwl'):
        shutil.copy(FIXTURES / name, root / name)
    shutil.copy(FIXTURES / 'echo.cwl', root / 'tools' / 'echo-copy.cwl')
    shutil.copy(FIXTURES / 'echo.cwl', root / 'with space' / 'c d.cwl')
    shutil.copy(FIXTURES / 'echo.cwl', root / '.hidden' / 'hidden.cwl')
    shutil.copy(FIXTURES / 'echo.cwl', root / 'node_modules' / 'x' / 'module.cwl')
    (root / 'notes.txt').write_text('not a document')
    (root / 'huge.json').write_bytes(b'a' * (rf.MAX_FILE_BYTES + 10))
    return root


def mirror_files(mirror: Path):
    return sorted(str(path.relative_to(mirror)) for path in mirror.rglob('*') if path.is_file())


class FailingTransport(rf.Transport):
    """A machine that cannot be reached."""

    def argv(self, script):
        return ['sh', '-c', 'echo "no route to host" >&2; exit 255']

    def describe(self):
        return 'the failing host'


# ------------------------------------------------------------------------------------------------ the copying
def test_one_level_is_copied_at_a_time_documents_and_the_names_of_the_folders(tmp_path, remote_dir):
    transport = rf.LocalTransport()
    mirror = tmp_path / 'mirror'
    first = rf.pullLevels(transport, str(remote_dir), [''], mirror)
    assert mirror_files(mirror) == ['50-workflow.cwl', 'echo.cwl', 'uppercase.cwl'], "only the documents of this level"
    assert sorted(p.name for p in mirror.iterdir() if p.is_dir()) == ['tools', 'with space'], \
        "the folders are there, empty; not the hidden one and not node_modules"
    assert list((mirror / 'tools').iterdir()) == []
    assert first.files == 3 and first.folders == 2 and not first.truncated
    assert (mirror / 'echo.cwl').read_text() == (remote_dir / 'echo.cwl').read_text()
    assert abs((mirror / 'echo.cwl').stat().st_mtime - (remote_dir / 'echo.cwl').stat().st_mtime) < 2
    # a folder is read when it is opened; several can be read at once
    second = rf.pullLevels(transport, str(remote_dir), ['tools', 'with space'], mirror)
    assert second.files == 2 and mirror_files(mirror) == ['50-workflow.cwl', 'echo.cwl', 'tools/echo-copy.cwl',
                                                           'uppercase.cwl', 'with space/c d.cwl']
    assert not (mirror / '.hidden').exists() and not (mirror / 'node_modules').exists()
    assert 'huge.json' not in str(mirror_files(mirror)) and 'notes.txt' not in str(mirror_files(mirror))


def test_a_second_copy_changes_nothing_and_a_file_changed_here_is_kept(tmp_path, remote_dir):
    transport = rf.LocalTransport()
    mirror = tmp_path / 'mirror'
    rf.pullLevels(transport, str(remote_dir), [''], mirror)
    again = rf.pullLevels(transport, str(remote_dir), [''], mirror)
    assert again.files == 0 and again.unchanged == 3
    # a change made here, not uploaded (the machine could not be reached): it must survive a sync
    (mirror / 'echo.cwl').write_text('changed here')
    kept = rf.pullLevels(transport, str(remote_dir), [''], mirror)
    assert kept.kept_local == ['echo.cwl'] and (mirror / 'echo.cwl').read_text() == 'changed here'
    # a change made on the machine comes in
    (remote_dir / 'uppercase.cwl').write_text('changed there')
    import os, time
    later = time.time() + 60
    os.utime(remote_dir / 'uppercase.cwl', (later, later))
    changed = rf.pullLevels(transport, str(remote_dir), [''], mirror)
    assert changed.files == 1 and (mirror / 'uppercase.cwl').read_text() == 'changed there'


def test_what_the_remote_machine_sends_cannot_write_outside_the_copy(tmp_path):
    """An archive with paths that lead out of the folder, links and devices: only the plain entries are written."""
    class Hostile(rf.Transport):
        def argv(self, script):
            code = (
                "import io, sys, tarfile\n"
                "tar = tarfile.open(fileobj=sys.stdout.buffer, mode='w|')\n"
                "def add(name, body=b'x', kind=tarfile.REGTYPE, link=''):\n"
                "    info = tarfile.TarInfo(name); info.type = kind; info.linkname = link\n"
                "    info.size = len(body) if kind == tarfile.REGTYPE else 0\n"
                "    tar.addfile(info, io.BytesIO(body) if kind == tarfile.REGTYPE else None)\n"
                f"add('../escaped.cwl'); add('{tmp_path}/absolute.cwl'); add('a/../../up.cwl'); add('ok/fine.cwl', b'fine')\n"
                "add('sym.cwl', kind=tarfile.SYMTYPE, link='/etc/hosts'); add('hard.cwl', kind=tarfile.LNKTYPE, link='ok/fine.cwl')\n"
                "add('dev.cwl', kind=tarfile.CHRTYPE); add('notes.txt')\n"
                "add('../newdir/x.cwl'); add('../evil-folder', kind=tarfile.DIRTYPE); add('ok-folder', kind=tarfile.DIRTYPE)\n"
                "add('linkdir', kind=tarfile.SYMTYPE, link='/'); add('link/pwned.cwl'); tar.close()\n")
            return [sys.executable, '-c', code]

    mirror = tmp_path / 'deep' / 'mirror'
    outside = tmp_path / 'outside'
    outside.mkdir()
    mirror.mkdir(parents=True)
    (mirror / 'link').symlink_to(outside)               # a link in the copy that leads out of it
    result = rf.pullLevels(Hostile(), '/anywhere', [''], mirror)
    assert mirror_files(mirror) == ['ok/fine.cwl'] and result.files == 1 and result.folders == 1
    assert (mirror / 'ok-folder').is_dir()
    assert len(result.skipped) == 11
    for escaped in (tmp_path / 'deep' / 'escaped.cwl', tmp_path / 'absolute.cwl', tmp_path / 'up.cwl',
                    tmp_path / 'deep' / 'up.cwl', tmp_path / 'deep' / 'newdir', tmp_path / 'deep' / 'evil-folder',
                    outside / 'pwned.cwl'):
        assert not escaped.exists(), f"{escaped} was written"


def test_a_folder_that_does_not_exist_and_a_machine_that_cannot_be_reached_say_why(tmp_path):
    with pytest.raises(rf.RemoteError, match='cannot be opened'):
        rf.pullLevels(rf.LocalTransport(), str(tmp_path / 'nope'), [''], tmp_path / 'mirror')
    with pytest.raises(rf.RemoteError, match='no route to host'):
        rf.pullLevels(FailingTransport(), '/x', [''], tmp_path / 'mirror')
    with pytest.raises(rf.RemoteError, match='no route to host'):
        rf.listDirectory(FailingTransport(), '~')


def test_folders_are_listed_and_paths_are_resolved(tmp_path, remote_dir, monkeypatch):
    transport = rf.LocalTransport()
    link = tmp_path / 'link'
    link.symlink_to(remote_dir)
    assert rf.resolvePath(transport, str(link)) == str(remote_dir.resolve())
    path, entries = rf.listDirectory(transport, str(link))
    assert path == str(remote_dir.resolve())
    assert [(e.name, e.is_dir) for e in entries if e.is_dir] == [('.hidden', True), ('node_modules', True),
                                                                  ('tools', True), ('with space', True)]
    assert 'echo.cwl' in [e.name for e in entries if not e.is_dir], "folders first, then the files"
    monkeypatch.setenv('HOME', str(remote_dir))
    assert rf.resolvePath(transport, '~') == str(remote_dir.resolve())
    assert rf.resolvePath(transport, '~/tools') == str((remote_dir / 'tools').resolve())


def test_a_file_is_written_on_the_remote_machine_keeping_the_old_mode(tmp_path, remote_dir):
    transport = rf.LocalTransport()
    local = tmp_path / 'new.cwl'
    local.write_text('cwlVersion: v1.2\n')
    target = remote_dir / 'a folder that is new' / 'new.cwl'
    rf.pushFile(transport, local, str(target))
    assert target.read_text() == 'cwlVersion: v1.2\n'
    existing = remote_dir / 'echo.cwl'
    existing.chmod(0o640)
    rf.pushFile(transport, local, str(existing))
    assert existing.read_text() == 'cwlVersion: v1.2\n' and (existing.stat().st_mode & 0o777) == 0o640
    assert not list(remote_dir.glob('*.cwled-part*')), "no temporary file is left"


def test_ssh_is_started_with_the_right_arguments(monkeypatch):
    transport = rf.SshTransport('dev-box', executable='/usr/bin/ssh')
    argv = transport.argv("echo 'quoted' && ls")
    assert argv[0] == '/usr/bin/ssh' and 'BatchMode=yes' in argv, "it never asks for a password"
    assert argv[-3:-1] == ['--', 'dev-box'] and argv[-1].startswith('sh -c '), "the host cannot be taken for an option"
    assert "'\"'\"'quoted'\"'\"'" in argv[-1], "the script is quoted for the remote shell"
    for bad in ('-oProxyCommand=evil', 'a b', ''):
        with pytest.raises(rf.RemoteError):
            rf.SshTransport(bad)
    assert 'Host key verification failed' in transport.failure(255, 'Host key verification failed.')
    assert 'ssh-add' in transport.failure(255, 'Permission denied (publickey).')


# ------------------------------------------------------------------------------------------------ the folders
@pytest.fixture
def remote(cwled_config, qapp, tmp_path):
    manager = rf.RemoteFolders(root=tmp_path / 'mirrors', transport_factory=lambda host: rf.LocalTransport())
    yield manager
    manager.deleteLater()


def add(manager, host, path):
    outcome = {}
    manager.addFolder(host, path, lambda folder, error: outcome.update(folder=folder, error=error))
    wait_until(lambda: outcome, message="the folder was not added")
    return outcome


def test_adding_a_folder_copies_it_remembers_it_and_names_the_root(remote, remote_dir, cwled_config):
    changes = []
    remote.changed.connect(lambda: changes.append(1))
    outcome = add(remote, 'dev-box', str(remote_dir))
    folder = outcome['folder']
    assert outcome['error'] is None and changes
    assert folder.label == f"dev-box:{remote_dir.resolve()}"
    mirror = Path(folder.mirror)
    assert mirror.relative_to(remote.root).parts[0] == 'dev-box', "one folder per host, then the path on the host"
    assert mirror_files(mirror) == ['50-workflow.cwl', 'echo.cwl', 'uppercase.cwl'], "only the first level is read"
    assert cwled_config['remote_folders'] == [{'host': 'dev-box', 'path': str(remote_dir.resolve()),
                                              'mirror': folder.mirror, 'synced': folder.synced}]
    assert remote.labels() == {str(mirror.resolve()): folder.label}
    assert remote.folderFor(mirror / 'tools' / 'echo-copy.cwl') == folder
    assert not remote.isUnfetched(mirror) and remote.isUnfetched(mirror / 'tools'), "the root was read, its folders were not"
    assert not remote.isUnfetched(remote_dir), "a folder that is not in a copy is no concern of ours"
    assert remote.folderFor(remote_dir / 'echo.cwl') is None
    # adding it again gives the same folder, and a new manager reads the list from the configuration
    assert add(remote, 'dev-box', str(remote_dir))['folder'].mirror == folder.mirror and len(remote.folders()) == 1
    again = rf.RemoteFolders(root=remote.root, transport_factory=lambda host: rf.LocalTransport())
    assert [f.label for f in again.folders()] == [folder.label]


def test_nothing_is_added_when_the_machine_cannot_be_reached_or_has_no_such_folder(remote, tmp_path):
    outcome = add(remote, 'dev-box', str(tmp_path / 'nothing here'))
    assert outcome['folder'] is None and isinstance(outcome['error'], rf.RemoteError)
    assert remote.folders() == [] and not list(remote.root.rglob('*.cwl'))
    remote.transportFor = lambda host: FailingTransport()
    assert 'no route to host' in str(add(remote, 'dev-box', '/x')['error'])
    assert remote.folders() == []


def test_a_folder_is_read_when_it_is_opened_and_only_once(remote, remote_dir):
    folder = add(remote, 'dev-box', str(remote_dir))['folder']
    mirror = Path(folder.mirror)
    assert remote.isUnfetched(mirror / 'tools') and list((mirror / 'tools').iterdir()) == []
    read, failed = [], []
    remote.levelFetched.connect(lambda path, result: read.append((path, result)))
    remote.levelFailed.connect(lambda path, why: failed.append((path, why)))
    assert remote.fetchLevel(mirror / 'tools')
    assert not remote.fetchLevel(mirror / 'tools'), "it is being read: no second request"
    wait_until(lambda: read)
    assert read[0][0] == str(mirror / 'tools') and read[0][1].files == 1
    assert (mirror / 'tools' / 'echo-copy.cwl').is_file() and not remote.isUnfetched(mirror / 'tools')
    assert not remote.fetchLevel(mirror / 'tools'), "and not again once it was read"
    assert remote.isUnfetched(mirror / 'with space'), "the other folders were not touched"
    assert not (mirror / 'with space' / 'c d.cwl').exists()
    assert not remote.fetchLevel(remote_dir / 'tools'), "only folders of a copy are read"
    # when the machine cannot be reached it is said, and the folder can be tried again
    remote.transportFor = lambda host: FailingTransport()
    assert remote.fetchLevel(mirror / 'with space')
    wait_until(lambda: failed)
    assert 'no route to host' in failed[0][1] and remote.isUnfetched(mirror / 'with space')
    remote.transportFor = lambda host: rf.LocalTransport()
    assert remote.fetchLevel(mirror / 'with space')
    wait_until(lambda: len(read) == 2)
    assert (mirror / 'with space' / 'c d.cwl').is_file()


def test_adding_a_large_folder_reads_one_level_only(remote, tmp_path):
    big = tmp_path / 'remote' / 'big'
    for number in range(60):
        folder = big / f'sample-{number:02d}' / 'deep' / 'deeper'
        folder.mkdir(parents=True)
        for document in range(5):
            (folder / f'doc-{document}.cwl').write_text('cwlVersion: v1.2\n')
    (big / 'top.cwl').write_text('cwlVersion: v1.2\n')
    result = {}
    remote.synced.connect(lambda mirror, pulled: result.update(pulled=pulled))
    folder = add(remote, 'dev-box', str(big))['folder']
    mirror = Path(folder.mirror)
    assert mirror_files(mirror) == ['top.cwl'], "the 300 documents below are not read yet"
    assert len([p for p in mirror.iterdir() if p.is_dir()]) == 60 and result['pulled'].folders == 60


def test_a_sync_reads_again_the_folders_that_were_opened_and_no_others(remote, remote_dir):
    folder = add(remote, 'dev-box', str(remote_dir))['folder']
    mirror = Path(folder.mirror)
    remote.fetchLevel(mirror / 'tools')
    wait_until(lambda: not remote.isUnfetched(mirror / 'tools'))
    (remote_dir / 'brand-new.cwl').write_text('cwlVersion: v1.2\n')
    (remote_dir / 'tools' / 'new-tool.cwl').write_text('cwlVersion: v1.2\n')
    (remote_dir / 'with space' / 'never-opened.cwl').write_text('cwlVersion: v1.2\n')
    done = []
    remote.synced.connect(lambda path, result: done.append((path, result)))
    remote.sync(folder.mirror)
    wait_until(lambda: done)
    assert (mirror / 'brand-new.cwl').is_file() and (mirror / 'tools' / 'new-tool.cwl').is_file()
    assert not (mirror / 'with space' / 'never-opened.cwl').exists(), "a folder that was never opened is not read by a sync"
    failed = []
    remote.syncFailed.connect(lambda path, why: failed.append(why))
    remote.transportFor = lambda host: FailingTransport()
    remote.sync(folder.mirror)
    wait_until(lambda: failed)
    assert 'no route to host' in failed[0]


def test_a_new_session_reads_a_folder_again_when_it_is_opened(remote, remote_dir):
    folder = add(remote, 'dev-box', str(remote_dir))['folder']
    mirror = Path(folder.mirror)
    remote.fetchLevel(mirror / 'tools')
    wait_until(lambda: not remote.isUnfetched(mirror / 'tools'))
    later = rf.RemoteFolders(root=remote.root, transport_factory=lambda host: rf.LocalTransport())
    assert later.isUnfetched(mirror) and later.isUnfetched(mirror / 'tools'), "what was read before is what is shown, not what is current"
    assert (mirror / 'tools' / 'echo-copy.cwl').is_file()
    seen = []
    later.levelFetched.connect(lambda path, result: seen.append(result))
    assert later.fetchLevel(mirror / 'tools')
    wait_until(lambda: seen)
    assert seen[0].unchanged == 1 and not later.isUnfetched(mirror / 'tools')


def test_an_upload_writes_the_file_on_the_machine_and_a_failure_is_reported(remote, remote_dir):
    folder = add(remote, 'dev-box', str(remote_dir))['folder']
    local = Path(folder.mirror) / 'tools' / 'echo-copy.cwl'
    local.write_text('cwlVersion: v1.2\n# saved here\n')
    uploaded, failed = [], []
    remote.uploaded.connect(lambda path, label: uploaded.append(label))
    remote.uploadFailed.connect(lambda path, why: failed.append(why))
    assert remote.upload(local) and not remote.upload(remote_dir / 'echo.cwl'), "only files of a copy go anywhere"
    wait_until(lambda: uploaded)
    assert (remote_dir / 'tools' / 'echo-copy.cwl').read_text().endswith('# saved here\n')
    assert uploaded == [f"dev-box:{remote_dir.resolve()}/tools/echo-copy.cwl"]
    remote.transportFor = lambda host: FailingTransport()
    assert remote.upload(local)
    wait_until(lambda: failed)
    assert 'no route to host' in failed[0] and 'echo-copy.cwl' in failed[0]


# ------------------------------------------------------------------------------------------------ the dialogs
@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / 'ssh-config'
    path.write_text(CONFIG)
    return path


def rows(dialog):
    return [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]


def test_the_dialog_lists_the_ec2_instances_of_the_ssh_configuration(window, config_file):
    dialog = RemoteFolderDialog(window.remote, window, config_path=config_file)
    assert rows(dialog) == ['dev-box', 'build']
    assert 'laptop' not in rows(dialog) and '2 EC2 instances among the 3 hosts' in dialog.config_label.text()
    assert dialog.table.item(0, 3).text() == 'yes' and 'AWS name' in dialog.table.item(0, 3).toolTip()
    dialog.all_check.setChecked(True)
    assert sorted(rows(dialog)) == ['build', 'dev-box', 'laptop']
    dialog.filter_edit.setText('192.168')
    assert rows(dialog) == ['laptop']
    dialog.filter_edit.setText('')
    assert not dialog.add_button.isEnabled(), "nothing is selected yet"
    dialog.table.selectRow(rows(dialog).index('laptop'))
    assert dialog.host() == 'laptop' and dialog.add_button.isEnabled()
    dialog.other_edit.setText('me@elsewhere')
    assert dialog.host() == 'me@elsewhere', "a host that is typed is used instead of the selection"


def test_the_dialog_says_so_when_there_is_no_configuration_or_no_ec2_instance(window, tmp_path):
    missing = RemoteFolderDialog(window.remote, window, config_path=tmp_path / 'missing')
    assert 'There is no SSH configuration' in missing.config_label.text()
    assert rows(missing) == []
    plain = tmp_path / 'plain'
    plain.write_text("Host laptop\n    HostName 192.168.1.20\n")
    dialog = RemoteFolderDialog(window.remote, window, config_path=plain)
    assert 'looks like an EC2 instance' in dialog.config_label.text() and dialog.all_check.isChecked()
    assert rows(dialog) == ['laptop']


def test_the_connection_is_tested_and_the_folder_browser_goes_down_and_up(window, config_file, remote_dir, monkeypatch):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    dialog = RemoteFolderDialog(window.remote, window, config_path=config_file)
    dialog.table.selectRow(0)
    monkeypatch.setenv('HOME', str(remote_dir))
    dialog.testConnection()
    wait_until(lambda: dialog.path_edit.text())
    assert 'Connected to' in dialog.status.text() and dialog.path_edit.text() == str(remote_dir.resolve())

    browser = RemoteFolderBrowser(window.remote, 'dev-box', str(remote_dir), window)
    wait_until(lambda: browser.list.count())
    names = [browser.list.item(i).text() for i in range(browser.list.count())]
    assert names[:4] == ['.hidden', 'node_modules', 'tools', 'with space'] and browser.select_button.isEnabled()
    browser._onDoubleClicked(browser.list.item(names.index('tools')))
    wait_until(lambda: browser.path.endswith('/tools'))
    assert [browser.list.item(i).text() for i in range(browser.list.count())] == ['echo-copy.cwl']
    browser.goUp()
    wait_until(lambda: not browser.path.endswith('/tools'))
    browser._choose()
    assert browser.selected == str(remote_dir.resolve())


def test_adding_a_remote_folder_from_the_dialog_shows_it_in_the_workspace_panel(window, config_file, remote_dir):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    dialog = RemoteFolderDialog(window.remote, window, config_path=config_file)
    dialog.table.selectRow(rows(dialog).index('dev-box'))
    dialog.path_edit.setText(str(remote_dir))
    dialog.addFolder()
    wait_until(lambda: dialog.folder is not None, message=dialog.status.text())
    window.addWorkspaceFolder(dialog.folder.mirror)
    pump(4)
    panel = window.sidebar.workspace_panel
    roots = [panel.model.index(row, 0).data() for row in range(panel.model.rowCount())]
    assert f"dev-box:{remote_dir.resolve()}" in roots, roots
    assert str(Path(dialog.folder.mirror).resolve()) in window.workspace.folders()
    # a failure stays in the dialog, which stays open
    window.remote.transportFor = lambda host: FailingTransport()
    failing = RemoteFolderDialog(window.remote, window, config_path=config_file)
    failing.table.selectRow(0)
    failing.addFolder()
    wait_until(lambda: not failing._busy)
    assert failing.folder is None and 'no route to host' in failing.status.text()


def test_saving_a_document_of_a_remote_folder_uploads_it(window, config_file, remote_dir, monkeypatch):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    folder = add(window.remote, 'dev-box', str(remote_dir))['folder']
    window.addWorkspaceFolder(folder.mirror)
    path = Path(folder.mirror) / 'echo.cwl'
    window.openDocument(str(path), host=window)
    pump(10)
    document = next(doc for doc in window.open_windows.values() if doc.file_path and Path(str(doc.file_path)).name == 'echo.cwl')
    document.cwl_tool.label = 'Saved from CWLed'
    document.saveFile(file_path=str(path))
    wait_until(lambda: 'Saved from CWLed' in (remote_dir / 'echo.cwl').read_text(), message="the file was not uploaded")
    wait_until(lambda: 'Saved on' in window.statusBar().currentMessage(), message=window.statusBar().currentMessage())
    # when the machine cannot be reached the user is told, and the copy here keeps the change
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, text, *args, **kwargs: warnings.append((title, text)))
    window.remote.transportFor = lambda host: FailingTransport()
    document.cwl_tool.label = 'Saved while offline'
    document.saveFile(file_path=str(path))
    wait_until(lambda: warnings)
    assert warnings[0][0] == 'Upload to Remote' and 'no route to host' in warnings[0][1]
    assert 'Saved while offline' in path.read_text() and 'Saved while offline' not in (remote_dir / 'echo.cwl').read_text()


def test_the_root_menu_and_the_menu_bar_offer_the_remote_folders(window, remote_dir):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    folder = add(window.remote, 'dev-box', str(remote_dir))['folder']
    window.addWorkspaceFolder(folder.mirror)
    pump(4)
    panel = window.sidebar.workspace_panel
    root = next(panel.model.index(row, 0) for row in range(panel.model.rowCount())
                if panel.model.index(row, 0).data().startswith('dev-box:'))
    menu = panel._contextMenu(root)
    assert [a.text() for a in menu.actions()] == ['Sync from Remote', 'Remove from Workspace']
    local_root = next(panel.model.index(row, 0) for row in range(panel.model.rowCount())
                      if not panel.model.index(row, 0).data().startswith('dev-box:'))
    assert [a.text() for a in panel._contextMenu(local_root).actions()] == ['Remove from Workspace']
    assert 'Add a Remote Folder (SSH)...' in [a.text() for a in panel._contextMenu(panel.model.index(-1, -1)).actions()]
    file_menu = window.file_menu
    entries = [action.text() for action in file_menu.actions()]
    assert 'Sync Remote Folders' in entries
    assert not any('Remote Folder' in entry and 'Sync' not in entry for entry in entries), "the option is next to Add a Folder"
    # "Add a Remote Folder (SSH)" is right below "Add a Folder" in the side panel, and also on the Welcome tab
    # (the dialog itself is replaced by a recorder: it would wait for an answer)
    seen_hosts = []
    window.addRemoteFolder = lambda host=None: seen_hosts.append(host)
    assert panel.add_remote_link.text() == 'Add a Remote Folder (SSH)'
    from PyQt6.QtCore import QPoint
    above = panel.add_folder_link.mapTo(panel, QPoint(0, 0)).y()
    below = panel.add_remote_link.mapTo(panel, QPoint(0, 0)).y()
    assert 0 < above < below < above + 3 * panel.add_folder_link.height(), "right below Add a Folder"
    panel.add_remote_link.click()
    assert seen_hosts == [window]
    window.welcome_add_remote_button.click()
    assert seen_hosts == [window, window], "the Welcome tab asks for a remote folder for this window's workspace too"
    # the sync of the root menu
    (remote_dir / 'later.cwl').write_text('cwlVersion: v1.2\n')
    seen = []
    window.remote.synced.connect(lambda mirror, result: seen.append(result))
    panel.syncRemoteFolderRequested.emit(folder.mirror)
    wait_until(lambda: seen)
    assert (Path(folder.mirror) / 'later.cwl').is_file() and 'copied' in window.statusBar().currentMessage()


def children(panel, index):
    return [panel.model.index(row, 0, index).data() for row in range(panel.model.rowCount(index))]


def remote_root(panel):
    return next(panel.model.index(row, 0) for row in range(panel.model.rowCount())
                if (panel.model.index(row, 0).data() or '').startswith('dev-box:'))


def test_a_folder_of_the_machine_is_read_when_it_is_expanded_in_the_panel(window, remote_dir):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    folder = add(window.remote, 'dev-box', str(remote_dir))['folder']
    window.addWorkspaceFolder(folder.mirror)
    pump(4)
    panel = window.sidebar.workspace_panel
    root = remote_root(panel)
    panel.tree_view.expand(root)
    assert children(panel, root) == ['tools', 'with space', '50-workflow.cwl', 'echo.cwl', 'uppercase.cwl'], \
        "the first level, with its folders although they are empty here (nothing was read below them)"
    tools = next(panel.model.index(row, 0, root) for row in range(panel.model.rowCount(root))
                 if panel.model.index(row, 0, root).data() == 'tools')
    panel.tree_view.expand(tools)
    assert children(panel, tools) == ['Loading...'], "while the machine is asked"
    wait_until(lambda: children(panel, tools) == ['echo-copy.cwl'], message=str(children(panel, tools)))
    # collapsing and expanding again asks nothing more: it was read
    asked = []
    panel.remoteFolderOpened.connect(asked.append)
    panel.tree_view.collapse(tools)
    panel.tree_view.expand(tools)
    pump(3)
    assert asked == [] and children(panel, tools) == ['echo-copy.cwl']


def test_a_folder_that_cannot_be_read_says_so_and_is_tried_again_when_expanded_again(window, remote_dir):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    folder = add(window.remote, 'dev-box', str(remote_dir))['folder']
    window.addWorkspaceFolder(folder.mirror)
    pump(4)
    panel = window.sidebar.workspace_panel
    root = remote_root(panel)
    panel.tree_view.expand(root)
    space = next(panel.model.index(row, 0, root) for row in range(panel.model.rowCount(root))
                 if panel.model.index(row, 0, root).data() == 'with space')
    window.remote.transportFor = lambda host: FailingTransport()
    panel.tree_view.expand(space)
    wait_until(lambda: any(text.startswith('Could not be read') for text in children(panel, space)))
    assert children(panel, space) == ['Could not be read: no route to host']
    window.remote.transportFor = lambda host: rf.LocalTransport()
    panel.tree_view.collapse(space)
    panel.tree_view.expand(space)
    wait_until(lambda: children(panel, space) == ['c d.cwl'], message=str(children(panel, space)))


def test_showing_a_file_in_the_panel_does_not_read_the_folders_on_the_way(window, remote_dir):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    folder = add(window.remote, 'dev-box', str(remote_dir))['folder']
    mirror = Path(folder.mirror)
    window.remote.fetchLevel(mirror / 'tools')
    wait_until(lambda: not window.remote.isUnfetched(mirror / 'tools'))
    window.addWorkspaceFolder(folder.mirror)
    pump(4)
    later = rf.RemoteFolders(root=window.remote.root, transport_factory=lambda host: rf.LocalTransport())
    window.sidebar.workspace_panel.remote_unfetched = later.isUnfetched     # as in a new session: nothing is read yet
    asked = []
    window.sidebar.workspace_panel.remoteFolderOpened.connect(asked.append)
    assert window.sidebar.workspace_panel.revealFile(mirror / 'tools' / 'echo-copy.cwl')
    pump(3)
    assert asked == [], "revealing is not the user opening folders: no network"


def test_the_browser_chooses_the_folder_that_is_highlighted_else_the_one_shown(window, remote_dir):
    window.remote.transportFor = lambda host: rf.LocalTransport()
    parent = remote_dir.parent
    browser = RemoteFolderBrowser(window.remote, 'dev-box', str(parent), window)
    wait_until(lambda: browser.list.count())
    assert browser.select_button.text() == 'Choose this folder'
    item = next(browser.list.item(i) for i in range(browser.list.count()) if browser.list.item(i).text() == remote_dir.name)
    browser.list.setCurrentItem(item)                                  # a click, not a double click
    assert browser.select_button.text() == f"Choose \u201c{remote_dir.name}\u201d"
    browser._choose()
    assert browser.selected == str(remote_dir.resolve()), "the highlighted folder, not the one that is shown"
    shown = RemoteFolderBrowser(window.remote, 'dev-box', str(remote_dir), window)
    wait_until(lambda: shown.list.count())
    shown._choose()
    assert shown.selected == str(remote_dir.resolve()), "nothing highlighted: the folder that is shown"
