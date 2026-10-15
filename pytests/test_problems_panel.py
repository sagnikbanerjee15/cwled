"""The Problems panel, the live validation and the autocompletion of the Code tab."""
import logging
import threading
import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.Qsci import QsciLexerYAML, QsciScintilla

import liveValidation
from conftest import FIXTURES
from cwlKeywords import completionWords
from problems import Problem, parseProblems
from liveValidation import ValidationRun
from qt_helpers import pump, wait_until

BAD_TYPE = """cwlVersion: v1.2
class: CommandLineTool
baseCommand: echo
inputs:
  msg:
    type: strin
    inputBinding:
      position: 1
outputs: []
"""

# What cwltool printed for an unknown type in a document named bad.cwl (the paths of a run from the sandbox)
UNKNOWN_TYPE = """ERROR Tool definition failed validation:
../../../../../../tmp/claude-502/probe/bad.cwl:4:1: checking field 'inputs'
../../../../../../tmp/claude-502/probe/bad.cwl:5:3:   checking object
                                                      '../../../../../../tmp/claude-502/probe/bad.cwl#msg'
../../../../../../tmp/claude-502/probe/bad.cwl:6:5:     Field 'type' references unknown identifier
                                                        'strin', tried
                                                        file:///tmp/claude-502/probe/bad.cwl#strin
"""


# --- the parser (pure Python) ---------------------------------------------------------------

def test_a_message_with_a_location_keeps_its_line_and_column():
    problems = parseProblems("file:///tmp/tool.cwl:12:3: Expected a string\n", source='tool.cwl')
    assert problems == [Problem('Expected a string', 12, 3, 'file:///tmp/tool.cwl')]


def test_a_message_without_a_location_has_no_line():
    problems = parseProblems("Unexpected error: boom\n", source='tool.cwl')
    assert problems == [Problem('Unexpected error: boom')]
    assert problems[0].line is None


def test_several_messages_each_keep_their_own_line():
    output = ("ERROR Tool definition failed validation:\n"
              "file:///tmp/tool.cwl:3:1: first problem\n"
              "ERROR second error\n"
              "file:///tmp/tool.cwl:9:4: second problem\n")
    problems = parseProblems(output, source='tool.cwl')
    assert [(p.message, p.line, p.column) for p in problems] == [
        ('first problem', 3, 1), ('second error', None, None), ('second problem', 9, 4)]


def test_the_innermost_message_of_a_nested_error_is_the_problem():
    problems = parseProblems(UNKNOWN_TYPE, source='bad.cwl')
    assert len(problems) == 1
    assert problems[0].line == 6
    assert problems[0].column == 5
    assert problems[0].message == ("Field 'type' references unknown identifier 'strin', tried "
                                   "file:///tmp/claude-502/probe/bad.cwl#strin")


def test_a_message_about_another_file_has_no_line_so_nothing_jumps_to_it():
    output = "ERROR Tool definition failed validation:\n/tmp/other/step.cwl:7:2: unknown field\n"
    problems = parseProblems(output, source='document.cwl')
    assert problems == [Problem('/tmp/other/step.cwl:7:2: unknown field', path='/tmp/other/step.cwl')]
    assert problems[0].line is None


def test_a_path_with_spaces_is_read_whole():
    problems = parseProblems("/Users/me/My Folder/tool.cwl:3:1: bad\n", source='tool.cwl')
    assert problems == [Problem('bad', 3, 1, '/Users/me/My Folder/tool.cwl')]


def test_a_nested_yaml_error_gives_one_problem_per_location():
    output = ("ERROR Tool definition failed validation:\n"
              "file:///tmp/broken.cwl:3:14: while parsing a flow sequence\n"
              "file:///tmp/broken.cwl:4:7:    expected ',' or ']', but got ':'\n")
    problems = parseProblems(output, source='broken.cwl')
    assert [(p.line, p.message) for p in problems] == [
        (3, 'while parsing a flow sequence'), (4, "expected ',' or ']', but got ':'")]


def test_a_message_without_location_continues_on_the_next_line():
    output = ("ERROR I'm sorry, I couldn't load this CWL file, try again with --debug for more information.\n"
              "The error was: workflowjobj must be a dict\n")
    problems = parseProblems(output, source='empty.cwl')
    assert problems == [Problem("I'm sorry, I couldn't load this CWL file, try again with --debug for more "
                                "information. The error was: workflowjobj must be a dict")]


def test_information_lines_are_not_problems():
    assert parseProblems("INFO Starting validation\nDEBUG details\n", source='x.cwl') == []


def test_the_heading_alone_still_gives_a_problem_and_no_output_gives_none():
    assert [p.message for p in parseProblems("ERROR Tool definition failed validation:\n")] == [
        'Tool definition failed validation:']
    assert parseProblems("") == []


# --- the panel ------------------------------------------------------------------------------

def test_the_panel_counts_its_problems_and_lists_them_with_their_lines(qapp):
    from ProblemsPanel import ProblemsPanel
    panel = ProblemsPanel()
    assert panel.header.text() == 'Problems (0)'
    panel.setProblems([Problem('bad type', 5, 3), Problem('no line here')])
    assert panel.header.text() == 'Problems (2)'
    assert panel.list.item(0).text() == 'Line 5: bad type'
    assert panel.list.item(1).text() == 'no line here'
    assert panel.problemLines() == [5, None]


def test_the_panel_collapses_and_expands_with_its_header(qapp):
    from ProblemsPanel import ProblemsPanel
    panel = ProblemsPanel()
    panel.setProblems([Problem('bad', 1)])
    panel.header.setChecked(False)
    assert not panel.list.isVisibleTo(panel)
    panel.header.setChecked(True)
    assert not panel.list.isHidden()


# --- the live validation (the Code tab on its own, with a fake check unless the test says otherwise) ----

class Checks:
    """Stands in for the validator: records the texts it is asked to check and answers with ``run``."""

    def __init__(self):
        self.texts = []
        self.run = ValidationRun(True)

    def __call__(self, text, directory=None):
        self.texts.append(text)
        return self.run


@pytest.fixture
def code(cwled_config, qapp):
    from TabCodeEditor import CodeWindow
    window = CodeWindow(title='test')
    window.show()
    pump(2)
    yield window
    window.close()


@pytest.fixture
def checks(code):
    fake = Checks()
    code.live_validation._validate = fake
    return fake


@pytest.fixture
def quick(monkeypatch):
    """The quiet time before a check is short, so that the tests are fast."""
    monkeypatch.setattr(liveValidation, 'DEBOUNCE_MS', 40)
    return 40


def test_the_check_runs_once_after_the_last_edit(code, checks, quick):
    for text in ('a', 'ab', 'abc'):
        code.editor.setText(text)
    assert checks.texts == [], "nothing is checked before the quiet time"
    wait_until(lambda: checks.texts)
    wait_until(lambda: not code.live_validation._busy)
    assert checks.texts == ['abc']


def test_a_result_for_an_earlier_text_is_not_shown(code, monkeypatch, quick):
    live = code.live_validation
    started, release = threading.Event(), threading.Event()
    calls = []

    def check(text, directory=None):
        calls.append(text)
        if len(calls) == 1:             # the first check is slow: the text changes while it runs
            started.set()
            release.wait(10)
            return ValidationRun(False, [Problem('old problem', 1)])
        return ValidationRun(False, [Problem('new problem', 2)])

    shown = []
    real = live.panel.setProblems
    monkeypatch.setattr(live.panel, 'setProblems', lambda problems, *args: (shown.append(problems), real(problems, *args)))
    live._validate = check
    code.editor.setText('one\n')
    wait_until(started.is_set)
    code.editor.setText('one\ntwo\n')
    release.set()
    wait_until(lambda: len(calls) == 2 and not live._busy)
    assert [p.message for problems in shown for p in problems] == ['new problem']
    assert live.panel.problemLines() == [2]


def test_checks_never_overlap_and_the_last_text_is_checked(code, quick):
    live = code.live_validation
    running, peak = [], [0]
    lock = threading.Lock()
    texts = []

    def check(text, directory=None):
        with lock:
            running.append(text)
            peak[0] = max(peak[0], len(running))
        time.sleep(0.15)
        with lock:
            running.remove(text)
        texts.append(text)
        return ValidationRun(True)

    live._validate = check
    code.editor.setText('a')
    wait_until(lambda: running)
    assert not live.panel.checkButton.isEnabled(), "the Check button waits for the run"
    for text in ('b', 'c', 'd'):
        code.editor.setText(text)
        pump(3)
    wait_until(lambda: texts and texts[-1] == 'd' and not live._busy, timeout=10)
    assert peak[0] == 1
    assert live.panel.checkButton.isEnabled()


def test_nothing_is_checked_by_itself_when_the_setting_is_off(code, checks, cwled_config, quick):
    cwled_config['live_validation'] = False
    code.editor.setText('x')
    QTest.qWait(150)
    assert checks.texts == []
    code.live_validation.checkNow()     # the Check button still checks
    wait_until(lambda: checks.texts == ['x'])
    wait_until(lambda: not code.live_validation._busy)


def test_the_code_tab_is_checked_when_it_is_shown_not_while_hidden(code, checks, quick):
    code.hide()
    pump(2)
    code.editor.setText('y')
    QTest.qWait(150)
    assert checks.texts == []
    code.show()
    wait_until(lambda: checks.texts == ['y'])
    wait_until(lambda: not code.live_validation._busy)


def test_problems_are_listed_and_marked_and_the_marks_go_when_valid(code, checks):
    live = code.live_validation
    code.editor.setText('one\ntwo\nthree\n')
    checks.run = ValidationRun(False, [Problem('bad type', 2, 1), Problem('no line')])
    live.checkNow()
    wait_until(lambda: live.panel.header.text() == 'Problems (2)' and not live._busy)
    assert live.panel.problemLines() == [2, None]
    assert live._markedLines == {2}
    line_two = code.editor.positionFromLineIndex(1, 0)
    assert code.editor.SendScintilla(QsciScintilla.SCI_INDICATORVALUEAT, live._indicator, line_two) == 1

    checks.run = ValidationRun(True)
    live.checkNow()
    wait_until(lambda: live.panel.header.text() == 'Problems (0)' and not live._busy)
    assert live._markedLines == set()
    assert code.editor.SendScintilla(QsciScintilla.SCI_INDICATORVALUEAT, live._indicator, line_two) == 0


def test_clicking_a_problem_moves_the_cursor_to_its_line(code, checks):
    live = code.live_validation
    code.editor.setText('a\nb\nc\nd\n')
    checks.run = ValidationRun(False, [Problem('bad', 3, 1), Problem('no line here')])
    live.checkNow()
    wait_until(lambda: live.panel.header.text() == 'Problems (2)' and not live._busy)

    listWidget = live.panel.list
    QTest.mouseClick(listWidget.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     listWidget.visualItemRect(listWidget.item(0)).center())
    assert code.editor.getCursorPosition()[0] == 2


def test_a_problem_without_a_line_does_not_move_the_cursor(code, checks):
    live = code.live_validation
    code.editor.setText('a\nb\nc\n')
    code.editor.setCursorPosition(1, 0)
    checks.run = ValidationRun(False, [Problem('no line here')])
    live.checkNow()
    wait_until(lambda: live.panel.header.text() == 'Problems (1)' and not live._busy)

    listWidget = live.panel.list
    QTest.mouseClick(listWidget.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     listWidget.visualItemRect(listWidget.item(0)).center())
    assert code.editor.getCursorPosition()[0] == 1


def test_the_real_validator_marks_the_line_of_an_unknown_type(code):
    live = code.live_validation
    code.editor.setText(BAD_TYPE)
    live.checkNow()
    wait_until(lambda: live.panel.header.text() != 'Problems (0)' and not live._busy, timeout=60)
    assert 6 in live.panel.problemLines()   # "type: strin" is line 6 of the text
    assert 6 in live._markedLines
    messages = [live.panel.list.item(row).text() for row in range(live.panel.list.count())]
    assert any('document.cwl#strin' in message for message in messages), "the document is named, not the copy"
    assert not any('.cwled-check-' in message for message in messages)


def test_the_real_validator_finds_no_problem_in_a_valid_tool(code):
    live = code.live_validation
    code.editor.setText((FIXTURES / '01-hello-world.cwl').read_text(encoding='utf-8'))
    live.checkNow()
    wait_until(lambda: not live._busy, timeout=60)
    assert live.panel.header.text() == 'Problems (0)'
    assert live.panel.note.text() == 'No problems found.'


def test_an_invalid_text_logs_no_error_so_no_error_dialog_opens(code):
    errors = []

    class Catch(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                errors.append(record)

    handler = Catch()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        code.editor.setText(BAD_TYPE)
        code.live_validation.checkNow()
        wait_until(lambda: not code.live_validation._busy, timeout=60)
    finally:
        root.removeHandler(handler)
    assert errors == []


# --- the autocompletion -----------------------------------------------------------------------

def test_the_completion_words_are_unique_sorted_and_cover_the_cwl_fields():
    words = completionWords()
    assert len(words) == len(set(words))
    assert words == sorted(words)
    for word in ('class', 'cwlVersion', 'inputs', 'outputs', 'steps', 'baseCommand', 'arguments',
                 'requirements', 'hints', 'DockerRequirement', 'InitialWorkDirRequirement',
                 'CommandLineTool', 'ExpressionTool', 'Workflow', 'WorkflowStep', 'valueFrom',
                 'inputBinding', 'outputBinding', 'position', 'glob'):
        assert word in words


def test_the_editor_offers_the_words_after_two_letters(code):
    lexer = QsciLexerYAML()
    code.editor.setLexer(lexer)
    code.live_validation.attachAutocompletion(lexer)
    assert code.editor.autoCompletionSource() == QsciScintilla.AutoCompletionSource.AcsAPIs
    assert code.editor.autoCompletionThreshold() == 2
    code.editor.setFocus()
    pump(2)
    QTest.keyClicks(code.editor, 'cl')
    pump(3)
    assert code.editor.isListActive()


def test_ctrl_space_opens_the_list_of_words(code):
    from PyQt6.QtGui import QKeySequence
    lexer = QsciLexerYAML()
    code.editor.setLexer(lexer)
    code.live_validation.attachAutocompletion(lexer)
    shortcuts = {shortcut.key().toString() for shortcut in code.live_validation._shortcuts}
    assert QKeySequence('Ctrl+Space').toString() in shortcuts
    code.editor.setFocus()
    pump(2)
    code.editor.setText('in')
    code.editor.setCursorPosition(0, 2)
    code.live_validation.autocompleteNow()
    pump(3)
    assert code.editor.isListActive()


# --- the setting -------------------------------------------------------------------------------

def test_the_setting_is_on_by_default(cwled_config):
    assert cwled_config.get('live_validation') is True


def test_the_general_tab_has_the_setting(window, cwled_config):
    from ConfigDialog import ConfigDialog
    assert ConfigDialog(window).live_validation_check.isChecked()
    cwled_config['live_validation'] = False
    assert not ConfigDialog(window).live_validation_check.isChecked()


def test_a_document_of_the_window_is_checked_after_the_pause_in_its_code_tab(window):
    from qt_helpers import open_documents
    doc = open_documents(window, ['01-hello-world.cwl'])['01-hello-world.cwl']
    doc.tabs.setCurrentWidget(doc.code_editor)
    pump(5)
    live = doc.code_editor.live_validation
    assert live.apis is not None, "the document's Code tab offers the CWL words"
    doc.code_editor.editor.setText(BAD_TYPE)
    wait_until(lambda: live.panel.header.text() != 'Problems (0)' and not live._busy, timeout=60)
    assert 6 in live.panel.problemLines()


def test_the_panel_says_it_is_not_checked_yet_until_a_check_ran(qapp):
    from ProblemsPanel import ProblemsPanel
    panel = ProblemsPanel()
    assert panel.note.text() == 'Not checked yet.'
    panel.setProblems([])
    assert panel.note.text() == 'No problems found.'
    panel.setProblems([Problem('bad', 1)])
    assert panel.note.text() == ''
