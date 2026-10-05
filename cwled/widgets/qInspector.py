"""
Rabix Composer object inspector.

Clicking an argument, input or output of the tool visual editor opens it in
an inspector docked on the right of the editor instead of a separate
dialog window. The inspector re-arranges the widgets of the existing
ArgumentDialog / InputDialog / OutputDialog into Composer's form (labels
above fields, Yes/No switches, collapsible sections) and applies every change
to the tool as it is made, like Composer does. The dialog object itself
stays hidden and keeps doing the work (validation, building the CWL object).
"""
import logging
from typing import Callable, Optional

from cwl_utils.parser import save
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (QAbstractButton, QCheckBox, QComboBox, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                             QPushButton, QScrollArea, QTableWidget,
                             QTextEdit, QToolButton, QVBoxLayout, QWidget)

import theme
from testJob import documentPath, testJobs
from JavascriptEditor import validateExpression

logger = logging.getLogger("Inspector")

DESCRIPTION_HELP = ("This description is visible from the workflow editor. "
                    "It’s best to be concise and informative.")
TEST_VALUE_HELP = ("Used for this input in the command line preview and in the Expression "
                   "Editor, instead of a sample value. It is not saved in the document.")
LOAD_CONTENT_HELP = ("Read up to the first 64 KiB of text from the file and place it in the "
                     "\"contents\" field of the file object for manipulation by expressions.")


def _takeAll(layout):
    """Remove every item from a layout without deleting the widgets."""
    while layout.count():
        layout.takeAt(0)


class ComposerForm(QWidget):
    """Base class of the inspector forms: Composer form groups and sections."""

    def __init__(self, dialog, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName('inspectorBody')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.dialog = dialog
        self.main = QVBoxLayout(self)
        self.main.setContentsMargins(13, 13, 13, 13)
        self.main.setSpacing(13)          # .form-group margin-bottom
        self._dynamic = []                # wrappers rebuilt by arrange()

    # -- building blocks ------------------------------------------------------
    def field(self, layout, label, widget, addon=None, text=None, editor_button=None):
        """
        A Composer form group. ``editor_button`` is the dialog's (hidden)
        expression-editor button: the field becomes an expression input.
        """
        if widget is None:
            return None
        if text is not None:
            if isinstance(label, QLabel):
                label.setText(text)
            else:
                label = text
        if isinstance(widget, QLineEdit):
            widget.setPlaceholderText("")      # Composer fields have no placeholders
        open_editor = editor_button.click if editor_button is not None else None
        validator = self._validateExpression if editor_button is not None else None
        group = theme.FieldGroup(label, widget, addon=addon, parent=self, open_editor=open_editor,
                                 validator=validator)
        layout.addWidget(group)
        return group

    def _validateExpression(self, code, report):
        """Evaluate an expression of the entry as the Expression Editor would."""
        d = self.dialog
        port = (getattr(d, 'input_parameter', None) or getattr(d, 'output_parameter', None)
                or getattr(d, 'argument_parameter', None))
        validateExpression(self, port, code, report)

    def toggle(self, layout, checkbox, text=None, on="Yes", off="No"):
        if checkbox is None:
            return None
        row = theme.ToggleRow(checkbox, text, on=on, off=off, parent=self)
        layout.addWidget(row)
        return row

    def section(self, layout, title):
        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(13)
        section = theme.FormSection(container, title=title, borderless=True, parent=self)
        layout.addWidget(section)
        return section, container_layout

    def helpText(self, layout, text):
        label = QLabel(text, self)
        label.setProperty('help', True)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def textArea(self, edit):
        """Composer description textarea: four lines high."""
        if edit is not None:
            edit.setFixedHeight(edit.fontMetrics().lineSpacing() * 4 + 14)
        return edit

    def secondaryFiles(self, layout, group):
        if group is None:
            return None
        section = theme.FormSection(group, title="Secondary Files", add_text="Add secondary file",
                                    empty_text="No Secondary Files defined.", borderless=True,
                                    parent=self)
        layout.addWidget(section)
        return section

    def fileTypes(self, layout, widget):
        """'File type(s)': a list group (with its own add button) or a single field."""
        if widget is None:
            return None
        header = getattr(widget, 'header', None)
        if header is None:
            return self.field(layout, "File type(s)", widget)
        header.hide()
        group = QWidget(self)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(6)
        group_layout.addWidget(QLabel("File type(s)", group))
        if QWidget.layout(widget) is not None:
            QWidget.layout(widget).setContentsMargins(0, 0, 0, 0)
        group_layout.addWidget(widget)
        add = QPushButton("Add a file type", group)
        add.setIcon(theme.icon('plus', color=theme.SKY))
        add.setIconSize(QSize(14, 14))
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.setButtonRole(add, 'link')
        add.clicked.connect(header.addButtonClicked.emit)
        group_layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(group)
        return group

    def relaxWidths(self):
        """Let drop-downs shrink to the panel width instead of their longest item."""
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)

    def dynamic(self, wrapper):
        if wrapper is not None:
            self._dynamic.append(wrapper)
        return wrapper

    def replaceDynamic(self, build: Callable[[], None]):
        """Rebuild the parts that depend on the selected type."""
        old = self._dynamic
        self._dynamic = []
        build()
        # The widgets moved into the new wrappers; drop the old wrappers
        for wrapper in old:
            wrapper.hide()
            wrapper.deleteLater()
        self.relaxWidths()


class InputForm(ComposerForm):
    """Composer ct-tool-input-inspector."""

    def __init__(self, dialog, parent=None):
        super().__init__(dialog, parent)
        d, m = dialog, self.main
        self.toggle(m, d.required_checkbox, "Required")
        self.field(m, d.id_label, d.id_input, text="ID")
        self.field(m, d.field_name_label, d.field_name_input, text="Field Name")
        self.field(m, d.data_type_label, d.data_type_combobox, text="Type")
        self.field(m, "Array", d.array_combobox)
        self.type_area = QVBoxLayout()
        self.type_area.setSpacing(13)
        m.addLayout(self.type_area)
        if getattr(d, 'command_line_checkbox', None) is not None:
            self.toggle(m, d.command_line_checkbox, "Include in the command line")
            self.field(m, d.value_label, d.value_input, editor_button=d.code_button, text="Value Transform")
            self.field(m, d.prefix_label, d.prefix_input, text="Prefix")
            self.field(m, d.position_label, d.position_input, text="Position")
            self.toggle(m, d.separate_value_prefix_checkbox, "Separate value and prefix")
            self.field(m, d.item_separator_label, d.item_separator_combobox, text="Item Separator")
            self.toggle(m, d.shellquote_checkbox, "shellQuote")
        self.field(m, d.defaultvalue_label, d.defaultvalue_input, text="Default Value")
        m.addWidget(d.record_default_widget)
        self.sections_area = QVBoxLayout()
        self.sections_area.setSpacing(13)
        m.addLayout(self.sections_area)

        self.description, description = self.section(m, "Description")
        self.helpText(description, DESCRIPTION_HELP)
        self.field(description, d.label_label, d.label_input, text="Label")
        self.field(description, d.description_label, self.textArea(d.description_input), text="Description")
        self.file_types_area = QVBoxLayout()
        description.addLayout(self.file_types_area)

        # Composer "Test Value" (inputs of the tool itself, not record fields)
        self.test_value = None
        if d.input_parameter_type == 'CommandInputParameter':
            self.test_section, test_body = self.section(m, "Test Value")
            self.helpText(test_body, TEST_VALUE_HELP)
            self.test_value = QLineEdit(self)
            self.test_value.setProperty('inspectorHooked', True)     # not part of the CWL
            self.test_value.setClearButtonEnabled(True)
            self.test_value.editingFinished.connect(self._storeTestValue)
            test_body.addWidget(self.test_value)
            QTimer.singleShot(0, self._loadTestValue)
        m.addStretch(1)

        self.arrange()
        d.data_type_combobox.currentTextChanged.connect(self.arrange)
        d.array_combobox.currentTextChanged.connect(self._updateTestPlaceholder)

    # -- test value -----------------------------------------------------------------
    def _loadTestValue(self):
        if self.test_value is None:
            return
        values = testJobs().values(documentPath(self))
        self.test_value.setText(values.get(self.dialog.id_input.text(), ''))
        self._updateTestPlaceholder()

    def _storeTestValue(self):
        testJobs().setValue(documentPath(self), self.dialog.id_input.text(), self.test_value.text())

    def _updateTestPlaceholder(self, *_):
        """What to type, for the input's type (Composer shows a typed editor)."""
        if self.test_value is None:
            return
        d = self.dialog
        kind = d.data_type_combobox.currentText()
        input_id = d.id_input.text() or 'input'
        examples = {
            'File': f"/path/to/{input_id}.ext", 'Directory': f"/path/to/{input_id}",
            'string': f"{input_id}-string-value", 'int': "a whole number, e.g. 5",
            'long': "a whole number, e.g. 5", 'float': "a number, e.g. 2.5", 'double': "a number, e.g. 2.5",
            'boolean': "true or false", 'record': 'a JSON object, e.g. {"field": "value"}',
        }
        text = examples.get(kind, "a value")
        if kind == 'enum' and d.enum_table_widget is not None:
            symbols = d.enum_table_widget.getTags()
            text = f"one of: {', '.join(symbols)}" if symbols else "one of the symbols"
        if d.array_combobox.currentText() == 'Array Only':
            text = f"comma separated values ({text})"
        self.test_value.setPlaceholderText(text)

    def arrange(self, *_):
        d = self.dialog
        QTimer.singleShot(0, self._updateTestPlaceholder)
        # the name is the field's for a record field, the enum type's otherwise
        if d.input_parameter_type != 'CommandInputRecordField':
            d.field_name_label.setText("Enum Name")

        def build():
            for area in (self.type_area, self.sections_area, self.file_types_area):
                _takeAll(area)
            if d.enum_table_widget is not None:
                self.dynamic(self.field(self.type_area, "Symbols", d.enum_table_widget))
            if d.record_type_list_widget is not None:
                self.dynamic(self.field(self.type_area, d.record_type_label, d.record_type_list_widget,
                                        text="Record Type"))
            if any(w is not None for w in (d.load_content_checkbox, d.streamable_checkbox,
                                           d.load_listing_combobox)):
                section, body = self.section(self.sections_area, "Load Content")
                self.dynamic(section)
                self.toggle(body, d.load_content_checkbox, "Load Content")
                self.toggle(body, d.streamable_checkbox, "Is streamable")
                self.field(body, "Load Listing", d.load_listing_combobox)
            self.dynamic(self.secondaryFiles(self.sections_area, d.secondary_files_input))
            self.dynamic(self.fileTypes(self.file_types_area, d.file_type_list_widget))

        self.replaceDynamic(build)


class OutputForm(ComposerForm):
    """Composer ct-tool-output-inspector."""

    def __init__(self, dialog, parent=None):
        super().__init__(dialog, parent)
        d, m = dialog, self.main
        self.toggle(m, d.required_checkbox, "Required")
        self.field(m, d.id_label, d.id_input, text="ID")
        self.field(m, d.field_name_label, d.field_name_input, text="Field Name")
        self.field(m, d.pick_value_label, d.pick_value_combobox, text="Pick Value")
        self.field(m, d.link_merge_label, d.link_merge_combobox, text="Link Merge")
        self.field(m, d.data_type_label, d.data_type_combobox, text="Type")
        self.field(m, "Array", d.array_combobox)
        self.type_area = QVBoxLayout()
        self.type_area.setSpacing(13)
        m.addLayout(self.type_area)
        self.toggle(m, d.record_field_checkbox, "Record Field")
        m.addWidget(d.record_id)
        self.field(m, d.glob_label, d.glob_input, editor_button=d.glob_code_button, text="Glob")

        self.output_eval, output_eval = self.section(m, "Output Eval")
        self.field(output_eval, d.output_eval_label, d.output_eval, editor_button=d.output_eval_code,
                   text="Output eval")
        self.load_area = QVBoxLayout()
        self.load_area.setSpacing(13)
        output_eval.addLayout(self.load_area)
        self.sections_area = QVBoxLayout()
        self.sections_area.setSpacing(13)
        m.addLayout(self.sections_area)

        self.description, description = self.section(m, "Description")
        self.helpText(description, DESCRIPTION_HELP)
        self.field(description, d.label_label, d.label_input, text="Label")
        self.field(description, d.description_label, self.textArea(d.description_input), text="Description")
        self.file_types_area = QVBoxLayout()
        description.addLayout(self.file_types_area)
        m.addStretch(1)

        self.arrange()
        d.data_type_combobox.currentTextChanged.connect(self.arrange)

    def arrange(self, *_):
        d = self.dialog

        def build():
            for area in (self.type_area, self.load_area, self.sections_area, self.file_types_area):
                _takeAll(area)
            if d.enum_table_widget is not None:
                self.dynamic(self.field(self.type_area, "Symbols", d.enum_table_widget))
            if d.load_content_checkbox is not None:
                self.dynamic(self.toggle(self.load_area, d.load_content_checkbox, "Load Content"))
                help_label = self.helpText(self.load_area, LOAD_CONTENT_HELP)
                self.dynamic(help_label)
            self.dynamic(self.toggle(self.load_area, d.streamable_checkbox, "Is streamable"))
            self.dynamic(self.field(self.load_area, "Load Listing", d.load_listing_combobox))
            self.dynamic(self.secondaryFiles(self.sections_area, d.secondary_files_input))
            self.dynamic(self.fileTypes(self.file_types_area, d.file_type_list_widget))

        self.replaceDynamic(build)


class ArgumentForm(ComposerForm):
    """Composer ct-argument-inspector."""

    def __init__(self, dialog, parent=None):
        super().__init__(dialog, parent)
        d, m = dialog, self.main
        code_buttons = [b for b in d.findChildren(QPushButton) if b.toolTip() == "Edit JavaScript expression"]
        self.field(m, "Prefix", d.prefix_edit)
        self.field(m, "Value", d.argument_edit, editor_button=code_buttons[0] if code_buttons else None)
        self.toggle(m, d.separate_value_and_prefix_check, "Separate value and prefix")
        self.field(m, "Position", d.position_edit)
        self.toggle(m, d.shell_quote_check, "shellQuote")
        m.addStretch(1)


def buildForm(dialog) -> ComposerForm:
    name = dialog.__class__.__name__
    if name == 'InputDialog':
        return InputForm(dialog)
    if name == 'OutputDialog':
        return OutputForm(dialog)
    if name == 'ArgumentDialog':
        return ArgumentForm(dialog)
    raise TypeError(f"No inspector form for {name}")


class Inspector(QFrame):
    """
    Composer ``ct-editor-inspector``: a panel on the right of the visual
    editor with the selected entry's name, a close button and its form.
    """
    DEFAULT_WIDTH = 320
    APPLY_DELAY_MS = 400

    def __init__(self, root: QWidget, parent: Optional[QWidget] = None):
        """
        Args:
            root: the widget holding the list rows the inspector edits.
        """
        super().__init__(parent)
        self.setObjectName('inspector')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(280)
        self._root = root
        self._dialog = None
        self._form = None
        self._target = None
        self._row_class = None
        self._title_of = None
        self._highlighted = None

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

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(self.APPLY_DELAY_MS)
        self._apply_timer.timeout.connect(self.apply)
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(self.DEFAULT_WIDTH, 400)

    # -- lookup -------------------------------------------------------------------
    @staticmethod
    def forWidget(widget: QWidget) -> Optional['Inspector']:
        """The inspector serving a list row, or None (e.g. rows inside dialogs)."""
        current = widget
        while current is not None:
            if isinstance(current, Inspector):
                return None
            inspector = getattr(current, 'inspector', None)
            if isinstance(inspector, Inspector):
                return inspector
            current = current.parentWidget()
        return None

    def _findRow(self):
        if self._row_class is None:
            return None
        # Newest rows first: rebuilt lists keep their old rows until deleteLater() runs
        rows = list(reversed(self._root.findChildren(self._row_class)))
        for row in rows:
            if row.getCWL() is self._target:
                return row
        try:
            wanted = save(self._target)
        except Exception:
            return None
        for row in rows:
            try:
                if save(row.getCWL()) == wanted:
                    return row
            except Exception:
                continue
        return None

    # -- inspecting -----------------------------------------------------------------
    def inspect(self, row, dialog, title_of: Callable[[object], str]):
        """Show ``dialog`` (built for ``row``) in the inspector."""
        self.applyPending()
        self._release()
        self._row_class = type(row)
        self._target = row.getCWL()
        self._title_of = title_of
        # Keep the dialog alive when the row is rebuilt by an editor refresh
        dialog.setParent(self)
        dialog.hide()
        self._dialog = dialog
        self._form = buildForm(dialog)
        self._form.relaxWidths()
        self.scroll.setWidget(self._form)
        self._hook()
        self._updateTitle()
        self.show()
        self._highlight()

    def openEntry(self, data, row_class, delay_ms: int = 0):
        """Open the row showing ``data`` once the editor has been refreshed."""
        def open_row():
            self._row_class = row_class
            self._target = data
            row = self._findRow()
            if row is not None:
                row.onEditClicked()
        QTimer.singleShot(delay_ms, open_row)

    def entriesRefreshed(self):
        """Called after the editor rebuilt its rows."""
        if self._dialog is None:
            return
        if self._findRow() is None:
            # Composer closes the inspector when its entry is deleted
            self._release()
            self.hide()
        else:
            self._highlight()

    def _updateTitle(self):
        try:
            title = self._title_of(self._dialog) if self._title_of else ""
        except Exception:
            title = ""
        self.title.setText(title)
        self.title.setToolTip(title)

    def _highlight(self):
        """Composer marks the inspected entry (.ct-inspected)."""
        self._setInspected(self._highlighted, False)
        row = self._findRow()
        bar = getattr(row, 'row_bar', None) if row is not None else None
        self._setInspected(bar, True)
        self._highlighted = bar

    @staticmethod
    def _setInspected(bar, inspected: bool):
        if bar is None:
            return
        try:
            bar.setProperty('inspected', inspected)
            bar.style().unpolish(bar)
            bar.style().polish(bar)
        except RuntimeError:
            pass   # the row was rebuilt

    # -- live update ----------------------------------------------------------------
    def _hook(self):
        """Apply the entry whenever any field of the form changes."""
        if self._form is None:
            return
        for widget in self._form.findChildren(QWidget):
            if widget.property('inspectorHooked'):
                continue
            widget.setProperty('inspectorHooked', True)
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._schedule)
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                widget.textChanged.connect(self._schedule)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._schedule)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._schedule)
            elif isinstance(widget, QTableWidget):
                widget.itemChanged.connect(self._schedule)
            elif isinstance(widget, QAbstractButton):
                widget.clicked.connect(self._schedule)

    def _schedule(self, *_):
        self._apply_timer.start()

    def applyPending(self):
        if self._apply_timer.isActive():
            self.apply()

    def apply(self):
        """Write the inspected entry back into the tool."""
        self._apply_timer.stop()
        if self._dialog is None:
            return
        self._hook()   # widgets added after a type change
        try:
            data = self._dialog.getData()
        except Exception as e:
            logger.debug(f"Entry not applied, the form is incomplete: {e}")
            return
        if data is None:
            return
        try:
            if save(data) == save(self._target):
                return
        except Exception:
            pass
        row = self._findRow()
        if row is None:
            logger.debug("The inspected entry is no longer in the editor")
            return
        self._target = data
        row.setCWL(data)          # refreshes the editor, rows are rebuilt
        self._updateTitle()
        QTimer.singleShot(0, self._highlight)

    # -- closing --------------------------------------------------------------------
    def _release(self):
        self._apply_timer.stop()
        self._setInspected(self._highlighted, False)
        self._highlighted = None
        form = self.scroll.takeWidget()
        if form is not None:
            form.deleteLater()
        if self._dialog is not None:
            self._dialog.deleteLater()
        self._dialog = None
        self._form = None
        self._target = None

    def close_inspector(self):
        self.applyPending()
        self._release()
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_inspector()
            return
        super().keyPressEvent(event)
