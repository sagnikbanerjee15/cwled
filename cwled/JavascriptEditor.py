"""
Rabix Composer "Expression Editor".

A modal editor for CWL expressions: the code on the left, the result of
evaluating it below (live, against a sample job), and the context the
expression can use (runtime, inputs, self) as a tree on the right. Double
clicking an entry of the tree inserts its path at the cursor.

The sample job follows Rabix Composer / cwl-ts (JobHelper.generateMockJobData,
V1CommandLineToolModel.getContext) and expressions are evaluated the way
cwl-ts' ExpressionEvaluator does, with Qt's built-in JavaScript engine
(QJSEngine), so no Node.js installation is needed.
"""
import json
import logging
import random
import re
from typing import Any, Callable, Optional

from PyQt6 import sip
from PyQt6.Qsci import QsciLexerJavaScript, QsciScintilla
from PyQt6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut
from PyQt6.QtQml import QJSEngine, QJSValue
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame,
                             QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QStyle, QStyledItemDelegate,
                             QStyleOptionViewItem, QToolButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

import data
import theme
from testJob import applyTestValues, documentPath, testJobs

PLACEHOLDER_RESULT = "Expression result will appear here"
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_TYPE = Qt.ItemDataRole.UserRole + 1

# cwl-ts ExpressionEvaluator.grabExpressions + evaluate (v1.0), run by
# QJSEngine. The context (runtime, inputs, self) is set as globals, as in a
# cwl-ts sandbox; __cwledEvaluate returns the value or throws.
_EVALUATOR_CORE_JS = r"""
function __cwledGrab(str) {
    let tokens = [], i = 0, state = 'literal', literal = '', expr = '', func = '';
    let brackets = 0, parens = 0;
    while (i < str.length) {
        const c = str[i];
        if (state === 'literal') {
            if (c === '$' && str[i + 1] === '(') {
                if (literal) { tokens.push({type: 'literal', value: literal}); literal = ''; }
                i++; expr = ''; state = 'expr';
            } else if (c === '$' && str[i + 1] === '{') {
                if (literal) { tokens.push({type: 'literal', value: literal}); literal = ''; }
                i++; func = ''; state = 'func';
            } else if (c === '\\' && str[i + 1] === '$') {
                literal += '\\$'; i++;
            } else { literal += c; }
        } else if (state === 'expr') {
            if (c === '(') { expr += c; parens++; }
            else if (c === ')') {
                if (parens === 0) { tokens.push({type: 'expr', value: expr}); state = 'literal'; }
                else { expr += c; parens--; }
            } else { expr += c; }
        } else {
            if (c === '{') { func += c; brackets++; }
            else if (c === '}') {
                if (brackets === 0) { tokens.push({type: 'func', value: func}); state = 'literal'; }
                else { func += c; brackets--; }
            } else { func += c; }
        }
        i++;
    }
    if (state === 'literal' && literal.length > 0) { tokens.push({type: 'literal', value: literal}); }
    if (state === 'expr' || state === 'func') { tokens = [{type: 'literal', value: str}]; }
    return tokens;
}
function __cwledSetContext(context) {
    const global = (0, eval)('this');
    ['runtime', 'inputs', 'self'].forEach(function (key) { global[key] = context[key]; });
}
function __cwledEvaluate(code, lib) {
    const run = function (script) { return (0, eval)(script); };
    const values = __cwledGrab(code).map(t => t.type === 'func' ? run('(function() {' + lib + '\n\n' + t.value + '})()')
                                       : t.type === 'expr' ? run(lib + '\n\n' + t.value)
                                       : t.value);
    return values.length === 1 ? values[0] : values.join('');
}
"""

# The editor preview: (code, context JSON, libraries JSON) -> {result | error}
_EVALUATOR_JS = _EVALUATOR_CORE_JS + r"""
(function (code, contextJson, librariesJson) {
    if (code === '') { return JSON.stringify({result: null}); }
    __cwledSetContext(JSON.parse(contextJson));
    try {
        const result = __cwledEvaluate(code, JSON.parse(librariesJson).join('\n\n'));
        return JSON.stringify({result: JSON.stringify(result, null, 4) || 'undefined'});
    } catch (e) {
        return JSON.stringify({error: e.name + ': ' + e.message});
    }
})(__cwled_code, __cwled_context, __cwled_libraries)
"""

# Many expressions at once (the command line preview):
# ([{code, self}] JSON, context JSON, libraries JSON) -> {results: [{value | error}]}
_BATCH_EVALUATOR_JS = _EVALUATOR_CORE_JS + r"""
(function (itemsJson, contextJson, librariesJson) {
    const lib = JSON.parse(librariesJson).join('\n\n');
    const results = JSON.parse(itemsJson).map(function (item) {
        const context = JSON.parse(contextJson);
        context.self = item.self === undefined ? null : item.self;
        __cwledSetContext(context);
        try {
            const value = __cwledEvaluate(item.code, lib);
            return {value: value === undefined || value === null ? '' : String(value)};
        } catch (e) {
            return {error: e.name + ': ' + e.message};
        }
    });
    return JSON.stringify({results: results});
})(__cwled_items, __cwled_context, __cwled_libraries)
"""
EVALUATION_TIMEOUT_MS = 3000


class JSEvaluation(QThread):
    """Runs a script in a fresh QJSEngine on a worker thread, so a runaway
    expression can be interrupted without freezing the window. ``arguments``
    (name -> string) become globals of the script, which returns JSON."""

    evaluated = pyqtSignal(int, dict)

    def __init__(self, request: int, script: str, arguments: dict, parent=None):
        super().__init__(parent)
        self.request = request
        self._script = script
        self._arguments = arguments
        self._engine = None
        self.timed_out = False

    def run(self):
        engine = QJSEngine()
        self._engine = engine
        globals_ = engine.globalObject()
        for name, value in self._arguments.items():
            globals_.setProperty(name, QJSValue(value))
        # evaluate(), unlike QJSValue.call(), lets go of Python's GIL while the
        # script runs, so the GUI thread can interrupt a runaway expression
        value = engine.evaluate(self._script)
        self._engine = None
        if self.timed_out:
            result = {'error': f"Error: Script execution timed out after {EVALUATION_TIMEOUT_MS}ms"}
        elif value.isError():
            result = {'error': value.toString()}
        else:
            try:
                result = json.loads(value.toString())
            except ValueError:
                result = {'error': "The expression could not be evaluated."}
        self.evaluated.emit(self.request, result)

    def interrupt(self, timed_out: bool = False):
        engine = self._engine
        if engine is not None and self.isRunning():
            self.timed_out = timed_out
            engine.setInterrupted(True)    # thread-safe

    def startWithTimeout(self, milliseconds: int = EVALUATION_TIMEOUT_MS):
        timer = QTimer(self)               # lives and dies with the evaluation
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.interrupt(timed_out=True))
        timer.start(milliseconds)
        self.start()


class _Evaluations(QObject):
    """Keeps evaluations (and whatever waits for their result) alive until
    they finish, whatever happens to the widget that started them."""

    def __init__(self):
        super().__init__()
        self._running = {}

    def start(self, evaluation: 'JSEvaluation', companion: Any = None):
        self._running[evaluation] = companion
        evaluation.finished.connect(self._release)      # queued to the GUI thread
        evaluation.startWithTimeout()

    def _release(self):
        evaluation = self.sender()
        evaluation.wait()
        self._running.pop(evaluation, None)
        evaluation.deleteLater()


_evaluations = None


def runEvaluation(evaluation: 'JSEvaluation', companion: Any = None):
    """Start an evaluation that nothing has to wait for (or clean up)."""
    global _evaluations
    if _evaluations is None:
        _evaluations = _Evaluations()
    _evaluations.start(evaluation, companion)


class _Reply(QObject):
    """Hands an evaluation result to a callback on the GUI thread."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def deliver(self, request: int, result: dict):
        results = result.get('results') or []
        error = result.get('error') or (results[0].get('error') if results else None)
        try:
            self._callback(error)
        except RuntimeError:
            pass        # the field is gone


def documentTool(widget) -> Any:
    """The CWL document of the ChildWindow a widget belongs to."""
    while widget is not None:
        if widget.__class__.__name__ == "ChildWindow":
            return getattr(widget, 'cwl_tool', None)
        widget = widget.parent()
    return None


def validateExpression(context_widget, port: Any, code: str, report: Callable[[Optional[str]], None]):
    """Evaluate ``code`` as the Expression Editor would (sample job, test
    values, expression library) and report its error, or None, to ``report``."""
    tool = documentTool(context_widget)
    context = expressionContext(tool, port, testJobs().values(documentPath(context_widget)))
    item = {'code': code, 'self': context.get('self')}
    evaluation = JSEvaluation(0, _BATCH_EVALUATOR_JS, evaluationArguments(
        context, expressionLibraries(tool), items=json.dumps([item], default=str)))
    reply = _Reply(report)
    evaluation.evaluated.connect(reply.deliver)       # queued to the GUI thread
    runEvaluation(evaluation, reply)


def evaluationArguments(context: dict, libraries: list, **strings) -> dict:
    """Script globals for the evaluators: the JSON context and libraries."""
    arguments = {'__cwled_context': json.dumps(context, default=str),
                 '__cwled_libraries': json.dumps(libraries, default=str)}
    arguments.update({f'__cwled_{name}': value for name, value in strings.items()})
    return arguments


# ---------------------------------------------------------------------------
# Sample job (cwl-ts JobHelper.generateMockJobData)
# ---------------------------------------------------------------------------
def _shortId(value: Any) -> str:
    return str(value).split('#')[-1].split('/')[-1]


def _mockFile(name: str) -> dict:
    return {
        'path': f'/path/to/{name}.ext',
        'class': 'File',
        'size': 0,
        'contents': 'file contents',
        'metadata': {},
        'secondaryFiles': [],
        'basename': f'{name}.ext',
        'nameroot': name,
        'nameext': '.ext',
    }


def _typeOf(cwl_type: Any):
    """(type, items, symbols, fields) of a CWL type, like cwl-ts ParameterTypeModel."""
    if isinstance(cwl_type, list):
        non_null = [t for t in cwl_type if t != 'null']
        cwl_type = non_null[0] if non_null else 'null'
    if isinstance(cwl_type, str):
        name = _shortId(cwl_type).rstrip('?')
        if name.endswith('[]'):
            return 'array', name[:-2], None, None
        return name, None, None, None
    kind = getattr(cwl_type, 'type_', None)
    if kind == 'array':
        items = getattr(cwl_type, 'items', None)
        item_type = _typeOf(items)
        return 'array', item_type[0], item_type[2], item_type[3]
    if kind == 'enum':
        return 'enum', None, [_shortId(s) for s in (getattr(cwl_type, 'symbols', None) or [])], None
    if kind == 'record':
        return 'record', None, None, getattr(cwl_type, 'fields', None) or []
    return None, None, None, None


def mockValue(cwl_type: Any, name: str) -> Any:
    kind, items, symbols, fields = _typeOf(cwl_type)
    scalars = {
        'File': lambda: _mockFile(name),
        'stdin': lambda: _mockFile(name),
        'Directory': lambda: {'path': f'/path/to/{name}', 'class': 'Directory', 'basename': name},
        'enum': lambda: symbols[0] if symbols else name,
        'string': lambda: f'{name}-string-value',
        'int': lambda: random.randint(0, 10),
        'long': lambda: random.randint(0, 10),
        'float': lambda: random.uniform(0, 11),
        'double': lambda: random.uniform(0, 11),
        'boolean': lambda: True,
        'record': lambda: {},
        'map': lambda: {},
        'Any': lambda: {},
    }
    if kind == 'array':
        arrays = {
            'File': lambda: [_mockFile(f'{name}-1'), _mockFile(f'{name}-2')],
            'stdin': lambda: [_mockFile(f'{name}-1'), _mockFile(f'{name}-2')],
            'Directory': lambda: [{'path': f'/path/to/{name}', 'class': 'Directory', 'basename': name}] * 2,
            'string': lambda: [f'{name}-string-value-1', f'{name}-string-value-2'],
            'int': lambda: [random.randint(0, 10), random.randint(0, 10)],
            'float': lambda: [random.uniform(0, 11), random.uniform(0, 11)],
            'record': lambda: [{}],
            'map': lambda: [{}],
            'enum': lambda: [symbols[0] if symbols else name],
            'boolean': lambda: [True, True],
        }
        if items == 'record' and fields:
            record = {_shortId(f.name): mockValue(f.type_, _shortId(f.name)) for f in fields}
            return [json.loads(json.dumps(record)), json.loads(json.dumps(record))]
        return arrays[items]() if items in arrays else None
    if kind == 'record' and fields:
        return {_shortId(f.name): mockValue(f.type_, _shortId(f.name)) for f in fields}
    return scalars[kind]() if kind in scalars else None


# The sample runtime: Composer's cores and ram, and the other CWL runtime
# fields so that e.g. $(runtime.outdir) has a value
SAMPLE_RUNTIME = {'outdir': '/path/to/outdir', 'tmpdir': '/path/to/tmpdir', 'cores': 1, 'ram': 1000,
                  'outdirSize': 1024, 'tmpdirSize': 1024}


def expressionContext(cwl_tool: Any, port: Any, test_values: Optional[dict] = None) -> dict:
    """runtime / inputs / self as Composer provides them to expressions;
    ``test_values`` (as typed in the side panel) replace sample values."""
    inputs = {}
    for parameter in (getattr(cwl_tool, 'inputs', None) or []):
        input_id = _shortId(parameter.id)
        inputs[input_id] = mockValue(getattr(parameter, 'type_', None), input_id)
    if test_values:
        inputs = applyTestValues(inputs, getattr(cwl_tool, 'inputs', None), test_values)
    for step_input in (getattr(port, 'in_', None) or []):
        inputs.setdefault(_shortId(step_input.id), None)
    context = {'runtime': dict(SAMPLE_RUNTIME), 'inputs': inputs}
    kind = type(port).__name__
    if 'InputParameter' in kind or 'InputRecordField' in kind:
        port_id = _shortId(getattr(port, 'id', None) or getattr(port, 'name', ''))
        context['self'] = inputs[port_id] if port_id in inputs else \
            mockValue(getattr(port, 'type_', None), port_id)
    elif 'OutputParameter' in kind or 'OutputRecordField' in kind:
        port_id = _shortId(getattr(port, 'id', None) or getattr(port, 'name', ''))
        context['self'] = [_mockFile(f'{port_id}-1'), _mockFile(f'{port_id}-2')]
    return context


def expressionLibraries(cwl_tool: Any) -> list:
    libraries = []
    for requirement in (getattr(cwl_tool, 'requirements', None) or []) + (getattr(cwl_tool, 'hints', None) or []):
        if getattr(requirement, 'class_', None) == 'InlineJavascriptRequirement' or \
                (isinstance(requirement, dict) and requirement.get('class') == 'InlineJavascriptRequirement'):
            lib = getattr(requirement, 'expressionLib', None) if not isinstance(requirement, dict) \
                else requirement.get('expressionLib')
            libraries += [entry for entry in (lib or []) if isinstance(entry, str)]
    return libraries


# ---------------------------------------------------------------------------
# Context tree (Composer ct-tree-view)
# ---------------------------------------------------------------------------
class _ContextDelegate(QStyledItemDelegate):
    """Composer tree entry: the name, then its type in the muted colour, monospace."""

    def __init__(self, font: QFont, parent=None):
        super().__init__(parent)
        self._font = font

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label = opt.text
        type_text = index.data(ROLE_TYPE) or ""
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setFont(self._font)
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        painter.setPen(QColor(theme.WHITE if selected else theme.TEXT))
        painter.drawText(rect, flags, label)
        offset = painter.fontMetrics().horizontalAdvance(label + " ")
        painter.setPen(QColor(theme.TEXT_MUTED))
        painter.drawText(rect.adjusted(offset, 0, 0, 0), flags, type_text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        metrics = QFontMetrics(self._font)
        text = f"{index.data(Qt.ItemDataRole.DisplayRole)} {index.data(ROLE_TYPE) or ''}"
        return QSize(metrics.horizontalAdvance(text) + 8, max(size.height(), metrics.height() + 8))


def _typeDisplay(value: Any) -> str:
    """cwl-ts transformContext: object / array[n] / "value" / null."""
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return f"array[{len(value)}]"
    if isinstance(value, bool):
        return f'"{str(value).lower()}"'
    return f'"{value}"'


def _addNodes(parent, values, path: str = ""):
    keys = range(len(values)) if isinstance(values, list) else list(values.keys())
    for key in keys:
        value = values[key]
        label = str(key)
        if isinstance(values, list):
            node_path = f"{path}[{key}]"
        else:
            node_path = f"{path}.{key}" if path else str(key)
        item = QTreeWidgetItem([label])
        item.setData(0, ROLE_PATH, node_path)
        item.setData(0, ROLE_TYPE, _typeDisplay(value))
        parent.addChild(item) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(item)
        if isinstance(value, (dict, list)):
            _addNodes(item, value, node_path)


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------
class JavaScriptEditorDialog(QDialog):
    """Rabix Composer Expression Editor (modal)."""

    SHADOW = 18
    WIDTH, HEIGHT = 800, 500

    def __init__(self, cwl_dict: Any = None, parent=None):
        if parent is None:
            raise Exception("JavaScriptEditorDialog requires a parent widget")
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.cwl_dict = cwl_dict          # the parameter/step being edited (sets "self")
        self.cwl_tool = None
        self._context_ready = False
        self._evaluations = set()
        self._closed = False
        self._request = 0
        self._overlay = None
        self._drag_offset = None

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setWindowTitle("Expression Editor")
        self.resize(self.WIDTH + 2 * self.SHADOW, self.HEIGHT + 40 + 2 * self.SHADOW)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SHADOW, self.SHADOW, self.SHADOW, self.SHADOW)
        frame = QFrame(self)
        frame.setObjectName('modalFrame')
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 110))
        frame.setGraphicsEffect(shadow)
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header: title and close icon
        self.header = QWidget(frame)
        self.header.setObjectName('modalHeader')
        self.header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header.installEventFilter(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(13, 8, 13, 8)
        title = QLabel("Expression Editor", self.header)
        title_font = QFont(QApplication.font())
        title_font.setPointSizeF(QApplication.font().pointSizeF() + 1)
        title.setFont(title_font)
        header_layout.addWidget(title, 1)
        close_button = QToolButton(self.header)
        close_button.setObjectName('sectionToggle')
        close_button.setIcon(theme.icon('times', color=theme.WHITE, active_color=theme.LIGHT_GRAY))
        close_button.setIconSize(QSize(16, 16))
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.reject)
        header_layout.addWidget(close_button)
        layout.addWidget(self.header)

        # Body: code + preview on the left, context tree on the right
        # the command line preview's font (Courier, 13px), also used by the tree
        self.code_font = theme.cssMonospaceFont()
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        code_column = QVBoxLayout()
        code_column.setSpacing(0)

        self.editor = QsciScintilla(frame)
        self.editor.setUtf8(True)
        lexer = QsciLexerJavaScript(self.editor)
        lexer.setDefaultFont(self.code_font)
        for style in range(128):
            if lexer.description(style):
                lexer.setFont(self.code_font, style)
        self.editor.setLexer(lexer)
        theme.styleCodeEditor(self.editor, lexer)
        self._prepareCodeView(self.editor)
        self.editor.setCaretLineVisible(True)
        self.editor.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
        self.editor.textChanged.connect(self._scheduleEvaluation)
        # Composer: completion of inputs. / self. / runtime. from the context
        self.editor.SendScintilla(QsciScintilla.SCI_AUTOCSETIGNORECASE, 1)
        self.editor.SCN_CHARADDED.connect(self._onCharAdded)
        QShortcut(QKeySequence("Ctrl+Space"), self.editor, activated=lambda: self._complete(explicit=True))
        code_column.addWidget(self.editor, 3)

        preview_frame = QFrame(frame)
        preview_frame.setObjectName('previewFrame')
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 1, 0, 0)
        self.preview = QsciScintilla(preview_frame)
        self.preview.setUtf8(True)
        self.preview.setFont(self.code_font)
        theme.styleCodeEditor(self.preview)
        self._prepareCodeView(self.preview)
        self.preview.setReadOnly(True)
        self.preview.setCaretWidth(0)
        self.preview.setCaretLineVisible(False)
        preview_layout.addWidget(self.preview)
        code_column.addWidget(preview_frame, 1)
        body.addLayout(code_column, 3)

        self.term_tree = QTreeWidget(frame)
        self.term_tree.setObjectName('contextTree')
        self.term_tree.setHeaderHidden(True)
        self.term_tree.setIndentation(13)
        self.term_tree.setExpandsOnDoubleClick(False)
        # long names scroll sideways instead of being cut (Composer: overflow auto)
        self.term_tree.header().setStretchLastSection(False)
        self.term_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.term_tree.setItemDelegate(_ContextDelegate(self.code_font, self.term_tree))
        self.term_tree.itemDoubleClicked.connect(self.insert_term)
        body.addWidget(self.term_tree, 1)
        layout.addLayout(body, 1)

        # Footer: Cancel and Save on the right
        footer = QWidget(frame)
        footer.setObjectName('modalFooter')
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(13, 13, 13, 13)
        footer_layout.setSpacing(13)
        footer_layout.addStretch(1)
        self.cancel_button = QPushButton("Cancel", footer)
        self.cancel_button.setMinimumWidth(80)
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        footer_layout.addWidget(self.cancel_button)
        self.save_button = QPushButton("Save", footer)
        self.save_button.setMinimumWidth(80)
        self.save_button.setAutoDefault(False)
        theme.setButtonRole(self.save_button, 'primary')
        self.save_button.clicked.connect(self.accept)
        footer_layout.addWidget(self.save_button)
        layout.addWidget(footer)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.evaluate)
        self._showResult(PLACEHOLDER_RESULT)

    def _prepareCodeView(self, view: QsciScintilla):
        """Composer's Ace editors: wrapped lines, an empty gutter, no folding."""
        view.setWrapMode(QsciScintilla.WrapMode.WrapWord)
        view.setMarginLineNumbers(0, False)
        view.setMarginWidth(0, 32)
        view.setMarginWidth(1, 0)
        view.setMarginWidth(2, 0)
        view.setFolding(QsciScintilla.FoldStyle.NoFoldStyle)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setFrameShape(QFrame.Shape.NoFrame)

    # -- context ------------------------------------------------------------------
    def _buildContext(self):
        self.cwl_tool = self.get_cwl_tool()
        try:
            self.context = expressionContext(self.cwl_tool, self.cwl_dict,
                                             testJobs().values(documentPath(self)))
        except Exception as e:
            self.logger.debug(f"Could not build the expression context: {e}")
            self.context = {'runtime': dict(SAMPLE_RUNTIME), 'inputs': {}}
        self.libraries = expressionLibraries(self.cwl_tool)
        self.term_tree.clear()
        _addNodes(self.term_tree, self.context)
        self._context_ready = True

    def insert_term(self, item: QTreeWidgetItem, column: int = 0):
        """Insert the path of a context entry at the cursor (Composer: open a tree node)."""
        path = item.data(0, ROLE_PATH)
        if not path or self.editor.isReadOnly():
            return
        line, index = self.editor.getCursorPosition()
        self.editor.insert(path)
        self.editor.setCursorPosition(line, index + len(path))
        self.editor.setFocus()

    # -- completion -----------------------------------------------------------------
    _MEMBER = re.compile(r'([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|\[\d+\])*)\.([\w$]*)$')
    _ROOT = re.compile(r'(?<![\w$.])([A-Za-z_$][\w$]*)$')

    def _onCharAdded(self, char: int):
        if chr(char) == '.' or chr(char).isalnum() or chr(char) in '_$':
            self._complete()

    def completions(self, before: str, explicit: bool = False) -> tuple:
        """(typed part, candidates) for the text before the cursor: the members
        of a context object after a ".", or runtime / inputs / self."""
        if not self._context_ready:
            self._buildContext()
        member = self._MEMBER.search(before)
        if member:
            value = self.context
            for step in re.findall(r'[A-Za-z_$][\w$]*|\[\d+\]', member.group(1)):
                if step.startswith('['):
                    index = int(step[1:-1])
                    value = value[index] if isinstance(value, list) and index < len(value) else None
                else:
                    value = value.get(step) if isinstance(value, dict) else None
            names = list(value.keys()) if isinstance(value, dict) else []
            if isinstance(value, (list, str)):
                names.append('length')
            return member.group(2), names
        root = self._ROOT.search(before)
        typed = root.group(1) if root else ''
        if typed or explicit:
            return typed, [name for name in self.context if name in ('runtime', 'inputs', 'self')]
        return '', []

    def _complete(self, explicit: bool = False):
        line, index = self.editor.getCursorPosition()
        before = self.editor.text(line)[:index]
        typed, names = self.completions(before, explicit)
        names = sorted({name for name in names if name.lower().startswith(typed.lower())}, key=str.lower)
        if not names or (names == [typed] and not explicit):
            return
        self.editor.SendScintilla(QsciScintilla.SCI_AUTOCSHOW, len(typed.encode('utf-8')),
                                  " ".join(names).encode('utf-8'))

    # -- evaluation -----------------------------------------------------------------
    def _scheduleEvaluation(self):
        self.save_button.setEnabled(False)
        self._timer.start()

    def _showResult(self, text: str, status: Optional[str] = None):
        color = {'error': theme.CODE_ERROR, 'warning': theme.CODE_WARNING}.get(status, theme.EDITOR['foreground'])
        self.preview.setColor(QColor(color))
        self.preview.setText(text)

    def evaluate(self):
        code = self.editor.text()
        if not self._context_ready:
            self._buildContext()
        if code == "":
            self._showResult(PLACEHOLDER_RESULT)
            self.save_button.setEnabled(True)
            return
        if self._closed:
            return
        self._request += 1
        self._stopEvaluations()
        evaluation = JSEvaluation(self._request, _EVALUATOR_JS,
                                  evaluationArguments(self.context, self.libraries, code=code), self)
        # bound methods of the dialog: delivered on the GUI thread
        evaluation.evaluated.connect(self._onEvaluated)
        evaluation.finished.connect(self._onEvaluationFinished)
        self._evaluations.add(evaluation)
        evaluation.startWithTimeout(EVALUATION_TIMEOUT_MS)

    def _stopEvaluations(self):
        for evaluation in list(self._evaluations):
            evaluation.interrupt()

    def _onEvaluationFinished(self):
        evaluation = self.sender()
        self._evaluations.discard(evaluation)
        evaluation.deleteLater()

    def _onEvaluated(self, request: int, result: dict):
        if request != self._request:
            return      # a newer evaluation is running
        if 'error' in result:
            self._showResult(result['error'], 'error')
        else:
            self._showResult(result.get('result') or PLACEHOLDER_RESULT)
        self.save_button.setEnabled(True)

    # -- modal behaviour ------------------------------------------------------------
    def exec(self) -> int:
        """Show over a dimmed main window (Composer modal backdrop)."""
        window = self.parentWidget().window() if self.parentWidget() is not None else None
        if window is not None and window.isVisible():
            self._overlay = QWidget(window)
            self._overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._overlay.setStyleSheet("background-color: rgba(0, 0, 0, 64);")
            self._overlay.setGeometry(window.rect())
            self._overlay.show()
            center = window.mapToGlobal(window.rect().center())
            self.move(center - QPoint(self.width() // 2, self.height() // 2))
        if not self._context_ready:
            self._buildContext()
        self.evaluate()
        self.editor.setFocus()
        try:
            return super().exec()
        finally:
            if self._overlay is not None:
                self._overlay.deleteLater()
                self._overlay = None
            # no evaluation may outlive the dialog
            self._closed = True
            self._timer.stop()
            self._stopEvaluations()
            for evaluation in list(self._evaluations):
                evaluation.wait(EVALUATION_TIMEOUT_MS)

    def eventFilter(self, watched, event) -> bool:
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        # drag the modal by its header
        if watched is self.header:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            elif event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
        return super().eventFilter(watched, event)

    # -- results --------------------------------------------------------------------
    def get_javascript_code(self):
        """The expression as written in the editor."""
        return self.editor.text()

    def get_cwl_tool(self):
        """The CWL document of the enclosing ChildWindow (for inputs and expressionLib)."""
        widget = self.parent()
        while widget is not None:
            if widget.__class__.__name__ == "ChildWindow":
                return getattr(widget, 'cwl_tool', None)
            widget = widget.parent()
        return None
