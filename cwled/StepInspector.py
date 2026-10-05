"""
Rabix Composer step inspector.

Double-clicking a step (a tool or a sub-workflow) on the workflow canvas opens
it in an inspector on the right of the canvas (Composer
``ct-workflow-step-inspector``) instead of a dialog window. Like Composer it
has three tabs:

- App Info: the class, CWL version, author, source and description of the app.
- Inputs: the step inputs grouped into Files and App parameters, each with
  its port options (Show/Hide, or Default / Exposed / Port), its default value,
  the link merge method and its connections.
- Step: ID, label, scatter method, scatter, the ``when`` condition (CWL 1.2),
  description and hints.

Every change is applied to the workflow as it is made.
"""
import json
import logging
import os
import re
from collections import namedtuple
from typing import Any, Callable, List, Optional

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QRegularExpression, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                             QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget)

import theme
from cwl_utils_handler import get_cwl_module

logger = logging.getLogger("StepInspector")

SBG_NAMESPACE = "https://sevenbridges.com"
# types without default values, whose ports Composer shows when they are required
FILE_KINDS = ('File', 'Directory', 'stdin')

PORT_OPTIONS = [
    ('default', "Default", "Set default value for execution"),
    ('exposed', "Exposed", "Set value with the option to edit on the test page"),
    ('port', "Port", "Get value from another node on the canvas"),
]
LINK_MERGE = [(None, "-- none --"), ('merge_nested', "Nested"), ('merge_flattened', "Flattened")]
PICK_VALUE = [(None, "-- none --"), ('first_non_null', "first_non_null"),
              ('the_only_non_null', "the_only_non_null"), ('all_non_null', "all_non_null")]
SCATTER_METHODS = [(None, "-- none --"), ('dotproduct', "Dot Product"),
                   ('nested_crossproduct', "Nested Cross Product"),
                   ('flat_crossproduct', "Flat Cross Product")]
# cwl-ts validateID
ID_CHARACTERS = re.compile(r"[^a-zA-Z0-9_;?\-:@&=+$,.!~*'()\[\]]")
HINTS_HELP = ("Set execution hints and their values, which specify the requirements and "
              "preferences for execution. For instance, use hints to specify the type of AWS "
              "instance to execute your task.")


# ---------------------------------------------------------------------------
# CWL helpers
# ---------------------------------------------------------------------------
PortType = namedtuple('PortType', 'kind items symbols fields nullable')


def shortId(value: Any) -> str:
    return str(value).split('#')[-1].split('/')[-1]


def portType(cwl_type: Any) -> PortType:
    """The type of a parameter like cwl-ts ParameterTypeModel: its kind
    ("File", "array", "enum", "record", ...), the kind of its items, the
    enum symbols, the record fields and whether it is optional."""
    nullable = False
    if isinstance(cwl_type, list):
        nullable = 'null' in cwl_type
        types = [t for t in cwl_type if t != 'null']
        cwl_type = types[0] if types else 'null'
    if isinstance(cwl_type, str):
        name = shortId(cwl_type)
        if name.endswith('?'):
            nullable, name = True, name[:-1]
        if name.endswith('[]'):
            return PortType('array', name[:-2], None, None, nullable)
        return PortType(name, None, None, None, nullable)
    kind = getattr(cwl_type, 'type_', None)
    if kind == 'array':
        item = portType(getattr(cwl_type, 'items', None))
        return PortType('array', item.kind, item.symbols, item.fields, nullable)
    if kind == 'enum':
        symbols = [shortId(s) for s in (getattr(cwl_type, 'symbols', None) or [])]
        return PortType('enum', None, symbols, None, nullable)
    if kind == 'record':
        return PortType('record', None, None, getattr(cwl_type, 'fields', None) or [], nullable)
    return PortType(None, None, None, None, nullable)


def itemType(cwl_type: Any) -> Any:
    """The (raw) type of the items of an array type."""
    if isinstance(cwl_type, list):
        types = [t for t in cwl_type if t != 'null']
        cwl_type = types[0] if types else None
    if isinstance(cwl_type, str):
        name = shortId(cwl_type).rstrip('?')
        return name[:-2] if name.endswith('[]') else None
    return getattr(cwl_type, 'items', None)


def isFileType(port_type: PortType) -> bool:
    return port_type.kind == 'File' or port_type.items == 'File'


def _isNamespaced(key: str, name: str) -> bool:
    """``sbg:<name>``, as written or expanded with the sevenbridges namespace."""
    return key == f"sbg:{name}" or bool(re.fullmatch(r"https?://sevenbridges\.com/?" + re.escape(name), key))


def sbgValue(cwl_object: Any, name: str) -> Any:
    for key, value in (getattr(cwl_object, 'extension_fields', None) or {}).items():
        if _isNamespaced(key, name):
            return value
    return None


def isExposed(parameter: Any) -> bool:
    """A workflow input Composer exposed from a step (``sbg:exposed``)."""
    return sbgValue(parameter, 'exposed') in (True, 'true')


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value)


def _sources(step_input: Any) -> List[str]:
    source = getattr(step_input, 'source', None) if step_input is not None else None
    if not source:
        return []
    return list(source) if isinstance(source, list) else [source]


def _sourceName(source: str) -> str:
    """``step/output`` or ``input`` as written in the document."""
    return str(source).split('#')[-1]


def _mockEntry(cwl_type: Any, name: str) -> Any:
    """A new array entry (Composer: the first value of a generated mock job)."""
    from JavascriptEditor import mockValue
    value = mockValue(cwl_type, name)
    if isinstance(value, list):
        return json.loads(json.dumps(value[0], default=str)) if value else None
    return value


# ---------------------------------------------------------------------------
# Small Composer controls
# ---------------------------------------------------------------------------
def _muted(label: QLabel) -> QLabel:
    label.setProperty('muted', True)
    return label


class ToggleSlider(QWidget):
    """Composer ct-toggle-slider: the state ("Yes"/"No") and the switch."""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, on: str = "Yes", off: str = "No",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._on, self._off = on, off
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.state = QLabel(self)
        self.state.setCursor(Qt.CursorShape.PointingHandCursor)
        self.state.installEventFilter(self)
        self.checkbox = QCheckBox(self)
        self.checkbox.setProperty('toggle', True)
        self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkbox.setChecked(bool(checked))
        layout.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        self._update()
        self.checkbox.toggled.connect(self._onToggled)

    def isChecked(self) -> bool:
        return self.checkbox.isChecked()

    def _update(self):
        self.state.setText(self._on if self.checkbox.isChecked() else self._off)

    def _onToggled(self, checked: bool):
        self._update()
        self.toggled.emit(checked)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not sip.isdeleted(self) and watched is self.state \
                and event.type() == QEvent.Type.MouseButtonRelease and self.checkbox.isEnabled():
            self.checkbox.toggle()
        return super().eventFilter(watched, event)


class PortOptionsMenu(QFrame):
    """Composer ct-generic-dropdown-menu of the port options."""

    chosen = pyqtSignal(str)

    def __init__(self, status: str, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName('portOptionsMenu')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.options = {}
        for value, caption, description in PORT_OPTIONS:
            row = QFrame(self)
            row.setObjectName('portOption')
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            row.setProperty('active', value == status)
            row.setProperty('option', value)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setFixedWidth(215)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(13, 7, 13, 7)
            row_layout.setSpacing(2)
            row_layout.addWidget(QLabel(caption, row))
            text = _muted(QLabel(description, row))
            text.setProperty('small', True)
            text.setWordWrap(True)
            row_layout.addWidget(text)
            row.installEventFilter(self)
            layout.addWidget(row)
            self.options[value] = row

    def choose(self, value: str):
        self.close()
        self.chosen.emit(value)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not sip.isdeleted(self) and event.type() == QEvent.Type.MouseButtonRelease \
                and watched.property('option'):
            self.choose(watched.property('option'))
            return True
        return super().eventFilter(watched, event)


class PortOptionsButton(QPushButton):
    """The port status with a chevron, opening the port options menu."""

    optionChosen = pyqtSignal(str)

    def __init__(self, status: str, parent: Optional[QWidget] = None):
        super().__init__(status, parent)
        self.status = status
        self.menu_popup = None
        self.setObjectName('portOptionsButton')
        self.setIcon(theme.icon('chevron-down', color=theme.TEXT, active_color=theme.TEXT))
        self.setIconSize(QSize(10, 10))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)     # chevron after the text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.showMenu)

    def showMenu(self):
        menu = PortOptionsMenu(self.status, self)
        menu.chosen.connect(self.optionChosen.emit)
        menu.adjustSize()
        # Composer aligns the menu's right side with the button's
        corner = self.mapToGlobal(QPoint(self.width(), self.height()))
        menu.move(corner.x() - menu.width(), corner.y() + 2)
        menu.show()
        self.menu_popup = menu
        return menu


def _combo(options, value, parent) -> QComboBox:
    combo = QComboBox(parent)
    for data, caption in options:
        combo.addItem(caption, data)
    index = combo.findData(value)
    if index < 0 and value is not None:
        combo.addItem(str(value), value)        # keep values the list does not know
        index = combo.count() - 1
    combo.setCurrentIndex(max(index, 0))
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    return combo


def _infoIcon(tooltip: str, parent: QWidget) -> QLabel:
    info = QLabel(parent)
    info.setPixmap(theme.icon('info-circle', color=theme.TEXT_MUTED).pixmap(QSize(13, 13)))
    info.setToolTip(tooltip)
    return info


def _escape(text: str) -> str:
    return (str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('\n', '<br>'))


# ---------------------------------------------------------------------------
# Default values (Composer ct-workflow-step-inspector-entry)
# ---------------------------------------------------------------------------
class ValueEntry(QWidget):
    """
    The editor of a step input's value for its type: a drop-down for enums,
    number and text fields, a Yes/No switch for booleans, nested entries for
    records and a list of entries for arrays.

    ``changed(immediate)``: the value was edited; ``immediate`` is False while
    the user is typing.
    """

    changed = pyqtSignal(bool)

    def __init__(self, cwl_type: Any, value: Any, name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cwl_type = cwl_type
        self.port_type = portType(cwl_type)
        self.name = name
        self.original = value
        self.kind = self.port_type.kind
        if self.kind == 'array' and self.port_type.items == 'File':
            self.kind = 'File'
        self._touched = False
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        build = {
            'enum': self._buildEnum, 'int': self._buildNumber, 'long': self._buildNumber,
            'float': self._buildNumber, 'double': self._buildNumber, 'string': self._buildString,
            'boolean': self._buildBoolean, 'File': self._buildFile, 'stdin': self._buildFile,
            'Directory': self._buildDirectory, 'record': self._buildRecord, 'array': self._buildArray,
            'Any': self._buildAny,
        }.get(self.kind, self._buildUnknown)
        build()

    # -- builders ----------------------------------------------------------------
    def _buildEnum(self):
        symbols = self.port_type.symbols or []
        self.combo = _combo([(None, "-- none --")] + [(s, s) for s in symbols], self.original, self)
        self.combo.currentIndexChanged.connect(lambda *_: self._edited(True))
        self.layout_.addWidget(self.combo)

    def _buildNumber(self):
        self.edit = QLineEdit(self)
        pattern = r"-?\d*" if self.kind in ('int', 'long') else r"-?\d*\.?\d*([eE][-+]?\d*)?"
        self.edit.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), self.edit))
        if self.original is not None:
            self.edit.setText(str(self.original))
        self.edit.textEdited.connect(lambda *_: self._edited(False))
        self.edit.editingFinished.connect(lambda: self._touched and self.changed.emit(True))
        self.layout_.addWidget(self.edit)

    def _buildString(self):
        self.edit = QLineEdit(self)
        if self.original is not None:
            self.edit.setText(self.original if isinstance(self.original, str)
                              else json.dumps(self.original, default=str))
        self.edit.textEdited.connect(lambda *_: self._edited(False))
        self.edit.editingFinished.connect(lambda: self._touched and self.changed.emit(True))
        self.layout_.addWidget(self.edit)

    _buildAny = _buildString

    def _buildBoolean(self):
        self.toggle = ToggleSlider(bool(self.original), parent=self)
        self.toggle.toggled.connect(lambda *_: self._edited(True))
        self.layout_.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)

    def _edited(self, immediate: bool):
        """The user changed the value (entries never touched keep their value)."""
        self._touched = True
        self.changed.emit(immediate)

    def _message(self, text: str, warning: bool):
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setProperty('small', True)
        label.setProperty('warningText' if warning else 'muted', True)
        self.layout_.addWidget(label)

    def _buildFile(self):
        self._message("Cannot set default values for type File and File[].", warning=True)

    def _buildDirectory(self):
        self._message("Cannot set default values for type Directory and Directory[].", warning=False)

    def _buildUnknown(self):
        self.layout_.addWidget(QLabel(f"Unknown input type: {self.kind or 'null'}", self))

    def _buildRecord(self):
        self.fields = {}
        values = self.original if isinstance(self.original, dict) else {}
        for field in self.port_type.fields or []:
            name = shortId(getattr(field, 'name', ''))
            box = QWidget(self)
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(13, 0, 0, 0)       # Composer .ml-1
            box_layout.setSpacing(6)
            title = QHBoxLayout()
            title.setSpacing(5)
            field_type = portType(getattr(field, 'type_', None))
            label = QLabel(f"{_escape(getattr(field, 'label', None) or name)} "
                           f"<span style='color:{theme.TEXT_MUTED}'>({field_type.kind})</span>", box)
            title.addWidget(label)
            if getattr(field, 'doc', None):
                title.addWidget(_infoIcon(_text(field.doc), box))
            title.addStretch(1)
            box_layout.addLayout(title)
            entry = ValueEntry(getattr(field, 'type_', None), values.get(name), name, box)
            entry.changed.connect(self._edited)
            box_layout.addWidget(entry)
            self.layout_.addWidget(box)
            self.fields[name] = entry

    def _buildArray(self):
        if self.original is not None and not isinstance(self.original, list):
            self._message(f"Type mismatch: the default step value for this input is of type "
                          f"“{type(self.original).__name__}”, but the input is declared as "
                          f"“array”. You can generate a new set of test data for this input by "
                          f"clicking on the “New {self.port_type.items}” button.", warning=True)
        self.items = list(self.original) if isinstance(self.original, list) else []
        self.entries = []
        self.rows = QVBoxLayout()
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(6)
        self.layout_.addLayout(self.rows)
        self.add_button = QPushButton(f"New {self.port_type.items}", self)
        self.add_button.setIcon(theme.icon('plus', color=theme.SKY))
        self.add_button.setIconSize(QSize(12, 12))
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.setButtonRole(self.add_button, 'link')
        self.add_button.clicked.connect(self._addItem)
        self.layout_.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._buildRows()

    def _buildRows(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.entries = []
        for index, value in enumerate(self.items):
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            entry = ValueEntry(itemType(self.cwl_type), value, self.name, row)
            entry.changed.connect(self._edited)
            row_layout.addWidget(entry, 1)
            remove = QPushButton(row)
            remove.setIcon(theme.icon('trash', color=theme.TEXT_MUTED, active_color=theme.TEXT))
            remove.setIconSize(QSize(14, 14))
            remove.setToolTip("Delete")
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            theme.setButtonRole(remove, 'plainIcon')
            remove.clicked.connect(lambda _=False, i=index: self._removeItem(i))
            row_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
            self.rows.addWidget(row)
            self.entries.append(entry)

    def _currentItems(self) -> list:
        return [entry.value() for entry in self.entries]

    def _addItem(self):
        self.items = self._currentItems() + [_mockEntry(self.cwl_type, self.name)]
        self._buildRows()
        self._edited(True)

    def _removeItem(self, index: int):
        items = self._currentItems()
        del items[index]
        self.items = items
        self._buildRows()
        self._edited(True)

    # -- value ---------------------------------------------------------------------
    def value(self) -> Any:
        if not self._touched:
            return self.original
        kind = self.kind
        if kind == 'enum':
            return self.combo.currentData()
        if kind in ('int', 'long', 'float', 'double'):
            text = self.edit.text().strip()
            try:
                if kind in ('int', 'long') or re.fullmatch(r"-?\d+", text):
                    return int(text)
                return float(text)
            except ValueError:
                return None
        if kind == 'string':
            return self.edit.text() or None
        if kind == 'Any':
            text = self.edit.text()
            if not text:
                return None
            try:
                return json.loads(text)
            except ValueError:
                return text
        if kind == 'boolean':
            return self.toggle.isChecked()
        if kind == 'record':
            value = dict(self.original) if isinstance(self.original, dict) else {}
            for name, entry in self.fields.items():
                field_value = entry.value()
                if field_value is None:
                    value.pop(name, None)
                else:
                    value[name] = field_value
            return value or None
        if kind == 'array':
            return self._currentItems()
        # File, Directory and unknown types keep their value
        return self.original


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
class _Page(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName('inspectorBody')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.main = QVBoxLayout(self)
        self.main.setContentsMargins(13, 13, 13, 13)
        self.main.setSpacing(13)


class AppInfoTab(_Page):
    """Composer ct-workflow-step-inspector-info."""

    def __init__(self, node, workflow_file: Optional[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        tool = node.getCWLTool()
        step = node.getCWL()
        toolkit = " ".join(_text(v) for v in (sbgValue(tool, 'toolkit'), sbgValue(tool, 'toolkitVersion'))
                           if v is not None)
        rows = [
            ("Type", getattr(tool, 'class_', None)),
            ("Cwl Version", getattr(tool, 'cwlVersion', None) or getattr(node, 'cwl_version', None)),
            ("Revision", sbgValue(tool, 'revision')),
            ("Toolkit", toolkit),
            ("Author", sbgValue(tool, 'createdBy')),
            ("Source", self._source(step, workflow_file)),
        ]
        for title, value in rows:
            line = QLabel(f"<span style='color:{theme.LIGHT_GRAY}'>{title}:</span> "
                          f"{_escape(_text(value))}", self)
            line.setWordWrap(True)
            line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.main.addWidget(line)
        description = _text(getattr(tool, 'doc', None))
        title = QLabel(f"Description{'' if description else ':'}", self)
        title.setStyleSheet(f"color: {theme.LIGHT_GRAY};")
        self.main.addWidget(title)
        if description:
            text = QLabel(self)
            text.setTextFormat(Qt.TextFormat.MarkdownText)
            text.setText(description)
            text.setWordWrap(True)
            text.setOpenExternalLinks(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            self.main.addWidget(text)
        self.main.addStretch(1)

    @staticmethod
    def _source(step, workflow_file: Optional[str]) -> str:
        run = getattr(step, 'run', None)
        if not isinstance(run, str):
            return "Embedded"
        path = run[len('file://'):] if run.startswith('file://') else run
        if workflow_file and os.path.isabs(path):
            try:
                return os.path.relpath(path, os.path.dirname(str(workflow_file)))
            except ValueError:
                return path
        return path


class InputBox(QFrame):
    """One step input (Composer ``.input-box``)."""

    def __init__(self, inspector: 'StepInspector', node, port_name: str, parameter: Any,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName('stepInputBox')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.inspector = inspector
        self.port_name = port_name
        self.parameter = parameter
        step_input = inspector.stepInput(port_name)
        port_type = portType(getattr(parameter, 'type_', None)) if parameter is not None \
            else PortType(None, None, None, None, True)
        status = inspector.graph.portStatus(node, port_name)
        port = node.inputs().get(port_name)
        visible = port.visible() if port is not None else True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 13, 0, 13)
        layout.setSpacing(8)

        # label, type and port options
        title = QHBoxLayout()
        title.setSpacing(5)
        label_text = getattr(parameter, 'label', None) or port_name
        if parameter is not None and not port_type.nullable:
            star = QLabel("*", self)
            star.setProperty('dangerText', True)
            title.addWidget(star)
        tooltip = self._tooltip(parameter, label_text)
        if tooltip:
            title.addWidget(_infoIcon(tooltip, self))
        type_text = f" <span style='color:{theme.TEXT_MUTED}'>({port_type.kind})</span>" \
            if port_type.kind else ""
        self.name_label = QLabel(f"{_escape(label_text)}{type_text}", self)
        self.name_label.setToolTip(label_text)
        self.name_label.setMinimumWidth(1)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.addWidget(self.name_label, 1)
        self.toggle = None
        self.options_button = None
        if parameter is not None:
            if port_type.kind in FILE_KINDS or port_type.items in FILE_KINDS:
                if port_type.nullable:
                    self.toggle = ToggleSlider(status == 'port', on="Show", off="Hide", parent=self)
                    self.toggle.toggled.connect(
                        lambda checked: inspector.setPortOption(port_name, 'port' if checked else 'default'))
                    title.addWidget(self.toggle)
            else:
                self.options_button = PortOptionsButton(status, self)
                self.options_button.optionChosen.connect(
                    lambda option: inspector.setPortOption(port_name, option))
                title.addWidget(self.options_button)
        layout.addLayout(title)

        # value
        self.entry = None
        if parameter is not None and not isFileType(port_type):
            self.entry = ValueEntry(getattr(parameter, 'type_', None),
                                    getattr(step_input, 'default', None), port_name, self)
            self.entry.changed.connect(self._onValueChanged)
            layout.addWidget(self.entry)

        # link merge method (and pick value, CWL 1.2)
        layout.addWidget(_muted(QLabel("Link Merge Method", self)))
        self.link_merge = _combo(LINK_MERGE, getattr(step_input, 'linkMerge', None), self)
        self.link_merge.currentIndexChanged.connect(
            lambda *_: inspector.setStepInputField(port_name, 'linkMerge', self.link_merge.currentData()))
        layout.addWidget(self.link_merge)
        self.pick_value = None
        self.source_order = None
        # CWL 1.2 pickValue, for inputs with several sources (Composer has no such option)
        if inspector.supportsPickValue() and (len(_sources(step_input)) > 1 or
                                              getattr(step_input, 'pickValue', None)):
            layout.addWidget(_muted(QLabel("Pick Value", self)))
            self.pick_value = _combo(PICK_VALUE, getattr(step_input, 'pickValue', None), self)
            self.pick_value.currentIndexChanged.connect(
                lambda *_: inspector.setStepInputField(port_name, 'pickValue', self.pick_value.currentData()))
            layout.addWidget(self.pick_value)
            sources = _sources(step_input)
            if getattr(step_input, 'pickValue', None) and len(sources) > 1:
                from widgets.qSortedList import QSortList
                self.source_order = QSortList(parent=self, cwl_tool=sources,
                                              cwl_version=inspector.cwlVersion())
                self.source_order.editingFinished.connect(
                    lambda: inspector.setStepInputField(port_name, 'source', self.source_order.getData()))
                layout.addWidget(self.source_order)

        # connections
        sources = _sources(step_input)
        if sources:
            connections = QLabel("Connections: " + ", ".join(_sourceName(s) for s in sources), self)
            connections.setWordWrap(True)
            layout.addWidget(_muted(connections))
        elif visible:
            required = parameter is not None and not port_type.nullable
            row = QHBoxLayout()
            row.setSpacing(5)
            color = theme.RED if required else theme.ORANGE
            glyph = QLabel(self)
            glyph.setPixmap(theme.icon('times-circle' if required else 'warning', color=color)
                            .pixmap(QSize(13, 13)))
            row.addWidget(glyph)
            text = QLabel("This required port is not connected" if required
                          else "This port is not connected", self)
            text.setProperty('dangerText' if required else 'warningText', True)
            row.addWidget(text, 1)
            layout.addLayout(row)

    @staticmethod
    def _tooltip(parameter: Any, title: str) -> str:
        """Composer's input metadata tooltip."""
        if parameter is None:
            return ""
        parts = []
        if getattr(parameter, 'doc', None):
            parts.append(_escape(_text(parameter.doc)))
        default = sbgValue(parameter, 'toolDefaultValue')
        if default is not None:
            parts.append(f"<b>Suggested Value:</b> {_escape(_text(default))}")
        file_types = sbgValue(parameter, 'fileTypes') or getattr(parameter, 'format', None)
        if file_types:
            parts.append(f"<b>Suggested File Types:</b> {_escape(', '.join(_text(file_types).splitlines()))}")
        alt_prefix = sbgValue(parameter, 'altPrefix')
        if alt_prefix:
            parts.append(f"<b>Alternative Command Line Prefix:</b> {_escape(_text(alt_prefix))}")
        if not parts:
            return ""
        return f"<h4>{_escape(title)}</h4>" + "".join(f"<p>{p}</p>" for p in parts)

    def _onValueChanged(self, immediate: bool):
        port_name = self.port_name
        self.inspector.schedule(('default', port_name),
                                lambda: self.inspector.setStepInputField(port_name, 'default',
                                                                         self.entry.value()),
                                immediate)


class StepInputsTab(_Page):
    """Composer ct-step-inputs-inspector: the inputs grouped into Files and
    App parameters (and the step's own inputs, used by ``when``)."""

    def __init__(self, inspector: 'StepInspector', node, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.main.setContentsMargins(13, 0, 13, 13)
        self.main.setSpacing(0)
        tool = node.getCWLTool()
        groups = {}
        tool_ports = set()
        for parameter in (getattr(tool, 'inputs', None) or []):
            port_name = shortId(parameter.id)
            tool_ports.add(port_name)
            group = "Files" if isFileType(portType(getattr(parameter, 'type_', None))) else "App parameters"
            groups.setdefault(group, []).append((port_name, parameter))
        for step_input in (getattr(node.getCWL(), 'in_', None) or []):
            port_name = shortId(step_input.id)
            if port_name not in tool_ports:
                groups.setdefault("Conditional inputs", []).append((port_name, None))
        self.boxes = {}
        for name in ("Files", "App parameters", "Conditional inputs"):
            if name not in groups:
                continue
            container = QWidget(self)
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            for port_name, parameter in groups[name]:
                box = InputBox(inspector, node, port_name, parameter, container)
                container_layout.addWidget(box)
                self.boxes[port_name] = box
            section = theme.FormSection(container, title=name, borderless=True, parent=self)
            section.setContentsMargins(0, 13, 0, 0)
            self.main.addWidget(section)
        if not groups:
            empty = _muted(QLabel("This app has no inputs.", self))
            empty.setContentsMargins(0, 13, 0, 0)
            self.main.addWidget(empty)
        self.main.addStretch(1)


class StepTab(_Page):
    """Composer ct-workflow-step-inspector-step."""

    ID_DELAY_MS = 1000
    LABEL_DELAY_MS = 1000

    def __init__(self, inspector: 'StepInspector', node, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.inspector = inspector
        step = node.getCWL()

        # ID
        self.id_input = QLineEdit(shortId(step.id), self)
        self.id_input.textEdited.connect(
            lambda *_: inspector.schedule('id', self._applyId, delay=self.ID_DELAY_MS))
        self.id_input.editingFinished.connect(lambda: inspector.schedule('id', self._applyId, True))
        id_group = theme.FieldGroup("ID", self.id_input, parent=self)
        self.id_error = QLabel(self)
        self.id_error.setProperty('dangerText', True)
        self.id_error.setWordWrap(True)
        self.id_error.hide()
        id_group.layout().addWidget(self.id_error)
        self.main.addWidget(id_group)

        # Label
        self.label_input = QLineEdit(step.label or "", self)
        self.label_input.textEdited.connect(
            lambda *_: inspector.schedule('label', self._applyLabel, delay=self.LABEL_DELAY_MS))
        self.label_input.editingFinished.connect(lambda: inspector.schedule('label', self._applyLabel, True))
        self.main.addWidget(theme.FieldGroup("Label", self.label_input, parent=self))

        # Scatter Method
        self.scatter_method = _combo(SCATTER_METHODS, getattr(step, 'scatterMethod', None), self)
        self.scatter_method.currentIndexChanged.connect(
            lambda *_: inspector.setStepField('scatterMethod', self.scatter_method.currentData()))
        self.main.addWidget(theme.FieldGroup("Scatter Method", self.scatter_method, parent=self))

        # Scatter (several inputs since CWL v1.0)
        self.scatter = QListWidget(self)
        self.scatter.setObjectName('scatterList')
        self.scatter.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        scattered = {shortId(s) for s in (step.scatter if isinstance(step.scatter, list)
                                         else [step.scatter] if step.scatter else [])}
        for port_name in inspector.stepInputNames():
            item = QListWidgetItem(port_name, self.scatter)
            item.setSelected(port_name in scattered)
        rows = min(max(self.scatter.count(), 1), 6)
        self.scatter.setFixedHeight(rows * (self.scatter.fontMetrics().height() + 8) + 6)
        self.scatter.itemSelectionChanged.connect(self._applyScatter)
        self.main.addWidget(theme.FieldGroup("Scatter", self.scatter, parent=self))

        # When (CWL v1.2 conditional execution)
        self.when_input = None
        if hasattr(step, 'when'):
            self.when_input = QLineEdit(step.when or "", self)
            self.when_input.textChanged.connect(lambda *_: inspector.schedule('when', self._applyWhen))
            self.main.addWidget(theme.FieldGroup("When", self.when_input, parent=self,
                                                 open_editor=self._editWhen))

        # Description
        self.description = QPlainTextEdit(_text(step.doc), self)
        self.description.setFixedHeight(self.description.fontMetrics().lineSpacing() * 4 + 14)
        self.description.textChanged.connect(lambda: inspector.schedule('doc', self._applyDescription))
        self.main.addWidget(theme.FieldGroup("Description", self.description, parent=self))

        # Hints
        hints = QPushButton("Set Hints", self)
        hints.setCursor(Qt.CursorShape.PointingHandCursor)
        hints.clicked.connect(inspector.editHints)
        self.main.addWidget(hints, 0, Qt.AlignmentFlag.AlignLeft)
        self.main.addStretch(1)

    def _applyId(self):
        error = self.inspector.renameStep(self.id_input.text())
        self.id_input.setProperty('invalid', bool(error))
        self.id_input.style().unpolish(self.id_input)
        self.id_input.style().polish(self.id_input)
        self.id_error.setText(error or "")
        self.id_error.setVisible(bool(error))

    def _applyLabel(self):
        self.inspector.setStepField('label', self.label_input.text() or None)

    def _applyScatter(self):
        selected = [item.text() for item in self.scatter.selectedItems()]
        self.inspector.setScatter(selected)

    def _applyWhen(self):
        self.inspector.setStepField('when', self.when_input.text() or None)

    def _editWhen(self):
        self.inspector.editExpression(self.when_input)

    def _applyDescription(self):
        self.inspector.setStepField('doc', self.description.toPlainText() or None)


# ---------------------------------------------------------------------------
# Hints (Composer ct-hints-modal)
# ---------------------------------------------------------------------------
class HintsDialog(QDialog):
    """Composer "Set Hints": the step's hints as class / value rows."""

    def __init__(self, hints: list, apply: Callable[[list], None], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Set Hints")
        self.setMinimumWidth(560)
        self._apply = apply
        self.hints = [dict(h) if isinstance(h, dict) else h for h in (hints or [])]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(10)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        layout.addLayout(self.body)
        layout.addStretch(1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        self._build()

    def _clear(self):
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
            elif item.layout() is not None:
                while item.layout().count():
                    child = item.layout().takeAt(0).widget()
                    if child is not None:
                        child.hide()
                        child.deleteLater()

    def _build(self):
        self._clear()
        if not self.hints:
            add = QPushButton("Add a Hint", self)
            theme.setButtonRole(add, 'primary')
            add.clicked.connect(self._add)
            self.body.addWidget(add, 0, Qt.AlignmentFlag.AlignHCenter)
            text = QLabel(HINTS_HELP, self)
            text.setWordWrap(True)
            text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.body.addWidget(text)
            return
        self.body.addWidget(theme.ListHeader([("Class", 1), ("Value", 1)], self))
        for index, hint in enumerate(self.hints):
            row = QHBoxLayout()
            row.setSpacing(6)
            hint_class = QLineEdit(str(hint.get('class', '')) if isinstance(hint, dict) else "", self)
            hint_class.setFont(theme.cssMonospaceFont())
            row.addWidget(hint_class, 1)
            editable = isinstance(hint, dict) and set(hint) <= {'class', 'value'} and \
                not isinstance(hint.get('value'), (dict, list))
            if editable:
                value = QLineEdit(_text(hint.get('value')), self)
                value.textChanged.connect(lambda text, i=index: self._set(i, 'value', text))
            else:
                rest = {k: v for k, v in hint.items() if k != 'class'} if isinstance(hint, dict) else hint
                value = QLineEdit(json.dumps(rest, default=str), self)
                value.setReadOnly(True)
            row.addWidget(value, 1)
            hint_class.textChanged.connect(lambda text, i=index: self._set(i, 'class', text))
            remove = QPushButton(self)
            remove.setIcon(theme.icon('trash', color=theme.TEXT_MUTED, active_color=theme.TEXT))
            remove.setIconSize(QSize(14, 14))
            remove.setToolTip("Delete")
            theme.setButtonRole(remove, 'plainIcon')
            remove.clicked.connect(lambda _=False, i=index: self._remove(i))
            row.addWidget(remove)
            self.body.addLayout(row)
        add = QPushButton("Add a Hint", self)
        add.setIcon(theme.icon('plus', color=theme.SKY))
        add.setIconSize(QSize(12, 12))
        theme.setButtonRole(add, 'link')
        add.clicked.connect(self._add)
        self.body.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

    def _set(self, index: int, key: str, text: str):
        if isinstance(self.hints[index], dict):
            self.hints[index][key] = text
            self._apply(self.hints)

    def _add(self):
        self.hints.append({'class': '', 'value': ''})
        self._apply(self.hints)
        self._build()

    def _remove(self, index: int):
        del self.hints[index]
        self._apply(self.hints)
        self._build()


# ---------------------------------------------------------------------------
# The inspector
# ---------------------------------------------------------------------------
class StepInspector(QFrame):
    """
    Composer ``ct-editor-inspector`` showing a workflow step: the step's name,
    a close button, and the App Info / Inputs / Step tabs.
    """
    DEFAULT_WIDTH = 340
    APPLY_DELAY_MS = 400
    TABS = ("App Info", "Inputs", "Step")

    def __init__(self, graph, parent: Optional[QWidget] = None):
        """``graph``: the CWLGraph of the workflow editor."""
        super().__init__(parent)
        self.setObjectName('inspector')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(280)
        self.graph = graph
        self._node_name = None
        self._applying = False
        self._pending = {}              # key -> callable, applied by the timer
        self._refresh_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        header.setObjectName('inspectorHeader')
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(13, 13, 13, 13)
        self.title = theme.styleTitle(QLabel(header))
        self.title.setMinimumWidth(1)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self.title, 1)
        close_button = QToolButton(header)
        close_button.setObjectName('sectionToggle')
        close_button.setIcon(theme.icon('times', color=theme.TEXT, active_color=theme.LIGHT_GRAY))
        close_button.setIconSize(QSize(16, 16))
        close_button.setToolTip("Close")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.close_inspector)
        header_layout.addWidget(close_button)
        layout.addWidget(header)

        # Composer ct-tab-selector, the tabs share the width equally
        self.tabs = QTabBar(self)
        self.tabs.setObjectName('stepInspectorTabs')
        self.tabs.setExpanding(True)
        self.tabs.setDrawBase(False)
        self.tabs.setDocumentMode(True)
        for name in self.TABS:
            self.tabs.addTab(name)
        self.tabs.setCurrentIndex(self.TABS.index("Inputs"))
        layout.addWidget(self.tabs)

        self.pages = QStackedWidget(self)
        self.scrolls = []
        for _ in self.TABS:
            scroll = QScrollArea(self.pages)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.pages.addWidget(scroll)
            self.scrolls.append(scroll)
        self.pages.setCurrentIndex(self.tabs.currentIndex())
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        layout.addWidget(self.pages, 1)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(self.APPLY_DELAY_MS)
        self._apply_timer.timeout.connect(self.applyPending)

        graph.editingFinished.connect(self._onGraphEdited)
        graph.graph.nodes_deleted.connect(self._onNodesDeleted)
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(self.DEFAULT_WIDTH, 400)

    # -- the inspected step ------------------------------------------------------------
    def node(self):
        if self._node_name is None or sip.isdeleted(self.graph):
            return None
        for node in self.graph.graph.get_nodes_by_type('cwled.step.StepNode'):
            if node.name() == self._node_name:
                return node
        return None

    def step(self):
        node = self.node()
        return node.getCWL() if node is not None else None

    def cwlVersion(self) -> str:
        node = self.node()
        return getattr(node, 'cwl_version', None) or self.graph.cwl_version

    def supportsPickValue(self) -> bool:
        return self.cwlVersion() not in (None, 'v1.0', 'v1.1')

    def stepInputNames(self) -> List[str]:
        """The tool's inputs then the step's own inputs."""
        node = self.node()
        names = [shortId(p.id) for p in (getattr(node.getCWLTool(), 'inputs', None) or [])]
        for step_input in (getattr(node.getCWL(), 'in_', None) or []):
            if shortId(step_input.id) not in names:
                names.append(shortId(step_input.id))
        return names

    def stepInput(self, port_name: str, create: bool = False):
        step = self.step()
        for step_input in (step.in_ or []):
            if shortId(step_input.id) == port_name:
                return step_input
        if not create:
            return None
        module = get_cwl_module(self.cwlVersion())
        step_input = module.WorkflowStepInput(id=port_name)
        step.in_.append(step_input)
        return step_input

    # -- showing ---------------------------------------------------------------------
    def inspect(self, node):
        """Show ``node`` (a StepNode) in the inspector."""
        self.applyPending()
        self._node_name = node.name()
        self.rebuild()
        self.show()

    def isInspecting(self, node) -> bool:
        return self.isVisible() and node is not None and node.name() == self._node_name

    def rebuild(self, tabs=None):
        """(Re)build the tabs (all of them by default) from the step."""
        node = self.node()
        if node is None:
            self.close_inspector()
            return
        self._updateTitle(node)
        builders = {
            "App Info": lambda: AppInfoTab(node, self.graph.workflow_file),
            "Inputs": lambda: StepInputsTab(self, node),
            "Step": lambda: StepTab(self, node),
        }
        for index, name in enumerate(self.TABS):
            if tabs is not None and name not in tabs:
                continue
            scroll = self.scrolls[index]
            position = scroll.verticalScrollBar().value()
            old = scroll.takeWidget()
            if old is not None:
                old.hide()
                old.deleteLater()
            scroll.setWidget(builders[name]())
            QTimer.singleShot(0, lambda s=scroll, p=position: sip.isdeleted(s) or
                              s.verticalScrollBar().setValue(p))

    def graphRebuilt(self):
        """The workflow editor redrew the graph: show the new node of the step."""
        if self.isVisible() and self._node_name is not None:
            self._pending.clear()
            self.rebuild()

    def _updateTitle(self, node):
        step = node.getCWL()
        title = step.label or getattr(node.getCWLTool(), 'label', None) or shortId(step.id)
        self.title.setText(title)
        self.title.setToolTip(title)

    def _onGraphEdited(self):
        """Connections changed on the canvas: refresh the Inputs tab."""
        if self._applying or not self.isVisible() or self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._refreshInputs)

    def _refreshInputs(self):
        self._refresh_pending = False
        if sip.isdeleted(self) or not self.isVisible():
            return
        if self.node() is None:
            self.close_inspector()
            return
        self.rebuild(("Inputs",))

    def _onNodesDeleted(self, *_):
        # after the event: redrawing the graph deletes the nodes and adds them again
        QTimer.singleShot(0, self._closeIfDeleted)

    def _closeIfDeleted(self):
        if not sip.isdeleted(self) and self.isVisible() and self.node() is None:
            self._pending.clear()
            self.close_inspector()

    # -- applying changes ------------------------------------------------------------
    def schedule(self, key, apply: Callable[[], None], immediate: bool = False, delay: Optional[int] = None):
        """Apply a change after a short delay (``immediate``: right away)."""
        self._pending[key] = apply
        if immediate:
            self.applyPending()
        else:
            self._apply_timer.start(delay if delay is not None else self.APPLY_DELAY_MS)

    def applyPending(self):
        self._apply_timer.stop()
        pending, self._pending = self._pending, {}
        for apply in pending.values():
            if self.node() is None:
                return
            apply()

    def _changed(self):
        """Tell the workflow editor the workflow changed."""
        self._applying = True
        try:
            self.graph.editingFinished.emit()
        finally:
            self._applying = False

    def setStepField(self, name: str, value: Any):
        node = self.node()
        if node is None:
            return
        step = node.getCWL()
        if getattr(step, name, None) == value:
            return
        setattr(step, name, value)
        if name == 'label':
            node.setCustomTitle()
            self._updateTitle(node)
        elif name == 'when':
            node.applyNodeColors(theme.GRAPH['step_conditional' if value else 'step'])
        elif name == 'doc' and node.has_property('documentation'):
            node.set_property('documentation', value or '', push_undo=False)
        self._changed()

    def setScatter(self, port_names: List[str]):
        step = self.step()
        if step is None:
            return
        prefix = f"{step.id}/" if '#' in str(step.id) else ""
        values = []
        for port_name in port_names:
            step_input = self.stepInput(port_name)
            values.append(step_input.id if step_input is not None else f"{prefix}{port_name}")
        value = None if not values else values[0] if len(values) == 1 else values
        self.setStepField('scatter', value)

    def setStepInputField(self, port_name: str, name: str, value: Any):
        """Set a field (default, linkMerge, pickValue, source) of a step input,
        adding the input to the step when needed and removing it when empty."""
        step_input = self.stepInput(port_name, create=value is not None)
        if step_input is None or getattr(step_input, name, None) == value:
            return
        setattr(step_input, name, value)
        if not any(getattr(step_input, field, None) not in (None, [], '')
                   for field in ('source', 'default', 'linkMerge', 'pickValue', 'valueFrom',
                                 'loadContents', 'loadListing', 'label')):
            self.step().in_.remove(step_input)
        self._changed()
        if name == 'pickValue':
            QTimer.singleShot(0, lambda: self.rebuild(("Inputs",)))

    def setPortOption(self, port_name: str, option: str):
        node = self.node()
        if node is None:
            return
        self.applyPending()
        self._applying = True
        try:
            self.graph.setPortOption(node, port_name, option)
        finally:
            self._applying = False
        QTimer.singleShot(0, lambda: sip.isdeleted(self) or self.rebuild(("Inputs", "Step")))

    def renameStep(self, new_id: str) -> Optional[str]:
        """Change the step's ID; returns an error message when it cannot."""
        node = self.node()
        if node is None:
            return None
        step = node.getCWL()
        old_id = step.id
        if new_id == shortId(old_id):
            return None
        if not new_id:
            return "ID must be set"
        invalid = sorted(set(ID_CHARACTERS.findall(new_id)))
        if invalid:
            listed = ", ".join(f"“{c}”" for c in invalid)
            return f"ID “{new_id}” contains invalid characters: {listed}"
        taken = {shortId(n.name()) for n in self.graph.graph.all_nodes() if n is not node}
        if new_id in taken:
            return f"ID already exists on graph, the next available id is \"{self.graph.nextAvailableId(new_id)}\""
        full_id = f"{old_id.rsplit('#', 1)[0]}#{new_id}" if '#' in old_id else new_id
        step.id = full_id
        self._applying = True
        try:
            self.graph.nodeEdited(node, old_id)
        finally:
            self._applying = False
        self._renameOwnReferences(step, old_id, step.id)
        self._node_name = node.name()
        node.setCustomTitle()
        self._updateTitle(node)
        self._changed()
        return None

    @staticmethod
    def _renameOwnReferences(step, old_id: str, new_id: str):
        """The step's inputs, outputs and scatter carry its ID."""
        def renamed(value):
            if isinstance(value, str) and value.startswith(old_id + '/'):
                return new_id + value[len(old_id):]
            return value
        for step_input in (step.in_ or []):
            step_input.id = renamed(step_input.id)
        outputs = []
        for step_output in (step.out or []):
            if isinstance(step_output, str):
                outputs.append(renamed(step_output))
            else:
                step_output.id = renamed(step_output.id)
                outputs.append(step_output)
        step.out = outputs
        if isinstance(step.scatter, list):
            step.scatter = [renamed(s) for s in step.scatter]
        elif step.scatter:
            step.scatter = renamed(step.scatter)

    def editExpression(self, line_edit: QLineEdit):
        """The Expression Editor for the step's ``when``."""
        from JavascriptEditor import JavaScriptEditorDialog
        dialog = JavaScriptEditorDialog(cwl_dict=self.step(), parent=self.window())
        if line_edit.text():
            dialog.editor.setText(line_edit.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            code = dialog.get_javascript_code()
            if code is not None:
                line_edit.setText(code)
                self.schedule('when', lambda: self.setStepField('when', line_edit.text() or None), True)

    def editHints(self):
        step = self.step()
        if step is None:
            return

        def apply(hints):
            node = self.node()
            if node is None:
                return
            node.getCWL().hints = [dict(h) for h in hints] or None
            self._changed()

        dialog = HintsDialog(list(step.hints or []), apply, parent=self.window())
        self.hints_dialog = dialog
        dialog.exec()

    # -- closing ---------------------------------------------------------------------
    def close_inspector(self):
        if self._node_name is not None and self.node() is not None:
            self.applyPending()
        self._pending.clear()
        self._apply_timer.stop()
        self._node_name = None
        for scroll in self.scrolls:
            old = scroll.takeWidget()
            if old is not None:
                old.hide()
                old.deleteLater()
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_inspector()
            return
        super().keyPressEvent(event)
