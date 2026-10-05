from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QSizePolicy, QToolTip
)
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
import logging
import data
import theme
from typing import Any, Optional, Union
from PyQt6 import sip
from cwl_utils.parser import save
from CWLparser import is_optional
from JavascriptEditor import (_BATCH_EVALUATOR_JS, SAMPLE_RUNTIME, JSEvaluation, evaluationArguments,
                              expressionLibraries, mockValue, runEvaluation)
from testJob import applyTestValues, documentPath, testJobs
import json



def _shortId(value: Any) -> str:
    return str(value).split('#')[-1].split('/')[-1]


def _isExpression(text: Any) -> bool:
    return isinstance(text, str) and ('$(' in text or '${' in text)


def _schema(cwl_type: Any) -> Any:
    """The type that the sample value follows (the first non-null of a union)."""
    if isinstance(cwl_type, list):
        types = [t for t in cwl_type if t != 'null']
        return types[0] if types else None
    return cwl_type


def _typeName(schema: Any) -> Optional[str]:
    if isinstance(schema, str):
        return _shortId(schema).rstrip('?')
    return getattr(schema, 'type_', None)


def _position(binding: Any) -> int:
    position = getattr(binding, 'position', None)
    return position if isinstance(position, int) else 0


def _plain(value: Any) -> str:
    """A job value as cwl-ts prints it: files and directories by path."""
    if value is None:
        return ''
    if isinstance(value, dict):
        return str(value.get('path') or value.get('location') or '')
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


class _NoBinding:
    """An empty inputBinding (array items or records without their own)."""
    prefix = None
    separate = None
    valueFrom = None
    position = None
    itemSeparator = None


_NO_BINDING = _NoBinding()


def _joined(groups: list, separator: str) -> list:
    """Pieces of several values (each trimmed) separated by ``separator``."""
    pieces = []
    for index, group in enumerate(groups):
        if index:
            pieces.append(separator)
        pieces.append(group)
    return pieces


class _Failed(Exception):
    """An expression of the part raised an error."""


class _Omitted(Exception):
    """An expression of the part gave nothing: leave the part out."""


class _Part:
    """
    One part of the command line. Its pieces are literal text, the index of
    an expression result, or a list of pieces (an array item or record field,
    trimmed like a cwl-ts CommandLinePart).
    """

    def __init__(self, kind: str, pieces: list, loc: str, optional: bool = False, omit_empty: bool = False):
        self.kind = kind
        self.pieces = pieces
        self.loc = loc
        self.optional = optional
        self.omit_empty = omit_empty
        self.error = None

    def description(self) -> str:
        """Where the part comes from, for its tooltip."""
        if self.loc.startswith('inputs.'):
            what = f"Input {self.loc[len('inputs.'):]}"
        elif self.loc.startswith('arguments['):
            what = f"Argument {int(self.loc[len('arguments['):-1]) + 1}"
        else:
            what = {'baseCommand': "Base command", 'stdin': "Standard input",
                    'stdout': "Standard output"}.get(self.loc.split('[')[0], self.loc)
        if self.error:
            return f"{what}: {self.error}"
        return what

    def text(self, results: list) -> Optional[str]:
        """The text, or None when one of its expressions failed."""
        try:
            return self._resolve(self.pieces, results)
        except _Failed:
            return None
        except _Omitted:
            return ''

    def _resolve(self, pieces: list, results: list) -> str:
        text = ''
        for piece in pieces:
            if isinstance(piece, list):
                text += self._resolve(piece, results).strip()
            elif isinstance(piece, int):
                result = results[piece] if piece < len(results) else {'error': 'not evaluated'}
                if 'error' in result:
                    self.error = result['error']
                    raise _Failed()
                if self.omit_empty and result.get('value', '') == '':
                    raise _Omitted()
                text += result.get('value', '')
            else:
                text += piece
        return text


class CommandLine(QWidget):
    """
    Status bar displaying a command line representation of the CWL tool.
    
    This widget shows a read-only colored text view that displays
    the command line that would be executed based on the CWL tool.
    Appears at the bottom of CommandLineTool windows.
    """
    
    def __init__(self, cwl_tool: Union[Any, None], parent=None):
        """
        Initialize the CommandLine tab.
        
        Args:
            cwl_tool: The CWL tool to display
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        
        self.cwl_tool = cwl_tool
        self._job_cache = {}        # sample values per input and type
        self._expressions = []      # expressions of the current preview
        self._request = 0
        self._pending_parts = []
        self.initUI()
        testJobs().changed.connect(self._onTestValuesChanged)
        
    def initUI(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        # Composer: 10px padding plus the 1px border of each command line part
        # (the text edit adds its own 4px document margin)
        layout.setContentsMargins(7, 7, 7, 7)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        # Create a read-only text viewer with colored text support
        self.command_display = QTextEdit(self)
        self.command_display.setReadOnly(True)
        self.command_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Composer's command line font (monospace) unless configured otherwise
        settings = data.configuration.get('command_line_window', {})
        self.command_display.setFont(theme.terminalFont(settings.get('font_family'),
                                                        settings.get('font_size')))
        
        # hovering a part shows where it comes from, clicking it opens it
        self._ranges = []
        self.command_display.viewport().setMouseTracking(True)
        self.command_display.viewport().installEventFilter(self)

        # Add to layout
        layout.addWidget(self.command_display)
        self.setLayout(layout)
        
        # Populate with initial content
        self.populateFromCWL()
        
    def setCWLTool(self, cwl_tool):
        """
        Set the CWL tool and update the display.
        
        Args:
            cwl_tool: The CWL tool to display
        """
        self.cwl_tool = cwl_tool
        self.populateFromCWL()
        
    def populateFromCWL(self):
        """
        Show the command line of the tool built from a sample job, the way
        Rabix Composer does (cwl-ts generateCommandLineParts): every input
        gets a sample value (a File is /path/to/<id>.ext, a string
        <id>-string-value, ...) and the expressions are evaluated.
        """
        tool = self.cwl_tool
        if tool is None:
            self._render([])
            return
        self._expressions = []
        try:
            job = self._sampleJob(tool)
            parts = self._commandLineParts(tool, job)
        except Exception as e:
            self.logger.warning(f"Could not build the command line preview: {e}")
            self._render([])
            return
        self._request += 1
        if not self._expressions:
            self._render(parts)
            return
        # evaluate all the expressions in one go, off the GUI thread
        context = {'runtime': dict(SAMPLE_RUNTIME), 'inputs': job}
        self._pending_parts = parts
        evaluation = JSEvaluation(self._request, _BATCH_EVALUATOR_JS, evaluationArguments(
            context, expressionLibraries(tool), items=json.dumps(self._expressions, default=str)))
        evaluation.evaluated.connect(self._onEvaluated)      # queued to the GUI thread
        runEvaluation(evaluation)

    def _onEvaluated(self, request: int, result: dict):
        if sip.isdeleted(self) or request != self._request:
            return          # closed, or a newer preview is on its way
        results = result.get('results') or []
        if 'error' in result:
            results = [{'error': result['error']}] * len(self._expressions)
        self._render(self._pending_parts, results)

    # -- sample job ---------------------------------------------------------------
    def _sampleJob(self, tool) -> dict:
        """Sample input values, kept while an input keeps its type so that the
        random numbers do not change on every update, and the test values
        set in the side panel."""
        job = {}
        for parameter in getattr(tool, 'inputs', None) or []:
            input_id = _shortId(parameter.id)
            key = (input_id, json.dumps(save(parameter.type_), sort_keys=True, default=str))
            if key not in self._job_cache:
                self._job_cache[key] = mockValue(parameter.type_, input_id)
            job[input_id] = self._job_cache[key]
        return applyTestValues(job, getattr(tool, 'inputs', None), testJobs().values(documentPath(self)))

    # -- hover and click (Composer: the part is outlined, with its location) -------
    def _partAt(self, position) -> tuple:
        cursor = self.command_display.cursorForPosition(position)
        rect = self.command_display.cursorRect(cursor)
        if abs(rect.center().y() - position.y()) > rect.height():
            return None, None
        offset = cursor.position()
        for start, end, part in self._ranges:
            if start <= offset <= end:
                return part, (start, end)
        return None, None

    def eventFilter(self, watched, event) -> bool:
        if sip.isdeleted(self):
            return False
        if watched is self.command_display.viewport():
            if event.type() == QEvent.Type.MouseMove:
                part, span = self._partAt(event.position().toPoint())
                self._highlight(span)
                if part is not None:
                    QToolTip.showText(event.globalPosition().toPoint(),
                                      f"{part.description()}\nClick to show it in the editor", watched)
                else:
                    QToolTip.hideText()
            elif event.type() == QEvent.Type.Leave:
                self._highlight(None)
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton \
                    and not self.command_display.textCursor().hasSelection():
                part, _ = self._partAt(event.position().toPoint())
                if part is not None:
                    self._showPart(part)
        return super().eventFilter(watched, event)

    def _highlight(self, span):
        """Outline the hovered part (Composer: a box in the primary colour)."""
        selections = []
        if span is not None:
            selection = QTextEdit.ExtraSelection()
            selection.cursor = self.command_display.textCursor()
            selection.cursor.setPosition(span[0])
            selection.cursor.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
            selection.format.setBackground(QColor(theme.SELECTED_BG))
            selections.append(selection)
        self.command_display.setExtraSelections(selections)
        self.command_display.viewport().setCursor(Qt.CursorShape.PointingHandCursor if span
                                                  else Qt.CursorShape.IBeamCursor)

    def _showPart(self, part: '_Part'):
        """Open the input / argument the part comes from in the tool editor."""
        window = self.parent()
        while window is not None and window.__class__.__name__ != "ChildWindow":
            window = window.parent()
        editor = getattr(window, 'app_editor', None)
        if editor is None or not hasattr(editor, 'inspectCommandLinePart'):
            return
        if getattr(window, 'tabs', None) is not None:
            window.tabs.setCurrentWidget(editor)
        editor.inspectCommandLinePart(part.loc)

    def _onTestValuesChanged(self, document: str):
        if not sip.isdeleted(self) and document == documentPath(self):
            self.populateFromCWL()

    # -- command line parts (cwl-ts CommandLinePrepare / CommandLineParsers) -------
    def _expression(self, code: str, self_value: Any = None) -> int:
        self._expressions.append({'code': code, 'self': self_value})
        return len(self._expressions) - 1

    def _valuePieces(self, text: Any, self_value: Any = None) -> list:
        if _isExpression(text):
            return [self._expression(text, self_value)]
        return [_plain(text)]

    def _commandLineParts(self, tool, job: dict) -> list:
        parts = []
        base_command = getattr(tool, 'baseCommand', None) or []
        for index, command in enumerate(base_command if isinstance(base_command, list) else [base_command]):
            if command is not None:
                parts.append(_Part('baseCommand', [str(command)], f"baseCommand[{index}]"))

        items = []      # (position, sort key, part)
        for index, argument in enumerate(getattr(tool, 'arguments', None) or []):
            part = self._argumentPart(argument, f"arguments[{index}]")
            items.append((_position(argument), str(index), part))
        for parameter in getattr(tool, 'inputs', None) or []:
            input_id = _shortId(parameter.id)
            value = job.get(input_id)
            schema = _schema(parameter.type_)
            optional = is_optional(parameter)
            if _typeName(schema) == 'stdin':
                continue
            binding = getattr(parameter, 'inputBinding', None)
            if binding is None and _typeName(schema) not in ('array', 'record'):
                # e.g. an enum type with its own inputBinding (cwltool uses it)
                binding = getattr(schema, 'inputBinding', None)
            if binding is not None:
                pieces = self._bindingPieces(binding, value, schema)
                if pieces is not None:
                    items.append((_position(binding), input_id,
                                  _Part('input', pieces, f"inputs.{input_id}", optional)))
            elif _typeName(schema) == 'record' and isinstance(value, dict):
                # record fields bound on their own (as cwltool does)
                for field in getattr(schema, 'fields', None) or []:
                    field_binding = getattr(field, 'inputBinding', None)
                    name = _shortId(field.name)
                    if field_binding is None:
                        continue
                    pieces = self._bindingPieces(field_binding, value.get(name), _schema(field.type_))
                    if pieces is not None:
                        items.append((_position(field_binding), f"{input_id}.{name}",
                                      _Part('input', pieces, f"inputs.{input_id}.{name}", optional)))
        items.sort(key=lambda item: (item[0], item[1].casefold()))
        parts += [part for _, _, part in items]

        # stdin: a "stdin" input or the tool's stdin, then the stdout redirect
        stdin_inputs = [p for p in getattr(tool, 'inputs', None) or [] if _typeName(_schema(p.type_)) == 'stdin']
        if stdin_inputs:
            path = _plain(job.get(_shortId(stdin_inputs[0].id)))
            parts.append(_Part('stdin', [f"< {path}"] if path else [], "stdin"))
        elif getattr(tool, 'stdin', None):
            parts.append(_Part('stdin', ["< "] + self._valuePieces(tool.stdin), "stdin", omit_empty=True))
        if getattr(tool, 'stdout', None):
            parts.append(_Part('stdout', ["> "] + self._valuePieces(tool.stdout), "stdout", omit_empty=True))
        return parts

    def _argumentPart(self, argument, loc: str) -> '_Part':
        if isinstance(argument, str):
            return _Part('argument', self._valuePieces(argument), loc)
        prefix = getattr(argument, 'prefix', None) or ''
        separator = '' if getattr(argument, 'separate', None) is False else ' '
        value_from = getattr(argument, 'valueFrom', None)
        if value_from in (None, ''):
            return _Part('argument', [prefix], loc)
        # an argument whose value is empty is left out, prefix and all
        return _Part('argument', [prefix + separator] + self._valuePieces(value_from), loc,
                     omit_empty=_isExpression(value_from))

    def _bindingPieces(self, binding, value: Any, schema: Any):
        """The text of one bound value (cwl-ts CommandLineParsers), or None."""
        if value is None:
            return None
        prefix = getattr(binding, 'prefix', None) or ''
        separator = '' if getattr(binding, 'separate', None) is False else ' '
        value_from = getattr(binding, 'valueFrom', None)
        if isinstance(value, bool):
            if not value:
                return None
            if value_from:
                return [prefix + separator] + self._valuePieces(value_from, value)
            return [prefix]
        if value_from:
            return [prefix + separator] + self._valuePieces(value_from, value)
        if isinstance(value, list):
            item_schema = _schema(getattr(schema, 'items', None))
            item_binding = getattr(schema, 'inputBinding', None) or _NO_BINDING
            item_separator = getattr(binding, 'itemSeparator', None)
            item_separator = item_separator if isinstance(item_separator, str) else ' '
            items = [self._bindingPieces(item_binding, item, item_schema) for item in value]
            return [prefix + separator] + _joined([item for item in items if item is not None], item_separator)
        if isinstance(value, dict) and value.get('class') not in ('File', 'Directory'):
            fields = sorted(((_position(getattr(field, 'inputBinding', None)), _shortId(field.name), field)
                             for field in getattr(schema, 'fields', None) or []
                             if getattr(field, 'inputBinding', None) is not None),
                            key=lambda item: (item[0], item[1].casefold()))
            parts = [self._bindingPieces(field.inputBinding, value.get(name), _schema(field.type_))
                     for _, name, field in fields]
            return [prefix + separator] + _joined([part for part in parts if part is not None], ' ')
        return [prefix + separator + _plain(value)]

    # -- display ------------------------------------------------------------------
    def _render(self, parts: list, results: Optional[list] = None):
        """Composer ct-command-line-preview: the parts, trimmed, coloured by kind."""
        formats = {
            'baseCommand': theme.CODE_BASE_CMD, 'input': theme.CODE_INPUTS, 'argument': theme.CODE_ARGS,
            'stdin': theme.CODE_STREAM, 'stdout': theme.CODE_STREAM,
            'error': theme.CODE_ERROR, 'warning': theme.CODE_WARNING,
        }
        self._last_render = (parts, results)
        self.command_display.clear()
        self.command_display.setExtraSelections([])
        self._ranges = []
        cursor = self.command_display.textCursor()
        shown = 0
        for part in parts:
            kind, text = part.kind, part.text(results or [])
            if text is None:
                kind, text = 'error', f"<error at {part.loc}>"
            text = text.strip()
            if not text:
                continue
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(formats.get(kind, theme.CODE_STREAM)))
            # CWLed: optional inputs in italics
            text_format.setFontItalic(kind == 'input' and part.optional)
            if shown:
                cursor.insertText(" ", QTextCharFormat())
            start = cursor.position()
            cursor.insertText(text, text_format)
            self._ranges.append((start, cursor.position(), part))
            shown += 1
        if not shown:
            placeholder = QTextCharFormat()
            placeholder.setForeground(QColor(theme.TEXT_MUTED))
            cursor.insertText("Your command line preview will appear here", placeholder)

    def onThemeChanged(self):
        last = getattr(self, '_last_render', None)
        if last is not None:
            self._render(*last)

    def updateCommandLine(self):
        """
        Update the command line display based on the current tool state.
        Can be called externally when the tool is modified.
        """
        self.populateFromCWL()
