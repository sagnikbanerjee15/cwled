"""
A document older than CWL v1.2 is opened as it is, without asking whether to upgrade it.
The question ("CWL Version Notice": Upgrade to v1.2 / Continue as is) is only asked when
`ask_to_upgrade_cwl_version` is true (Tools -> Configuration -> General).

Nothing here reads the user's configuration or uses the network.
"""
import shutil
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox

from conftest import FIXTURES
from qt_helpers import documents_by_name, park_cursor, pump

OLD_TOOL = """\
cwlVersion: v1.0
class: CommandLineTool
baseCommand: echo
inputs:
  message:
    type: string
    inputBinding:
      position: 1
outputs: []
"""


@pytest.fixture
def notices(monkeypatch):
    """The message boxes that are executed: [(title, text, [button texts], default button text)]."""
    shown = []

    def record(box):
        shown.append((box.windowTitle(), box.text(), [b.text() for b in box.buttons()],
                      box.defaultButton().text() if box.defaultButton() else None))
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', record)
    return shown


def questions(notices):
    """The version questions among the message boxes shown (a message box has no title on macOS)."""
    return [n for n in notices if n[1].startswith('The loaded CWL document is version')]


def open_in(make_window, folder: Path, name: str):
    window = make_window(workspace=folder)
    park_cursor()
    window.openDocument(str(folder / name), host=window)
    pump(12)
    return documents_by_name(window)[name]


def old_document(folder: Path) -> Path:
    path = folder / 'old-echo.cwl'
    path.write_text(OLD_TOOL)
    return path


def test_the_question_is_off_by_default(cwled_config):
    assert cwled_config.get('ask_to_upgrade_cwl_version') is False


def test_an_old_document_is_opened_as_it_is_without_a_question(make_window, notices, tmp_path):
    path = old_document(tmp_path)
    document = open_in(make_window, tmp_path, path.name)
    assert questions(notices) == []
    assert document.cwl_tool.cwlVersion == 'v1.0'
    assert path.read_text() == OLD_TOOL, "nothing is converted or rewritten"
    assert [p.name for p in tmp_path.glob('*.cwl')] == [path.name], "no upgraded copy is written either"


def test_a_v1_2_document_never_asks(make_window, notices, cwled_config, tmp_path):
    shutil.copy(FIXTURES / 'echo.cwl', tmp_path / 'echo.cwl')
    for ask in (False, True):
        cwled_config['ask_to_upgrade_cwl_version'] = ask
        open_in(make_window, tmp_path, 'echo.cwl')
    assert questions(notices) == []


def test_the_question_is_asked_when_the_setting_is_on(make_window, notices, cwled_config, tmp_path):
    cwled_config['ask_to_upgrade_cwl_version'] = True
    path = old_document(tmp_path)
    document = open_in(make_window, tmp_path, path.name)
    asked = questions(notices)
    assert len(asked) == 1
    _, text, buttons, default = asked[0]
    assert 'v1.0' in text and 'v1.2' in text
    assert buttons == ['Upgrade to v1.2', 'Continue as is']
    assert default == 'Continue as is'
    assert document.cwl_tool.cwlVersion == 'v1.0', "nothing was clicked: the document is kept"


def test_the_general_tab_has_the_setting(window, cwled_config):
    from ConfigDialog import ConfigDialog
    assert not ConfigDialog(window).ask_upgrade_check.isChecked()
    cwled_config['ask_to_upgrade_cwl_version'] = True
    assert ConfigDialog(window).ask_upgrade_check.isChecked()


def test_ticking_the_box_and_pressing_ok_keeps_the_setting(window, cwled_config, monkeypatch):
    import ConfigDialog as module
    # OK saves the configuration file and says so in a message box: neither must happen here
    monkeypatch.setattr(module.Configuration, 'saveConfiguration', lambda self: 'nowhere')
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: None)
    dialog = module.ConfigDialog(window)
    dialog.ask_upgrade_check.setChecked(True)
    dialog.accept()
    assert cwled_config['ask_to_upgrade_cwl_version'] is True
    dialog = module.ConfigDialog(window)
    dialog.ask_upgrade_check.setChecked(False)
    dialog.accept()
    assert cwled_config['ask_to_upgrade_cwl_version'] is False
