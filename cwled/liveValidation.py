"""
Live validation of the document in the Code tab, and the autocompletion of CWL words in its editor.

While the Code tab is shown, the text of the editor is checked in a worker thread DEBOUNCE_MS after the
last edit, when the setting ``live_validation`` is on. The messages go to the Problems panel and the lines
they are about are underlined in the editor. The Check button of the panel validates at any time.
"""
import logging
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.Qsci import QsciAPIs, QsciScintilla

import data
import theme
from cwlKeywords import completionWords
from problems import Problem, parseProblems
from ProblemsPanel import ProblemsPanel

DEBOUNCE_MS = 1500              # quiet time after the last edit before the document is checked
AUTOCOMPLETE_THRESHOLD = 2      # letters typed before the list of CWL words opens
SHORTCUTS = ('Ctrl+Space', 'Meta+Space')   # Qt's Meta is the Control key on the Mac

_CWLTOOL_LOCK = threading.Lock()   # cwltool runs one document at a time


@dataclass(frozen=True)
class ValidationRun:
    valid: bool
    problems: list[Problem] = field(default_factory=list)


def validateText(text: str, document: Path | None = None) -> ValidationRun:
    """
    Validate a text in-process, as the Validate menu does (cwltool --validate).

    The text is written to a hidden copy next to the document, so that the tools it refers to resolve as
    they do for the document (the temporary folder when the document is not saved yet), and the copy is
    removed afterwards. The messages name the document, not the copy. Runs in the calling thread: it is
    meant for a worker thread.
    """
    from CWLtoolFactory import CWLRunner

    scratch = _writeCopy(text, document.parent if document else None)
    try:
        runner = CWLRunner()
        with _cwltoolLogsKeptApart(), _CWLTOOL_LOCK:
            valid = runner.validate(str(scratch))
        output = getattr(runner, 'stderr', '') or ''
    finally:
        scratch.unlink(missing_ok=True)
    if valid:
        return ValidationRun(True)
    name = document.name if document else 'document.cwl'
    problems = [replace(problem, message=problem.message.replace(scratch.name, name))
                for problem in parseProblems(output, source=scratch.name)]
    return ValidationRun(False, problems or [Problem('The document cannot be validated')])


def _writeCopy(text: str, directory: Path | None) -> Path:
    name = f'.cwled-check-{uuid.uuid4().hex[:8]}.cwl'
    for folder in (directory, tempfile.gettempdir()):
        if folder is None:
            continue
        target = Path(folder) / name
        try:
            target.write_text(text, encoding='utf-8')
            return target
        except OSError:
            continue
    raise OSError('no folder to write the copy of the document to')


@contextmanager
def _cwltoolLogsKeptApart():
    """
    cwltool logs an invalid document as an error, and the application shows every error in a dialog
    (ErrorDialogHandler, on the root logger). While a check runs, these records stay with the run, where
    the problems are read from, and no dialog opens on each pause in typing.
    """
    loggers = [logging.getLogger(name) for name in ('cwltool', 'salad')]
    saved = [each.propagate for each in loggers]
    for each in loggers:
        each.propagate = False
    try:
        yield
    finally:
        for each, propagate in zip(loggers, saved):
            each.propagate = propagate


class _Results(QObject):
    done = pyqtSignal(object)       # (revision, ValidationRun), from the worker thread to the GUI thread


class LiveValidation(QObject):
    """
    Checks the text of the code editor and shows the result in the Problems panel and in the editor.

    Args:
        codeWindow: the Code tab (TabCodeEditor.CodeWindow); its ``editor`` is the text checked.
        validate: the check, ``validate(text, document) -> ValidationRun``, document being the path of the
            file (None when it is not saved yet). Tests replace it.
    """

    def __init__(self, codeWindow, validate=validateText):
        super().__init__(codeWindow)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.codeWindow = codeWindow
        self.editor = codeWindow.editor
        self._validate = validate
        self._revision = 0          # counts the edits: the result of an earlier text is dropped
        self._busy = False          # a check runs in the worker thread (never two at once)
        self._pending = False       # a check was asked for while one ran: it starts when that one ends
        self._dirty = True          # the text changed since it was last checked
        self._markedLines: set[int] = set()
        self.apis = None
        self._lexer = None

        self.panel = ProblemsPanel()
        self.panel.jumpRequested.connect(self.jumpToLine)
        self.panel.checkRequested.connect(self.checkNow)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._onQuiet)
        self._results = _Results(self)
        self._results.done.connect(self._onResult)

        self._indicator = self.editor.indicatorDefine(QsciScintilla.IndicatorStyle.SquiggleIndicator)
        self.editor.setIndicatorForegroundColor(QColor(theme.RED), self._indicator)
        self.editor.textChanged.connect(self._onTextChanged)
        codeWindow.installEventFilter(self)     # a check that waited for the Code tab starts when it is shown
        self._shortcuts = [QShortcut(QKeySequence(keys), self.editor) for keys in SHORTCUTS]
        for shortcut in self._shortcuts:
            shortcut.activated.connect(self.autocompleteNow)

    # --- when a check runs ---------------------------------------------------------------

    def automatic(self) -> bool:
        """The setting ``live_validation``: check while typing."""
        return bool((data.configuration or {}).get('live_validation', True))

    def checkNow(self):
        """Check the document now, whatever the setting says (the Check button)."""
        self._requestRun()

    def eventFilter(self, watched, event):
        if watched is self.codeWindow and event.type() == QEvent.Type.Show and self._dirty:
            self._restartTimer()
        return False

    def _onTextChanged(self):
        self._revision += 1
        self._dirty = True
        self._restartTimer()

    def _restartTimer(self):
        if self.automatic() and self.codeWindow.isVisible():
            self._timer.start(DEBOUNCE_MS)

    def _onQuiet(self):
        if self.automatic() and self.codeWindow.isVisible():
            self._requestRun()

    def _requestRun(self):
        if self._busy:
            self._pending = True
        else:
            self._start()

    # --- the check, in a worker thread ----------------------------------------------------

    def _start(self):
        self._timer.stop()
        self._busy = True
        self._pending = False
        self.panel.setChecking(True)
        args = (self._revision, self.editor.text(), self._document())
        threading.Thread(target=self._work, args=args, name='cwled-live-validation', daemon=True).start()

    def _work(self, revision: int, text: str, document: Path | None):
        try:
            run = self._validate(text, document)
        except Exception as e:      # not expected: the panel shows it, no error dialog opens
            self.logger.warning(f"The document could not be checked: {e}")
            run = ValidationRun(False, [Problem(f"The document could not be checked: {e}")])
        try:
            self._results.done.emit((revision, run))
        except RuntimeError:        # the Code tab was closed while the check ran
            pass

    def _onResult(self, payload):
        revision, run = payload
        self._busy = False
        if revision == self._revision:
            self._dirty = False
            self._show(run)
        else:
            self.logger.debug("Dropping the result for an earlier text of the document")
        if self._pending:
            self._start()
        else:
            self.panel.setChecking(False)

    def _document(self) -> Path | None:
        filePath = getattr(self.codeWindow.parent(), 'file_path', None)
        return Path(filePath) if filePath else None

    # --- the result ----------------------------------------------------------------------

    def _show(self, run: ValidationRun):
        self.logger.debug(f"Check finished: valid={run.valid}, {len(run.problems)} problem(s)")
        self.panel.setProblems(run.problems)
        self._mark(run.problems)

    def _mark(self, problems: list[Problem]):
        lines = self.editor.lines()
        last = max(lines - 1, 0)
        self.editor.clearIndicatorRange(0, 0, last, self.editor.lineLength(last), self._indicator)
        self._markedLines = set()
        for problem in problems:
            if problem.line is None or not 1 <= problem.line <= lines:
                continue
            row = problem.line - 1
            self.editor.fillIndicatorRange(row, 0, row, self.editor.lineLength(row), self._indicator)
            self._markedLines.add(problem.line)

    def jumpToLine(self, line: int):
        """Move the cursor of the editor to a line (1-based), as a click on a problem does."""
        row = min(max(line - 1, 0), max(self.editor.lines() - 1, 0))
        self.editor.ensureLineVisible(row)
        self.editor.setCursorPosition(row, 0)
        self.editor.setFocus()

    # --- autocompletion ------------------------------------------------------------------

    def attachAutocompletion(self, lexer):
        """
        Offer the CWL words in the editor, for the lexer that was just set on it (the lexer is set again
        each time the document is shown). The lexer is kept here: QScintilla forgets a lexer whose Python
        object goes away, and the word list needs it.
        """
        apis = QsciAPIs(lexer)
        for word in completionWords():
            apis.add(word)
        apis.prepare()
        self.apis = apis           # the list of the previous lexer goes before that lexer does
        self._lexer = lexer
        self.editor.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAPIs)
        self.editor.setAutoCompletionThreshold(AUTOCOMPLETE_THRESHOLD)

    def autocompleteNow(self):
        """Open the list of CWL words at the cursor (Ctrl+Space)."""
        self.editor.autoCompleteFromAPIs()
