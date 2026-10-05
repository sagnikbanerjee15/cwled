"""
The dialogs to add a folder of a remote machine to the workspace (see remoteFolders.py).

``RemoteFolderDialog`` lists the hosts of ``~/.ssh/config``, the EC2 instances first, asks for a
folder on the chosen one (typed, or picked in ``RemoteFolderBrowser``) and copies it.
"""
import logging
import os
from pathlib import Path, PurePosixPath
from typing import List, Optional

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

import theme
from remoteFolders import RemoteFolder, RemoteFolders, RemoteError, listDirectory, resolvePath
from sshConfig import EC2, PROBABLY_EC2, SshConfig, SshHost, readSshConfig

logger = logging.getLogger(__name__)

COLUMNS = ['Name', 'Host name', 'User', 'EC2 instance']


def _setStatus(label: QLabel, text: str, error: bool = False):
    label.setText(text)
    label.setProperty('error', error)
    label.setStyleSheet(f"color: {theme.RED};" if error else "")
    label.setVisible(bool(text))


class RemoteFolderBrowser(QDialog):
    """Pick a folder of a remote machine: the folders are listed with ssh, a double click opens one."""

    def __init__(self, remote: RemoteFolders, host: str, start: str = '~', parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Choose a folder on {host}")
        self.setMinimumSize(480, 420)
        self.remote = remote
        self.host = host
        self.path = ''                         # the folder that is shown (absolute)
        self.selected: Optional[str] = None    # the folder that was chosen

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.up_button = QPushButton("Up")
        self.up_button.setToolTip("The folder above")
        self.up_button.clicked.connect(self.goUp)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/path/on/the/remote/machine")
        self.path_edit.returnPressed.connect(lambda: self.load(self.path_edit.text().strip()))
        row.addWidget(self.up_button)
        row.addWidget(self.path_edit, 1)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._onDoubleClicked)
        layout.addWidget(self.list, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.select_button = buttons.addButton("Choose this folder", QDialogButtonBox.ButtonRole.AcceptRole)
        self.select_button.setEnabled(False)
        buttons.accepted.connect(self._choose)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.load(start)

    def load(self, path: str):
        """Show a folder of the remote machine."""
        _setStatus(self.status, f"Listing {path or '~'} ...")
        self.list.setEnabled(False)
        self.select_button.setEnabled(False)

        def work():
            return listDirectory(self.remote.transportFor(self.host), path)

        def done(result, error):
            if sip.isdeleted(self):
                return
            self.list.setEnabled(True)
            if error is not None:
                _setStatus(self.status, str(error), error=True)
                return
            self.path, entries = result
            self.path_edit.setText(self.path)
            self.list.clear()
            for entry in entries:
                if entry.is_dir:
                    item = QListWidgetItem(theme.icon('folder'), entry.name)
                    item.setData(Qt.ItemDataRole.UserRole, True)
                else:
                    item = QListWidgetItem(theme.icon('file-o', color=theme.SMOKE), entry.name)
                    item.setFlags(Qt.ItemFlag.NoItemFlags)           # shown for orientation only
                self.list.addItem(item)
            self.select_button.setEnabled(True)
            self.up_button.setEnabled(self.path not in ('', '/'))
            _setStatus(self.status, "")

        self.remote.submit(work, done)

    def goUp(self):
        if self.path:
            self.load(str(PurePosixPath(self.path).parent))

    def _onDoubleClicked(self, item: QListWidgetItem):
        if item.data(Qt.ItemDataRole.UserRole):
            self.load(str(PurePosixPath(self.path) / item.text()))

    def _choose(self):
        self.selected = self.path
        self.accept()


class RemoteFolderDialog(QDialog):
    """
    Add a folder of a remote machine to the workspace. The hosts are read from the SSH configuration
    (``~/.ssh/config``): the EC2 instances are listed, and all the other hosts too when asked for.
    On success ``folder`` is the ``RemoteFolder`` that was added.
    """

    def __init__(self, remote: RemoteFolders, parent=None, config_path: Optional[os.PathLike] = None):
        super().__init__(parent)
        self.setWindowTitle("Add a Remote Folder (SSH)")
        self.setMinimumSize(760, 560)
        self.remote = remote
        self.config_path = config_path
        self.config: SshConfig = SshConfig(path=Path())
        self.folder: Optional[RemoteFolder] = None
        self._busy = False

        layout = QVBoxLayout(self)
        intro = QLabel("The CWL documents of a folder on another machine are copied to this computer and "
                       "shown in the Workspace panel; saving a document uploads it again. The connection is made "
                       "with ssh, with the settings of your SSH configuration.")
        intro.setWordWrap(True)
        intro.setProperty('muted', True)
        layout.addWidget(intro)

        # the hosts
        self.config_label = QLabel()
        self.config_label.setWordWrap(True)
        layout.addWidget(self.config_label)
        filter_row = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter the hosts")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.fillTable)
        self.all_check = QCheckBox("Show all hosts")
        self.all_check.setToolTip("Also list the hosts that do not look like EC2 instances")
        self.all_check.toggled.connect(self.fillTable)
        self.reload_button = QPushButton("Reload")
        self.reload_button.setToolTip("Read the SSH configuration again")
        self.reload_button.clicked.connect(self.reloadHosts)
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.all_check)
        filter_row.addWidget(self.reload_button)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._onSelectionChanged)
        layout.addWidget(self.table, 1)

        other_row = QHBoxLayout()
        other_row.addWidget(QLabel("Another host:"))
        self.other_edit = QLineEdit()
        self.other_edit.setPlaceholderText("user@host, or a name known to ssh (used instead of the selection)")
        self.other_edit.textChanged.connect(self._updateButtons)
        other_row.addWidget(self.other_edit, 1)
        layout.addLayout(other_row)

        # the folder
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Folder on the host:"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("~  (the home folder), or /path/to/the/folder")
        self.path_edit.textChanged.connect(self._updateButtons)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self.testConnection)
        folder_row.addWidget(self.path_edit, 1)
        folder_row.addWidget(self.browse_button)
        folder_row.addWidget(self.test_button)
        layout.addLayout(folder_row)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_button = buttons.addButton("Add Folder", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_button.setDefault(True)
        buttons.accepted.connect(self.addFolder)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.reloadHosts()

    # -- the hosts ---------------------------------------------------------------------------------------------
    def reloadHosts(self):
        """Read the SSH configuration and list its hosts."""
        self.config = readSshConfig(self.config_path)
        path = str(self.config.path)
        ec2 = self.config.ec2Hosts()
        if self.config.error:
            _setStatus(self.config_label, self.config.error, error=True)
        elif not self.config.exists:
            _setStatus(self.config_label, f"There is no SSH configuration at {path}. Type the host below, e.g. "
                                          f"ec2-user@ec2-1-2-3-4.compute-1.amazonaws.com.")
        elif not self.config.hosts:
            _setStatus(self.config_label, f"{path} defines no host.")
        elif not ec2:
            _setStatus(self.config_label, f"None of the {len(self.config.hosts)} hosts of {path} looks like an "
                                          f"EC2 instance: all of them are listed.")
        else:
            certain = sum(1 for host in ec2 if host.ec2_level == EC2)
            probable = len(ec2) - certain
            text = f"{certain} EC2 instance{'s' if certain != 1 else ''}"
            if probable:
                text += f" and {probable} probable one{'s' if probable != 1 else ''}"
            _setStatus(self.config_label, f"{text} among the {len(self.config.hosts)} hosts of {path}.")
        self.all_check.blockSignals(True)
        self.all_check.setChecked(bool(self.config.hosts) and not ec2)
        self.all_check.blockSignals(False)
        self.fillTable()

    def visibleHosts(self) -> List[SshHost]:
        """The hosts that are listed: the EC2 instances (all hosts if asked), those that match the filter."""
        hosts = self.config.hosts if self.all_check.isChecked() else self.config.ec2Hosts()
        needle = self.filter_edit.text().strip().lower()
        if needle:
            hosts = [h for h in hosts if needle in ' '.join([h.alias, h.hostname, h.user, h.comment]).lower()]
        return sorted(hosts, key=lambda host: -host.ec2_level)

    def fillTable(self, *_):
        selected = self.selectedAlias()
        hosts = self.visibleHosts()
        self.table.setRowCount(len(hosts))
        for row, host in enumerate(hosts):
            kind = {EC2: "yes", PROBABLY_EC2: "probably"}.get(host.ec2_level, "")
            values = [host.alias, host.hostname if host.hostname != host.alias else '', host.user, kind]
            tooltip = self._tooltip(host)
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(tooltip)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, host.alias)
                self.table.setItem(row, column, item)
            if host.alias == selected:
                self.table.selectRow(row)
        self._updateButtons()

    @staticmethod
    def _tooltip(host: SshHost) -> str:
        lines = [f"ssh {host.alias}  ({host.destination})"]
        if host.identity_files:
            lines.append("key: " + ", ".join(host.identity_files))
        if host.proxy_jump:
            lines.append("jump host: " + host.proxy_jump)
        if host.comment:
            lines.append("comment: " + host.comment)
        if host.ec2_reasons:
            lines.append("EC2: " + "; ".join(host.ec2_reasons))
        lines.append(f"defined in {host.source}")
        return "\n".join(lines)

    def selectedAlias(self) -> str:
        items = self.table.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else ''

    def host(self) -> str:
        """The host to connect to: the one typed, else the one selected in the list."""
        return self.other_edit.text().strip() or self.selectedAlias()

    def _onSelectionChanged(self):
        self._updateButtons()

    def _updateButtons(self, *_):
        ready = bool(self.host()) and not self._busy
        self.add_button.setEnabled(ready)
        self.browse_button.setEnabled(ready)
        self.test_button.setEnabled(ready)

    def _setBusy(self, busy: bool, text: str = ''):
        self._busy = busy
        for widget in (self.table, self.other_edit, self.path_edit, self.filter_edit, self.all_check,
                       self.reload_button):
            widget.setEnabled(not busy)
        self._updateButtons()
        _setStatus(self.status, text)

    # -- actions -----------------------------------------------------------------------------------------------
    def testConnection(self):
        host = self.host()
        self._setBusy(True, f"Connecting to {host} ...")

        def work():
            return resolvePath(self.remote.transportFor(host), '~')

        def done(home, error):
            if sip.isdeleted(self):
                return
            self._setBusy(False)
            if error is not None:
                _setStatus(self.status, str(error), error=True)
                return
            _setStatus(self.status, f"Connected to {host}. Its home folder is {home}.")
            if not self.path_edit.text().strip():
                self.path_edit.setText(home)

        self.remote.submit(work, done)

    def browse(self):
        browser = RemoteFolderBrowser(self.remote, self.host(), self.path_edit.text().strip() or '~', self)
        if browser.exec() == QDialog.DialogCode.Accepted and browser.selected:
            self.path_edit.setText(browser.selected)

    def addFolder(self):
        host = self.host()
        path = self.path_edit.text().strip() or '~'
        self._setBusy(True, f"Copying the documents of {host}:{path} ...")

        def done(folder, error):
            if sip.isdeleted(self):
                return
            self._setBusy(False)
            if error is not None:
                _setStatus(self.status, str(error), error=True)
                return
            self.folder = folder
            self.accept()

        self.remote.addFolder(host, path, done)

    def reject(self):
        if not self._busy:
            super().reject()
