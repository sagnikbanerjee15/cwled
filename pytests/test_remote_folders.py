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
def test_the_documents_of_a_folder_are_copied_and_nothing_else(tmp_path, remote_dir):
    transport = rf.LocalTransport()
    mirror = tmp_path / 'mirror'
    result = rf.pullFolder(transport, str(remote_dir), mirror)
    assert mirror_files(mirror) == ['50-workflow.cwl', 'echo.cwl', 'tools/echo-copy.cwl', 'uppercase.cwl',
                                    'with space/c d.cwl'], "no hidden folder, no node_modules, no other file, nothing large"
    assert result.files == 5 and result.unchanged == 0 and not result.truncated
    assert (mirror / 'echo.cwl').read_text() == (remote_dir / 'echo.cwl').read_text()
    assert abs((mirror / 'echo.cwl').stat().st_mtime - (remote_dir / 'echo.cwl').stat().st_mtime) < 2


def test_a_second_copy_changes_nothing_and_a_file_changed_here_is_kept(tmp_path, remote_dir):
    transport = rf.LocalTransport()
    mirror = tmp_path / 'mirror'
    rf.pullFolder(transport, str(remote_dir), mirror)
    again = rf.pullFolder(transport, str(remote_dir), mirror)
    assert again.files == 0 and again.unchanged == 5
    # a change made here, not uploaded (the machine could not be reached): it must survive a sync
    (mirror / 'echo.cwl').write_text('changed here')
    kept = rf.pullFolder(transport, str(remote_dir), mirror)
    assert kept.kept_local == ['echo.cwl'] and (mirror / 'echo.cwl').read_text() == 'changed here'
    # a change made on the machine comes in
    (remote_dir / 'uppercase.cwl').write_text('changed there')
    import os, time
    later = time.time() + 60
    os.utime(remote_dir / 'uppercase.cwl', (later, later))
    changed = rf.pullFolder(transport, str(remote_dir), mirror)
    assert changed.files == 1 and (mirror / 'uppercase.cwl').read_text() == 'changed there'


def test_what_the_remote_machine_sends_cannot_write_outside_the_copy(tmp_path):
    """An archive with paths that lead out of the folder, links and devices: only the plain file is written."""
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
                "add('dev.cwl', kind=tarfile.CHRTYPE); add('notes.txt'); tar.close()\n")
            return [sys.executable, '-c', code]

    mirror = tmp_path / 'deep' / 'mirror'
    result = rf.pullFolder(Hostile(), '/anywhere', mirror)
    assert mirror_files(mirror) == ['ok/fine.cwl'] and result.files == 1
    assert len(result.skipped) == 7
    assert not (tmp_path / 'deep' / 'escaped.cwl').exists() and not (tmp_path / 'absolute.cwl').exists()
    assert not (tmp_path / 'up.cwl').exists() and not (tmp_path / 'deep' / 'up.cwl').exists()


def test_a_folder_that_does_not_exist_and_a_machine_that_cannot_be_reached_say_why(tmp_path):
    with pytest.raises(rf.RemoteError, match='cannot be opened'):
        rf.pullFolder(rf.LocalTransport(), str(tmp_path / 'nope'), tmp_path / 'mirror')
    with pytest.raises(rf.RemoteError, match='no route to host'):
        rf.pullFolder(FailingTransport(), '/x', tmp_path / 'mirror')
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
    assert (mirror / 'echo.cwl').is_file()
    assert cwled_config['remote_folders'] == [{'host': 'dev-box', 'path': str(remote_dir.resolve()),
                                              'mirror': folder.mirror, 'synced': folder.synced}]
    assert remote.labels() == {str(mirror.resolve()): folder.label}
    assert remote.folderFor(mirror / 'tools' / 'echo-copy.cwl') == folder
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


def test_a_sync_brings_in_what_changed_on_the_machine(remote, remote_dir):
    folder = add(remote, 'dev-box', str(remote_dir))['folder']
    (remote_dir / 'brand-new.cwl').write_text('cwlVersion: v1.2\n')
    done = []
    remote.synced.connect(lambda mirror, result: done.append((mirror, result)))
    remote.sync(folder.mirror)
    wait_until(lambda: done)
    assert done[0][1].files == 1 and (Path(folder.mirror) / 'brand-new.cwl').is_file()
    failed = []
    remote.syncFailed.connect(lambda mirror, why: failed.append(why))
    remote.transportFor = lambda host: FailingTransport()
    remote.sync(folder.mirror)
    wait_until(lambda: failed)
    assert 'no route to host' in failed[0]


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
