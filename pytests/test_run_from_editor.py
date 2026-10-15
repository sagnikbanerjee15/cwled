"""
Running a document from the editor (Tools -> Run tool/workflow...): the Run dialog, cwltool in a
process of its own, the save-first question and the job template.

The runs are real: cwltool runs tests/echo.cwl and tests/uppercase.cwl, and small tools written
into the test's folder. cwltool's temporary folders are kept in the test's folder too (on macOS it
uses /private/tmp/docker_tmp, which a sandbox does not allow), see the `scratch` fixture.
Nothing here reads the user's configuration or uses the network.
"""
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox

import CWLRun as runner_module
import RunDialog
from ChildWindow import ChildWindow
from conftest import FIXTURES
from qt_helpers import documents_by_name, open_documents, park_cursor, pump, wait_until

RUN_TIMEOUT = 120      # seconds: cwltool takes a few seconds to start


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """Keep cwltool's temporary folders in the test's folder (see the module's docstring)."""
    original = runner_module.commandLine

    def with_scratch(document, job, outdir):
        program, arguments = original(document, job, outdir)
        temp = tmp_path / 'cwltool-tmp'
        temp.mkdir(exist_ok=True)
        index = arguments.index('--disable-color') + 1
        extra = ['--tmpdir-prefix', f'{temp}/', '--tmp-outdir-prefix', f'{temp}/']
        return program, arguments[:index] + extra + arguments[index:]

    monkeypatch.setattr(runner_module, 'commandLine', with_scratch)
    return tmp_path


def copy_document(folder: Path, name: str) -> Path:
    shutil.copy(FIXTURES / name, folder / name)
    return folder / name


def open_in(window, path: Path):
    """Open a document of the test's folder in the window and return it."""
    park_cursor()
    window.openDocument(str(path), host=window)
    pump(12)
    return documents_by_name(window)[path.name]


def write_job(folder: Path, text: str, name: str = 'job.yml') -> Path:
    path = folder / name
    path.write_text(text)
    return path


def write_tool(folder: Path, name: str, body: str) -> Path:
    path = folder / name
    path.write_text(f"cwlVersion: v1.2\nclass: CommandLineTool\n{body}inputs: []\noutputs: []\n")
    return path


def run_to_end(dialog, timeout: float = RUN_TIMEOUT):
    wait_until(lambda: dialog.run is not None and dialog.run.ended, timeout=timeout,
               message="the run did not end")
    return dialog.run


def files_listed(dialog):
    return [dialog.filesList.item(index).text() for index in range(dialog.filesList.count())]


# -- the menu and the document ----------------------------------------------------------------------------------
def test_the_run_action_is_in_the_tools_menu_after_validate(window):
    tools = next(action.menu() for action in window.menuBar().actions() if action.text() == '&Tools')
    texts = [action.text() for action in tools.actions() if not action.isSeparator()]
    assert texts.index('Run tool/workflow...') == texts.index('Validate tool') + 1


def test_run_without_a_document_warns_like_the_other_tools(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(window, '_warnNoDocument', lambda: warnings.append('no document'))
    window.active_window = None
    window.onMenuRun()
    assert warnings == ['no document']


def test_an_unsaved_document_is_not_run_when_the_user_does_not_save(make_window, tmp_path, monkeypatch):
    window = make_window(tmp_path)
    document = open_in(window, copy_document(tmp_path, 'echo.cwl'))
    document.hasChanged = True
    asked = []

    def no(self, title, text, show_cancel=False):
        asked.append(title)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(ChildWindow, 'questionCentered', no)
    assert RunDialog.startRunFromEditor(document) is None
    assert asked == ['Save Before Running?']
    assert document.hasChanged, "nothing was saved"
    assert document.findChildren(RunDialog.RunDialog) == []


def test_an_unsaved_document_is_saved_and_then_the_run_dialog_opens(make_window, tmp_path, monkeypatch):
    window = make_window(tmp_path)
    document = open_in(window, copy_document(tmp_path, 'echo.cwl'))
    document.hasChanged = True

    def yes(self, title, text, show_cancel=False):
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(ChildWindow, 'questionCentered', yes)
    dialog = RunDialog.startRunFromEditor(document)
    assert isinstance(dialog, RunDialog.RunDialog)
    assert not document.hasChanged, "the document was saved"
    assert dialog.parent() is document
    dialog.close()


def test_the_tools_action_opens_the_run_dialog_for_the_saved_document(make_window, tmp_path):
    window = make_window(tmp_path)
    document = open_in(window, copy_document(tmp_path, 'echo.cwl'))
    window.active_window = document
    window.onMenuRun()
    dialogs = document.findChildren(RunDialog.RunDialog)
    assert len(dialogs) == 1
    dialogs[0].close()


# -- the job and the output folder ------------------------------------------------------------------------------
def test_generating_the_job_fills_the_box_from_the_template_and_writes_nothing(make_window, tmp_path):
    window = make_window(tmp_path)
    document = open_in(window, copy_document(tmp_path, 'echo.cwl'))
    dialog = RunDialog.RunDialog(document)
    dialog.generateJob()
    assert 'message' in dialog.jobText.toPlainText()
    assert dialog.jobSource is None
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix in ('.cwl', '.yml', '.json')) == ['echo.cwl']
    dialog.close()


def test_the_output_folder_is_a_new_folder_named_for_the_run(make_window, tmp_path):
    window = make_window(tmp_path)
    document = open_in(window, copy_document(tmp_path, 'echo.cwl'))
    dialog = RunDialog.RunDialog(document)
    folder = Path(dialog.outputEdit.text())
    assert folder.parent == tmp_path
    assert re.fullmatch(r'echo-run-\d{8}-\d{6}', folder.name)
    dialog.close()


def test_a_job_that_is_not_yaml_is_not_run(make_window, tmp_path, monkeypatch):
    window = make_window(tmp_path)
    document = open_in(window, copy_document(tmp_path, 'echo.cwl'))
    warnings = []
    monkeypatch.setattr(RunDialog.QMessageBox, 'warning', lambda parent, title, text: warnings.append(title))
    dialog = RunDialog.RunDialog(document)
    dialog.jobText.setPlainText('message: [unclosed')
    dialog.startRun()
    assert warnings == ['Job']
    assert dialog.run is None
    dialog.close()


# -- the command ----------------------------------------------------------------------------------------------
def test_the_run_is_cwltool_run_by_this_python(monkeypatch):
    program, arguments = runner_module.commandLine(Path('/w/echo.cwl'), Path('/w/job.yml'), Path('/w/out'))
    assert program == sys.executable
    assert arguments[:2] == ['-m', 'cwltool.main']        # its exit code is cwltool's (python -m cwltool drops it)
    assert arguments[-4:] == ['--outdir', '/w/out', '/w/echo.cwl', '/w/job.yml']

    monkeypatch.setattr(sys, 'frozen', True, raising=False)      # the packaged application
    program, arguments = runner_module.commandLine(Path('/w/echo.cwl'), Path('/w/job.yml'), Path('/w/out'))
    assert arguments[:2] == ['--run-module', 'cwltool']


def test_the_produced_files_are_the_file_and_folder_outputs(tmp_path):
    outputs = {
        'report': {'class': 'File', 'location': 'file:///w/out/a%20b.txt'},
        'count': 3,
        'many': [{'class': 'File', 'location': 'file:///w/out/c.txt'}],
        'folder': {'class': 'Directory', 'location': 'file:///w/out/d'},
    }
    assert runner_module.producedFiles(outputs) == [Path('/w/out/a b.txt'), Path('/w/out/c.txt'), Path('/w/out/d')]
    assert runner_module.parseOutputs('not json') is None


# -- real runs --------------------------------------------------------------------------------------------------
def test_the_echo_tool_runs_in_the_background_and_its_output_is_listed(window, tmp_path, scratch, monkeypatch):
    document = open_documents(window, ['echo.cwl'])['echo.cwl']
    job = tmp_path / 'echo-job.yml'
    job.write_text('message: hello\n')
    dialog = RunDialog.RunDialog(document)
    dialog.loadJobFile(str(job))
    dialog.outputEdit.setText(str(tmp_path / 'out'))
    dialog.startRun()
    run = run_to_end(dialog)

    assert run.status == 'finished' and run.exit_code == 0
    assert json.loads(dialog.resultView.toPlainText()) == {'out': 'hello\n'}
    assert files_listed(dialog) == [RunDialog.NO_FILES_TEXT], "the output of echo.cwl is a value, not a file"
    assert dialog.statusLabel.text().startswith('Finished, exit code 0')
    assert not dialog.resultBox.isHidden()
    assert '[job' in dialog.logView.toPlainText(), "the log shows what cwltool does, as it does"

    opened = []
    monkeypatch.setattr(RunDialog.QDesktopServices, 'openUrl', lambda url: opened.append(url.toLocalFile()) or True)
    dialog.openOutputFolder()
    assert opened == [str(tmp_path / 'out')]
    dialog.close()


@pytest.mark.skipif(shutil.which('node') is None,
                    reason='cwltool evaluates the JavaScript of an expression tool with Node.js; without it '
                           'cwltool tries a Docker image of Node (a network download)')
def test_an_expression_tool_from_the_tests_folder_runs(window, tmp_path, scratch):
    document = open_documents(window, ['uppercase.cwl'])['uppercase.cwl']
    job = tmp_path / 'upper-job.yml'
    job.write_text('message: hello\n')
    dialog = RunDialog.RunDialog(document)
    dialog.loadJobFile(str(job))
    dialog.outputEdit.setText(str(tmp_path / 'out'))
    dialog.startRun()
    run = run_to_end(dialog)

    assert run.status == 'finished'
    assert json.loads(dialog.resultView.toPlainText()) == {'uppercase_message': 'HELLO'}
    dialog.close()


def test_a_tool_that_writes_a_file_lists_it_among_the_produced_files(make_window, tmp_path, scratch):
    window = make_window(tmp_path)
    tool = tmp_path / 'writes.cwl'
    tool.write_text("cwlVersion: v1.2\nclass: CommandLineTool\nbaseCommand: echo\nstdout: report.txt\n"
                    "inputs:\n  message:\n    type: string\n    inputBinding: {}\n"
                    "outputs:\n  report: stdout\n")
    document = open_in(window, tool)
    dialog = RunDialog.RunDialog(document)
    dialog.loadJobFile(str(write_job(tmp_path, 'message: hello\n')))
    dialog.outputEdit.setText(str(tmp_path / 'out'))
    dialog.startRun()
    run = run_to_end(dialog)

    assert run.status == 'finished'
    assert (tmp_path / 'out' / 'report.txt').read_text() == 'hello\n'
    assert files_listed(dialog) == ['report.txt']
    dialog.close()


def test_a_failing_tool_keeps_its_log_and_says_so(make_window, tmp_path, scratch):
    window = make_window(tmp_path)
    broken = write_tool(tmp_path, 'broken.cwl', 'baseCommand: [sh, -c]\n'
                                                'arguments: ["echo the-tool-went-wrong >&2; exit 3"]\n')
    document = open_in(window, broken)
    dialog = RunDialog.RunDialog(document)
    dialog.jobText.setPlainText('{}\n')
    dialog.outputEdit.setText(str(tmp_path / 'out'))
    dialog.startRun()
    run = run_to_end(dialog)

    assert run.status == 'failed' and run.exit_code not in (0, None)
    assert dialog.statusLabel.text().startswith('Failed, exit code')
    assert 'the-tool-went-wrong' in dialog.logView.toPlainText()
    assert dialog.resultBox.isHidden()
    assert dialog.runButton.isEnabled() and not dialog.cancelButton.isEnabled()
    assert (tmp_path / 'broken-job.yml').exists(), "a typed job is saved next to the document"
    dialog.close()


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_cancel_stops_cwltool_and_the_tool_it_started(make_window, tmp_path, scratch):
    window = make_window(tmp_path)
    started, pidfile = tmp_path / 'started', tmp_path / 'pid'
    # `exec` makes sleep the tool's only process, so the pid written to the file is the tool's
    slow = write_tool(tmp_path, 'slow.cwl', 'baseCommand: [sh, -c]\n'
                                            f'arguments: [{json.dumps(f"touch {started}; echo $$ > {pidfile}; exec sleep 60")}]\n')
    document = open_in(window, slow)
    dialog = RunDialog.RunDialog(document)
    dialog.jobText.setPlainText('{}\n')
    dialog.outputEdit.setText(str(tmp_path / 'out'))
    dialog.startRun()
    wait_until(lambda: pidfile.exists() and pidfile.read_text().strip(), timeout=RUN_TIMEOUT,
               message="the tool did not start")
    tool = int(pidfile.read_text())
    assert is_alive(tool)
    assert dialog.cancelButton.isEnabled() and not dialog.runButton.isEnabled()

    dialog.cancelButton.click()
    assert dialog.statusLabel.text() == "Stopping..."
    run = run_to_end(dialog, timeout=30)
    assert run.status == 'cancelled'
    assert dialog.statusLabel.text() == "Cancelled."
    assert dialog.runButton.isEnabled() and not dialog.cancelButton.isEnabled()
    wait_until(lambda: not is_alive(tool), timeout=10, message="the tool kept running after the run was cancelled")
    dialog.close()


def test_closing_the_dialog_while_it_runs_stops_the_run(make_window, tmp_path, scratch):
    window = make_window(tmp_path)
    started = tmp_path / 'started'
    slow = write_tool(tmp_path, 'slow.cwl', 'baseCommand: [sh, -c]\n'
                                            f'arguments: [{json.dumps(f"touch {started}; sleep 30")}]\n')
    document = open_in(window, slow)
    dialog = RunDialog.RunDialog(document)
    dialog.show()                              # closing a shown dialog is what the user does
    dialog.jobText.setPlainText('{}\n')
    dialog.outputEdit.setText(str(tmp_path / 'out'))
    dialog.startRun()
    wait_until(started.exists, timeout=RUN_TIMEOUT, message="the tool did not start")
    run = dialog.run
    dialog.close()
    assert run.ended and run.status == 'cancelled'
    assert not run.isRunning()
