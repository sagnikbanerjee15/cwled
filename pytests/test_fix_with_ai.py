"""
Fix with AI: the consent, the request in a worker thread, the reading of the answer, the comparison
with the suggestion, Apply (one undoable edit) and Discard, and the Tools entry.

The model is never reached: its chat model is replaced by a stand-in that records what it is sent
and answers what the test says. No network, no API key (the key of the environment is a dummy).
"""
import threading
import time
import types

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

import DocumentDiff as DD
import LLM
import LLMFix
import qErrorMessage
from qt_helpers import open_documents, pump, wait_until

GOOD_DOCUMENT = """cwlVersion: v1.2
class: CommandLineTool
baseCommand: cat
inputs:
  message:
    type: string
    inputBinding:
      position: 1
outputs: []
"""

GOOD_JSON = """{
  "cwlVersion": "v1.2",
  "class": "CommandLineTool",
  "baseCommand": "cat",
  "inputs": [],
  "outputs": []
}"""

ASKED = "gemini-2.5-flash"


class StandIn:
    """The chat model: records the messages it is sent and answers ``answer``; it may wait for ``release``."""

    def __init__(self):
        self.answer = GOOD_DOCUMENT
        self.calls = []
        self.release = None

    def invoke(self, messages):
        self.calls.append(messages)
        if self.release is not None:
            self.release.wait(10)
        return types.SimpleNamespace(content=self.answer)


@pytest.fixture
def model(monkeypatch, cwled_config):
    """The configured model, set up with a dummy key, whose chat model is the stand-in."""
    stand_in = StandIn()
    monkeypatch.setenv('GOOGLE_API_KEY', 'dummy-key-for-tests')
    monkeypatch.setattr(LLM, 'init_chat_model', lambda *args, **kwargs: stand_in)
    yield stand_in
    # a request still waiting for its answer must end before the test does
    if stand_in.release is not None:
        stand_in.release.set()
        wait_until(lambda: not any(request.isRunning() for request in LLMFix._requests), message="a request is still running")


def clickThrough(*labels, timeout=15.0):
    """
    Click, in turn, the button with each of ``labels`` in the dialogs that open, as a user would.
    Returns what was shown, (kind, text, details), of each dialog that was clicked on: 'message' for a
    message box (Qt keeps no title for it), else the title of the dialog.
    A dialog that is not answered in time is closed, so that the test fails instead of waiting.
    """
    pending = list(labels)
    shown = []
    deadline = time.monotonic() + timeout

    def poll():
        if not pending:
            return
        dialog = QApplication.activeModalWidget()
        if dialog is not None and time.monotonic() >= deadline:
            dialog.close()
            return
        if isinstance(dialog, QDialog):
            for button in dialog.findChildren(QPushButton):
                if button.isVisible() and button.text().replace('&', '') == pending[0]:
                    if isinstance(dialog, QMessageBox):
                        shown.append(('message', dialog.text(), dialog.detailedText()))
                    else:
                        shown.append((dialog.windowTitle(), '', ''))
                    pending.pop(0)
                    button.click()
                    QTimer.singleShot(20, poll)
                    return
        QTimer.singleShot(20, poll)

    QTimer.singleShot(20, poll)
    return shown


def openEcho(window):
    return open_documents(window, ['echo.cwl'])['echo.cwl']


# ---------------------------------------------------------------------------------------------
# the consent and the request
# ---------------------------------------------------------------------------------------------
def test_nothing_is_sent_until_the_user_sends(window, model):
    document = openEcho(window)
    shown = clickThrough('Cancel')
    LLMFix.suggestFix(document, 'the errors')
    assert shown == [('message', f'The document and the validation errors will be sent to google_genai/{ASKED}.', '')]
    assert model.calls == []


def test_send_sends_the_document_and_the_errors(window, model):
    document = openEcho(window)
    buffer = document.code_editor.editor.text()
    clickThrough('Send', 'Discard')
    LLMFix.suggestFix(document, 'ERROR: the input "message" is missing')
    assert len(model.calls) == 1
    sent = '\n'.join(str(message.content) for message in model.calls[0])
    assert 'ERROR: the input "message" is missing' in sent
    assert buffer in sent
    assert 'corrected' in str(model.calls[0][0].content)


def test_without_an_api_key_the_message_is_shown_and_nothing_is_sent(window, monkeypatch):
    document = openEcho(window)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    shown = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda parent, title, text, *args, **kwargs: shown.append((title, text)))

    def consentMustNotOpen(*args, **kwargs):
        raise AssertionError("the consent was asked without a key")

    monkeypatch.setattr(LLMFix, 'askConsent', consentMustNotOpen)
    LLMFix.suggestFix(document, 'the errors')
    assert [title for title, _text in shown] == ['API Key Missing']
    assert 'GOOGLE_API_KEY' in shown[0][1]


# ---------------------------------------------------------------------------------------------
# the answer
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize('answer', [
    f"Here is the corrected document:\n\n```yaml\n{GOOD_DOCUMENT}```\n\nI added the input.",
    f"```\n{GOOD_DOCUMENT}```",
    f"Here is the fix.\n{GOOD_DOCUMENT}\nThe input was missing.",
    GOOD_DOCUMENT,
    f"```json\n{GOOD_JSON}\n```",
    GOOD_JSON,
], ids=['fenced-with-prose', 'fence-without-language', 'prose-before-and-after', 'bare', 'json-fenced', 'json-bare'])
def test_the_document_is_taken_from_the_answer(answer):
    document = LLMFix.documentFromAnswer(answer)
    assert document is not None
    assert DD.sourceFromText(document, 'answer').cwl['class'] == 'CommandLineTool'


@pytest.mark.parametrize('answer', [
    "Sorry, I cannot correct this document.",
    "Error: the model is busy",                       # a key-like line, without a class
    "cwlVersion: v1.2\nbaseCommand: cat\n",           # a mapping, without a class
    "```yaml\n: : :\n```",                            # not YAML
    "",
], ids=['prose', 'key-like-prose', 'no-class', 'not-yaml', 'empty'])
def test_an_answer_without_a_document_is_rejected(answer):
    assert LLMFix.documentFromAnswer(answer) is None


def test_an_unusable_answer_is_shown_with_the_answer_under_details(window, model):
    document = openEcho(window)
    model.answer = "Sorry, I cannot help with this one."
    shown = clickThrough('Send', 'OK')
    LLMFix.suggestFix(document, 'the errors')
    assert shown[-1] == ('message', 'The answer could not be used.', model.answer)
    assert not document.hasChanged


def test_cancel_while_the_model_answers_returns_at_once_and_a_late_answer_is_ignored(window, model):
    document = openEcho(window)
    buffer = document.code_editor.editor.text()
    model.release = threading.Event()
    shown = clickThrough('Send', 'Cancel')
    started = time.monotonic()
    LLMFix.suggestFix(document, 'the errors')
    assert time.monotonic() - started < 5, "the window waited for the model"
    assert [kind for kind, _text, _details in shown] == ['message', 'Fix with AI']
    assert len(model.calls) == 1
    model.release.set()                              # the answer comes after the cancel
    wait_until(lambda: not any(request.isRunning() for request in LLMFix._requests))
    pump(20)
    assert QApplication.activeModalWidget() is None, "a late answer opened a dialog"
    assert document.code_editor.editor.text() == buffer
    assert not document.hasChanged


# ---------------------------------------------------------------------------------------------
# the comparison, Apply and Discard
# ---------------------------------------------------------------------------------------------
def test_the_comparison_shows_the_changes_of_the_suggestion(cwled_config, qapp):
    from TabDiff import DiffView
    current = 'cwlVersion: v1.2\nclass: CommandLineTool\nbaseCommand: echo\ninputs: []\noutputs: []\n'
    suggestion = current.replace('baseCommand: echo', 'baseCommand: cat')
    view = DiffView(lambda: DD.sourceFromText(current, 'Current document'),
                    lambda: DD.sourceFromText(suggestion, 'Suggested fix'))
    assert [change.describe() for change in view.changes] == ['~ baseCommand']
    assert 'difference' in view.summary.text()


def test_text_that_is_not_a_document_is_compared_as_lines(cwled_config, qapp):
    from TabDiff import DiffView
    current = 'class: [unclosed\n'
    view = DiffView(lambda: DD.sourceFromText(current, 'Current document'),
                    lambda: DD.sourceFromText(GOOD_DOCUMENT, 'Suggested fix'))
    assert view.left is not None
    assert view.left_edit.toPlainText().splitlines()[0] == 'class: [unclosed'
    assert view.change_list.item(0).text() == 'Not a CWL document: compare the lines'


def test_apply_puts_the_suggestion_in_the_code_tab_as_one_undoable_edit(window, model):
    document = openEcho(window)
    code = document.code_editor
    before = code.editor.text()
    suggestion = before.replace('baseCommand: echo', 'baseCommand: cat')
    assert LLMFix.applyToEditor(document, suggestion)
    assert 'baseCommand: cat' in code.editor.text()
    assert document.hasChanged, "the document is not marked as modified"
    assert '*' in document.windowTitle()
    assert document.getCWL().baseCommand == ['cat']
    code.editor.undo()
    assert code.editor.text() == before
    code.editor.redo()
    assert 'baseCommand: cat' in code.editor.text()


def test_apply_from_the_comparison_changes_the_document(window, model):
    document = openEcho(window)
    before = document.code_editor.editor.text()
    model.answer = before.replace('baseCommand: echo', 'baseCommand: cat')
    shown = clickThrough('Send', 'Apply')
    LLMFix.suggestFix(document, 'the errors')
    assert [kind for kind, _text, _details in shown] == ['message', 'Suggested fix']
    assert 'baseCommand: cat' in document.code_editor.editor.text()
    assert document.hasChanged


def test_discard_leaves_the_document_as_it_was(window, model):
    document = openEcho(window)
    before = document.code_editor.editor.text()
    model.answer = before.replace('baseCommand: echo', 'baseCommand: cat')
    clickThrough('Send', 'Discard')
    LLMFix.suggestFix(document, 'the errors')
    assert document.code_editor.editor.text() == before
    assert not document.hasChanged
    assert document.getCWL().baseCommand == 'echo'


def test_a_suggestion_that_cannot_be_applied_leaves_the_buffer_as_it_was(window, monkeypatch):
    document = openEcho(window)
    before = document.code_editor.editor.text()
    # the Code tab shows the error in a dialog that would wait for someone to close it
    monkeypatch.setattr(qErrorMessage.QErrorMessage, 'show_critical', lambda *args, **kwargs: 0)
    assert not LLMFix.applyToEditor(document, 'class: NotAClass\n')
    assert document.code_editor.editor.text() == before
    assert not document.hasChanged


# ---------------------------------------------------------------------------------------------
# the entries: the validation error dialog and the Tools menu
# ---------------------------------------------------------------------------------------------
def test_the_validation_error_dialog_offers_fix_with_ai(cwled_config, qapp):
    from widgets.qButtons import ErrorDialog
    calls = []
    dialog = ErrorDialog(error_message="This tool cannot be validated", details="the errors",
                         actions=[("Fix with AI", lambda: calls.append('fix'))])
    assert [button.text() for button in dialog.findChildren(QPushButton)] == ['Fix with AI', 'OK']
    dialog.findChildren(QPushButton)[0].click()
    assert calls == ['fix']
    assert dialog.result() == QDialog.DialogCode.Accepted.value


def test_the_tools_menu_has_the_suggestion(window):
    tools = next(action.menu() for action in window.menuBar().actions() if action.text().replace('&', '') == 'Tools')
    assert 'Suggest a fix for the validation errors' in [action.text() for action in tools.actions()]


def test_a_valid_document_is_said_to_be_valid(window, monkeypatch):
    document = openEcho(window)
    monkeypatch.setattr(LLMFix, 'validateDocument', lambda window: (True, ''))
    monkeypatch.setattr(LLMFix, 'suggestFix', lambda *args: pytest.fail("a valid document is not sent"))
    shown = clickThrough('OK')
    LLMFix.suggestFixForValidation(document)
    assert shown == [('message', 'The document is valid: there is nothing to fix.', '')]


def test_an_invalid_document_goes_straight_into_the_fix(window, monkeypatch):
    document = openEcho(window)
    monkeypatch.setattr(LLMFix, 'validateDocument', lambda window: (False, 'the errors'))
    asked = []
    monkeypatch.setattr(LLMFix, 'suggestFix', lambda window, errors: asked.append((window, errors)))
    LLMFix.suggestFixForValidation(document)
    assert asked == [(document, 'the errors')]


def test_validation_writes_the_document_next_to_it_and_removes_the_file(window, monkeypatch, tmp_path):
    document = openEcho(window)
    check = tmp_path / 'check.cwl'
    monkeypatch.setattr(document, '_temporary_filename', lambda: check)
    seen = {}

    class Runner:
        stderr = 'boom'

        def validate(self, filename):
            seen['text'] = open(filename, encoding='utf-8').read()
            return False

    monkeypatch.setattr(LLMFix, 'CWLRunner', Runner)
    assert LLMFix.validateDocument(document) == (False, 'boom')
    assert seen['text'] == document.code_editor.editor.text()
    assert not check.exists()
