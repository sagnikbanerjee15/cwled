"""
Fix with AI: the configured LLM corrects a document that does not validate.

It is started from the "Fix with AI" button of the validation error dialog, and from
Tools > Suggest a fix for the validation errors (see docs/FLOW.md, "Fix with AI"):

1. the model is set up from the 'llm' configuration; without an API key the message is the one
   the Troubleshoot tool shows, and the flow stops there;
2. the user is told what is sent, and to whom, and agrees: nothing is sent before;
3. the model is asked in a worker thread, with a busy indicator and a Cancel button;
4. the answer is read: the document is taken out of the text around it (code fences, prose) and
   must parse as YAML with a ``class``, otherwise the answer is shown, unused, under Details;
5. the suggestion is compared with the Code tab in the comparison view. Apply puts it into the
   Code tab as one undoable edit, Discard does nothing. Nothing changes without Apply.
"""
import json
import logging
import re
from io import StringIO
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressBar, QVBoxLayout)
from ruamel.yaml import YAML

import DocumentDiff
from CWLtoolFactory import CWLRunner
from LLM import BaseLLM
from TabDiff import DiffView

logger = logging.getLogger(__name__)

# a fenced block of markdown: ```yaml ... ```
_FENCE = re.compile(r'```[^\n`]*\n(.*?)```', re.DOTALL)
# a line that starts a top level key of a YAML document, or a JSON object
_TOP_KEY = re.compile(r'^(?:[A-Za-z_$][\w.$-]*\s*:(?:\s|$)|\{)')


# ---------------------------------------------------------------------------------------------
# the answer of the model
# ---------------------------------------------------------------------------------------------
def _continues(line: str) -> bool:
    """Whether a line can belong to a document that started at a top level key."""
    return not line or line[0].isspace() or line[0] in '-#}]' or bool(_TOP_KEY.match(line))


def _isCWL(text: str) -> bool:
    try:
        document = YAML().load(text)
    except Exception:
        return False
    return isinstance(document, dict) and 'class' in document


def _documentIn(text: str) -> Optional[str]:
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if not _TOP_KEY.match(line):
            continue
        end = start
        while end < len(lines) and _continues(lines[end]):
            end += 1
        document = '\n'.join(lines[start:end])
        if _isCWL(document):
            return document
    return None


def documentFromAnswer(answer: str) -> Optional[str]:
    """
    The CWL document in an answer of the model: the code block that holds it, or the answer
    itself without the prose before and after the document. None when the answer holds no
    document with a ``class`` that parses as YAML.
    """
    for candidate in _FENCE.findall(answer) + [answer]:
        document = _documentIn(candidate)
        if document is not None:
            return document
    return None


# ---------------------------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------------------------
class FixWithAI(BaseLLM):
    """The configured model, asked for the corrected document."""

    def __init__(self, model: Optional[str] = None):
        super().__init__(model)
        self.system_prompt = self.loadTemplate("systemPrompt-fix.jinja2")

    def requestFix(self, document: str, errors: str) -> str:
        """The answer of the model, as it came. It waits for the model: call it in a worker thread."""
        user_content = (f"The validation errors:\n```\n{errors}\n```\n\n"
                        f"The document:\n```\n{document}\n```\n")
        return self.invokeModel(user_content)


class _Request(QThread):
    """The model is asked in a thread of its own, so that the window keeps working while it answers."""
    answered = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, call: Callable[[], str]):
        super().__init__()
        self._call = call

    def run(self):
        try:
            answer = self._call()
        except Exception as e:
            self.failed.emit(str(e) or type(e).__name__)
        else:
            self.answered.emit(answer)


# The requests that have not ended. A cancelled one stays here until it ends: a thread is not
# destroyed while it runs.
_requests: List[_Request] = []


class _AskingDialog(QDialog):
    """The busy indicator while the model answers, with Cancel. An answer that comes later is ignored."""

    def __init__(self, request: _Request, description: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fix with AI")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.answer: Optional[str] = None
        self.failure: Optional[str] = None
        self._open = True

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(description, self))
        busy = QProgressBar(self)
        busy.setRange(0, 0)                  # busy: no progress is known
        layout.addWidget(busy)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        request.answered.connect(self._answered)
        request.failed.connect(self._failed)

    def _answered(self, answer: str):
        if self._open:
            self.answer = answer
            self.accept()

    def _failed(self, message: str):
        if self._open:
            self.failure = message
            self.reject()

    def done(self, result: int):
        self._open = False
        super().done(result)


# ---------------------------------------------------------------------------------------------
# the dialogs
# ---------------------------------------------------------------------------------------------
def askConsent(parent, provider: str, model: str) -> bool:
    """The notice before anything is sent: True when the user sends."""
    box = QMessageBox(parent)
    box.setWindowTitle("Fix with AI")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(f"The document and the validation errors will be sent to {provider}/{model}.")
    box.setInformativeText("Nothing in the document changes until you apply the suggestion.")
    send = box.addButton("Send", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is send


def _showUnusable(parent, answer: str):
    logger.warning("Fix with AI: the answer of the model holds no CWL document that can be used")
    box = QMessageBox(parent)
    box.setWindowTitle("Fix with AI")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText("The answer could not be used.")
    box.setInformativeText("It holds no CWL document (with a class) that can be read. The answer is under Details.")
    box.setDetailedText(answer)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


class FixReview(QDialog):
    """
    The suggestion next to the Code tab's text, in the comparison view. Apply puts the suggestion
    into the Code tab (see ``applyToEditor``); Discard leaves the document as it is.
    """

    def __init__(self, window, suggestion: str, parent=None):
        super().__init__(parent if parent is not None else window)
        self.setWindowTitle("Suggested fix")
        self._window = window
        self._suggestion = suggestion
        current = window.code_editor.editor.text()
        self.view = DiffView(lambda: DocumentDiff.sourceFromText(current, "Current document"),
                             lambda: DocumentDiff.sourceFromText(suggestion, "Suggested fix"), self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        buttons = QDialogButtonBox(self)
        self.apply_button = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.discard_button = buttons.addButton("Discard", QDialogButtonBox.ButtonRole.RejectRole)
        self.apply_button.clicked.connect(self._apply)
        self.discard_button.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(1100, 700)

    def _apply(self):
        if applyToEditor(self._window, self._suggestion):
            self.accept()


def applyToEditor(window, suggestion: str) -> bool:
    """
    Put the suggestion into the Code tab of ``window`` as one edit that Undo takes back.

    The text is applied the way an edit of the Code tab is: the document is read from it, and its
    other tabs and the modified marker follow. The buffer keeps the suggestion as the model wrote it
    (its comments included). Undo takes the whole change back in one step. Returns False, with the
    buffer as it was, when the suggestion cannot be applied.
    """
    code = window.code_editor
    editor = code.editor
    before = editor.text()
    editor.setText(suggestion)
    try:
        code.applyEditorChanges(emit_signal=True)
    except Exception as e:
        editor.setText(before)
        logger.warning(f"Fix with AI: the suggestion could not be applied: {e}")
        return False
    # Applying redraws the Code tab from the document, and setText clears the undo history: the
    # buffer goes back to the text before the change, and the suggestion is written again as one
    # undoable step. The document was read from the suggestion, so that is the applied text.
    editor.setText(before)
    editor.beginUndoAction()
    editor.selectAll()
    editor.replaceSelectedText(suggestion)
    editor.endUndoAction()
    code._markTextAsApplied(suggestion)
    logger.info("Fix with AI: the suggestion is applied to the Code tab (Undo takes it back)")
    return True


# ---------------------------------------------------------------------------------------------
# the flow
# ---------------------------------------------------------------------------------------------
def _askInBackground(window, assistant: FixWithAI, document: str, errors: str) -> Optional[str]:
    """The answer of the model, or None when it was cancelled or failed (a failure is shown)."""
    request = _Request(lambda: assistant.requestFix(document, errors))
    _requests[:] = [pending for pending in _requests if pending.isRunning()]
    _requests.append(request)
    dialog = _AskingDialog(request, f"Asking {assistant.provider}/{assistant.model_name} for a fix...", window)
    request.start()
    dialog.exec()
    dialog.deleteLater()
    if dialog.answer is not None:
        return dialog.answer
    if dialog.failure is not None:
        logger.warning(f"Fix with AI: the model did not answer: {dialog.failure}")
        QMessageBox.warning(window, "Fix with AI", f"The model did not answer:\n{dialog.failure}")
    else:
        logger.info("Fix with AI: cancelled while the model answered")
    return None


def suggestFix(window, errors: str) -> None:
    """
    Fix with AI for the document in the Code tab of ``window``, given its validation ``errors``.
    The consent, the request, the reading of the answer and the comparison with the suggestion.
    """
    try:
        assistant = FixWithAI()
    except Exception as e:
        # no API key, or the model cannot be set up: the message is shown, as the Troubleshoot tool does
        logger.warning(f"Fix with AI stopped before anything was sent: {e}")
        return
    if not askConsent(window, assistant.provider, assistant.model_name):
        logger.info("Fix with AI: nothing was sent (cancelled by the user)")
        return
    answer = _askInBackground(window, assistant, window.code_editor.editor.text(), errors)
    if answer is None:
        return
    suggestion = documentFromAnswer(answer)
    if suggestion is None:
        _showUnusable(window, answer)
        return
    review = FixReview(window, suggestion)
    review.exec()
    review.deleteLater()


def validateDocument(window) -> Tuple[bool, str]:
    """
    The Code tab text of ``window`` validated as ChildWindow.onMenuValidate does it (the same runner,
    the same temporary file next to the document), without a dialog: (valid, the messages).
    """
    text = window.code_editor.editor.text()
    if window.code_editor.format == 'JSON':
        yaml = YAML()
        yaml.width = 4096
        output = StringIO()
        yaml.dump(json.loads(text), output)
        text = output.getvalue()
    temp_filename = window._temporary_filename()
    try:
        temp_filename.write_text(text, encoding='utf-8')
        runner = CWLRunner()
        valid = runner.validate(str(temp_filename))
        return valid, getattr(runner, 'stderr', '') or ''
    finally:
        if temp_filename.exists():
            temp_filename.unlink()


def suggestFixForValidation(window) -> None:
    """Tools > Suggest a fix for the validation errors: an invalid document goes straight into Fix with AI."""
    try:
        valid, errors = validateDocument(window)
    except Exception as e:
        logger.warning(f"Validation before the fix failed: {e}")
        QMessageBox.warning(window, "Validation Error", f"An error occurred during validation:\n{e}")
        return
    if valid:
        QMessageBox.information(window, "Validation Results", "The document is valid: there is nothing to fix.")
        return
    suggestFix(window, errors)
