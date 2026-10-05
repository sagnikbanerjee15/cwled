from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor,QFontMetrics

import copy
import json
from configuration import Configuration
import builtins
import logging
from sanitizeName import sanitize
from widgets.qButtons import *
from JavascriptEditor import JavaScriptEditorDialog
import theme
from widgets.qSecondaryFiles import QSecondaryFilesGroupWidget
from Tags import QTagWidget
import sys 
import logging
from dataTypes import input
from copy import deepcopy
from typing import Any, Tuple 
import data
import CWLparser 
import jinja2
import uuid
from pathlib import Path
from widgets.qLabelLineEditWidget import QLabelLineEditWidget
from widgets.qSchema import QSchemaListGroupWidget
import re
from CWLparser import Parser, is_array, is_optional_array, is_optional, get_type
from cwl_utils.parser import save
from cwl_utils_handler import get_cwl_module, get_cwl_version
from BaseDialog import BaseDialog
logger = logging.getLogger(__name__)

def _mainSchema(cwl_type: Any) -> Any:
    """The (first) non-null type of a parameter."""
    if isinstance(cwl_type, list):
        types = [t for t in cwl_type if t != 'null']
        return types[0] if types else None
    return cwl_type


def _schemas(cwl_type: Any):
    """The schema objects in a type (inside unions too)."""
    if isinstance(cwl_type, list):
        for item in cwl_type:
            yield from _schemas(item)
    elif cwl_type is not None and not isinstance(cwl_type, str):
        yield cwl_type


def _workingCopy(parameter):
    """A shallow copy of a parameter with its own type list, for the dialog
    to read (and trim) without changing the parameter of the tool."""
    duplicate = copy.copy(parameter)
    if isinstance(getattr(parameter, 'type_', None), list):
        duplicate.type_ = list(parameter.type_)
    return duplicate


class InputDialog(BaseDialog):
    code=''
    codeUpdated = pyqtSignal() # emit this signal when the code is updated
    input_parameter=None
    input_parameter_type=None
    cwl_version:str=None
    def __init__(self, 
                 input_parameter:Any=None, 
                 input_parameter_type:str=None,
                 cwl_version:str=None,
                 parent=None):
        '''
        InputDialog is a dialog to edit the input parameters of a CWL Input parameter.

        '''
        super().__init__(parent)
        self.logger=logging.getLogger(__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        # bindings as loaded, so that saving keeps what the dialog does not edit
        self._original_binding = None   # the binding edited by the dialog
        self._type_binding = None       # ... when it lives on an enum/record type
        self._item_binding = None       # the binding of array items (kept as is)
        self._command_line_before_record = None
        
        if input_parameter is not None and cwl_version is None:
            self.setCWLVersion(input_parameter)
        elif cwl_version is not None:
            self.setCWLVersion(cwl_version)
        else:
            raise ValueError("Either input_parameter or cwl_version must be provided.")
        
        # Set input_parameter_type before calling initUI
        if input_parameter is not None:
            self.input_parameter_type = type(input_parameter).__name__
        elif input_parameter_type is not None:
            self.input_parameter_type = input_parameter_type
        else:
            raise ValueError("Either input_parameter or input_parameter_type must be provided.")
        
        # Set the dialog title
        self.setWindowTitle(f"Inputs (cwl: {self.cwl_version})")
        self.initUI()
        self.logger.debug(" ===== Input Dialog ==========")
        if input_parameter is not None:
            # a working copy: loading must not change the tool (it strips 'null'...)
            self.input_parameter=_workingCopy(input_parameter)
            logger.debug(f"Received the object of type {input_parameter}")
            self.setDefaults()
        elif input_parameter_type is not None:
            logger.debug(f"Setting the object to {input_parameter_type} from the arguments")
            self.onDataTypeChanged()
            
        self.logger.debug(f"InputDialog received {self.input_parameter_type}")

    def initUI(self):
        # Main layout for the dialog
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)  # Set margins to zero

        # Create a scroll area
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        # Create a widget to hold all the other widgets
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)  # Set margins to zero


        # ID input
        self.id_label = QLabel("ID:")
        self.id_input = QLineEdit(self)
        self.id_input.setPlaceholderText("Enter ID")
        self.id_input.setText(f"input{ str(uuid.uuid4())[:4]}")
        self.id_input.textChanged.connect(
            lambda:self.sanitizeID(
                self.id_input.text(),
                self.id_input
            )
        )
        
        # Field name input
        self.field_name_label = QLabel("Field Name:")
        self.field_name_input = QLineEdit(self)
        self.field_name_input.setPlaceholderText("Enter Field Name")
        self.field_name_input.setText(f"name{ str(uuid.uuid4())[:4]}")
        self.field_name_input.textChanged.connect(
            lambda:self.sanitizeID(
                self.field_name_input.text(),
                self.field_name_input
            )
        )
        # Initially hide the field name input (will be shown when enum type is selected)
        self.field_name_label.setVisible(False)
        self.field_name_input.setVisible(False)
        
        # Required checkbox
        self.required_checkbox = QCheckBox("Required")

        # Data type ComboBox
        self.data_type_label = QLabel("Data Type:")
        self.data_type_combobox = QComboBox(self)
        self.data_type_combobox.addItems(data.configuration.get('CWL_types'))
        self.data_type_combobox.currentTextChanged.connect(self.onDataTypeChanged)

        # Record handling layout has been removed
        

        # Array Handling options (tri-state radio buttons)
        self.array_handling_layout=QHBoxLayout()
        self.array_combobox = QComboBox(self)
        self.array_combobox.addItems(['Single Item','Allow Array','Array Only'])
        self.array_handling_layout.addWidget(self.array_combobox)

        # self.array_checkbox = QCheckBox("Array")
        # self.single_item_checkbox = QCheckBox("Single Item")
        # self.array_handling_layout = QHBoxLayout()
        # self.array_handling_layout.addWidget(self.single_item_checkbox)
        # self.array_handling_layout.addWidget(self.array_checkbox)
        self.array_combobox.currentTextChanged.connect(self.toggleCommandLineOptions)
        

        
        self.code_button=QCodeButton()
        self.code_button.clicked.connect( lambda:self.onCodeEditor(self.value_input))
        
        

        # Default value (scalar)
        self.defaultvalue_label = QLabel("Default:")
        self.defaultvalue_input = QLineEdit(self)
        self.defaultvalue_input.setPlaceholderText("Enter Default Value")

        # Editable record field defaults (shown for record types)
        self.record_default_widget = QGroupBox("Record Defaults")
        self.record_default_layout = QVBoxLayout(self.record_default_widget)
        self.record_default_layout.setContentsMargins(5, 5, 5, 5)
        self.record_default_fields = {}  # {field_name: QLineEdit}
        self.record_default_field_types = {}  # {field_name: str} — CWL type per field
        self.record_default_record_type = 'dependent'  # 'dependent' or 'exclusive'
        self.record_default_widget.setVisible(False)

        
        # Label input
        self.label_label = QLabel("Label:")
        self.label_input = QLineEdit(self)

        # Description input
        self.description_label = QLabel("Description:")
        self.description_input = QTextEdit(self)

        # Dynamic widgets that appear based on the data type
        self.enum_table_widget = None
        self.load_content_checkbox = None
        self.load_listing_combobox = None
        self.streamable_checkbox = None
        self.secondary_files_input = None
        self.file_type_list_widget = None
        self.file_type_table = None
        self.record_type_label=None
        self.record_type_list_widget=None

        # Add widgets to the layout
        scroll_layout.addWidget(self.required_checkbox)
        scroll_layout.addWidget(self.id_label)
        scroll_layout.addWidget(self.id_input)
        
        is_input_parameter = (self.input_parameter_type in [ 'InputParameter' ,'WorkflowInputParameter'])
        # Field name only for non-InputParameter types
        scroll_layout.addWidget(self.field_name_label)
        scroll_layout.addWidget(self.field_name_input)
        
        # Command line options only for non-InputParameter types
        if not is_input_parameter:
            # Include in command line checkbox
            self.command_line_checkbox = QCheckBox("Include in command line")
            self.command_line_checkbox.setChecked(True)
            self.command_line_checkbox.stateChanged.connect(self.toggleCommandLineOptions)

            # Prefix input
            self.prefix_label = QLabel("Prefix:")
            self.prefix_input = QLineEdit(self)
            self.prefix_input.setPlaceholderText("Enter Prefix")

            # Value input
            
            self.value_label = QLabel("Value:")
            self.value_input = QLineEdit(self)
            self.value_input.setPlaceholderText("Enter Value")
            # Position input
            self.position_label = QLabel("Position:")
            self.position_input = QLineEdit(self)
            self.position_input.setPlaceholderText("0")
            self.position_input.setText("0")

            # Item Separator option
            self.item_separator_label = QLabel("Item Separator:")
            self.item_separator_combobox = QComboBox(self)
            self.item_separator_combobox.addItems(['space',',',';',':','-','/','other'])

            # Separate value and prefix checkbox
            self.separate_value_prefix_checkbox = QCheckBox("Separate value and prefix")
            self.separate_value_prefix_checkbox.setChecked(True)
            # Shell quote
            self.shellquote_checkbox = QCheckBox("ShellQuote")
            self.shellquote_checkbox.setChecked(False)
            # the </> button is attached to the value field (Composer input group)
            layout_in=QHBoxLayout()
            layout_in.addWidget(theme.InputGroup(self.value_input, self.code_button, parent=self))

            scroll_layout.addWidget(self.command_line_checkbox)

            # Add Prefix and Value inputs
            scroll_layout.addWidget(self.prefix_label)
            scroll_layout.addWidget(self.prefix_input)
            scroll_layout.addWidget(self.value_label)
            scroll_layout.addLayout(layout_in)
            scroll_layout.addWidget(self.position_label)
            scroll_layout.addWidget(self.position_input)

            # Add Item Separator widget (initially hidden)
            scroll_layout.addWidget(self.item_separator_label)
            scroll_layout.addWidget(self.item_separator_combobox)

            # Add Separate value and prefix checkbox
            scroll_layout.addWidget(self.separate_value_prefix_checkbox)
            scroll_layout.addWidget(self.shellquote_checkbox)
        
        # Default value is shown for both (it's in the allowed list)
        scroll_layout.addWidget(self.defaultvalue_label)
        scroll_layout.addWidget(self.defaultvalue_input)
        scroll_layout.addWidget(self.record_default_widget)
        
        # Label and Description (both in allowed list)
        scroll_layout.addWidget(self.label_label)
        scroll_layout.addWidget(self.label_input)
        scroll_layout.addWidget(self.description_label)
        scroll_layout.addWidget(self.description_input)
        
        # Data Type ComboBox (type is in allowed list)
        scroll_layout.addWidget(self.data_type_label)
        scroll_layout.addWidget(self.data_type_combobox)
        
        # Add Array handling options
        scroll_layout.addLayout(self.array_handling_layout)
        
        # Dynamic area where new widgets will be added based on Data Type
        self.dynamic_area_layout = QVBoxLayout()
        scroll_layout.addLayout(self.dynamic_area_layout)



        # Dynamic area for file-related widgets (File Type and Table)
        self.file_related_layout = QVBoxLayout()
        scroll_layout.addLayout(self.file_related_layout)

        scroll_area.setWidget(scroll_widget)
        self.layout.addWidget(scroll_area)
        # Add OK/Cancel buttons
        self.button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.button_layout.addWidget(self.ok_button)
        self.button_layout.addWidget(self.cancel_button)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self.layout.addLayout(self.button_layout)

        # show the name if we have a RecordField
        # self.field_name_label.setVisible(self.input_parameter_type == 'CommandInputRecordField')
        # self.field_name_input.setVisible(self.input_parameter_type == 'CommandInputRecordField')
        
        # Initially hide prefix, value, separate prefix/value, and item separator widgets
        self.onDataTypeChanged()
        self.toggleCommandLineOptions()


    def setCWLVersion(self, cwl_version: str):
        if not isinstance(cwl_version, str):
            self.cwl_version = get_cwl_version(cwl_version)
        else:
            self.cwl_version = cwl_version

    def sanitizeID(self,text, widget):
        '''
        make sure the text in the ID field is sanitized
        dependig on the options in the configuration
        '''
        if data.configuration.get('sanitize_id') == 'underscore':
            new_text = sanitize(text).underscore().text
        elif data.configuration.get('sanitize_id') == 'camelCase':
            new_text = sanitize(text).camelCase().text
        elif data.configuration.get('sanitize_id') == 'UpperCamelCase':
            new_text = sanitize(text).UpperCamelCase().text
        elif data.configuration.get('sanitize_id') == 'lowerCamelCase':
            new_text = sanitize(text).lowerCamelCase().text
        elif data.configuration.get('sanitize_id') == 'dash':
            new_text = sanitize(text).dash().text
        elif data.configuration.get('sanitize_id') == 'keepAlphaNum':
            new_text = sanitize(text).keepAlphaNum().text
        else:
            new_text = text
        widget.setText(new_text)
        widget.setCursorPosition(len( new_text ))

    # onRecordFieldChanged method has been removed
        
    def onDataTypeChanged(self):
        """
        Update the dialog UI when the data type changes.
        """
        data_type=self.data_type_combobox.currentText()

        logger.debug(f"Data type changed: working with {data_type} for {self.input_parameter_type}")

        # Clear any previously added dynamic widgets
        for i in reversed(range(self.dynamic_area_layout.count())):
            widget_to_remove = self.dynamic_area_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)

        # Clear file-related layout
        for i in reversed(range(self.file_related_layout.count())):
            widget_to_remove = self.file_related_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)

        
        self.toggleCommandLineOptions()

        # Add widgets based on the selected data type
        if data_type == "enum":
            self.enum_table_widget = QTagWidget(parent=self)
            self.dynamic_area_layout.addWidget( self.enum_table_widget)

        
        if data_type != "enum":
            if self.enum_table_widget:
                self.enum_table_widget.setParent(None)
                self.enum_table_widget = None

        # if data_type == 'boolean':
        #     if self.value_input:
        #         self.value_input.setVisible(False)
        #         self.value_label.setVisible(False)
        #         self.value_input = None
        # if data_type != 'boolean':
        #     if self.value_input:
        #         self.value_input.setVisible(True)
        #         self.value_label.setVisible(True)
        #         self.value_input.setText('')
            

        if data_type=='Directory':
            self.load_listing_combobox = QComboBox(self)
            self.load_listing_combobox.addItems(["no_listing", "shallow_listing", "deep_listing"])
            self.dynamic_area_layout.addWidget(self.load_listing_combobox)
        if data_type != "Directory":
            if self.load_listing_combobox:
                self.load_listing_combobox.setParent(None)
                self.load_listing_combobox = None
            

        if data_type == "File":
            self.load_content_checkbox = QCheckBox("Load Content")
            self.streamable_checkbox = QCheckBox("Is streamable")
            self.secondary_files_input = QSecondaryFilesGroupWidget(parent=self)

            # self.secondary_files_input.setPlaceholderText("Secondary Files")
            self.dynamic_area_layout.addWidget(self.load_content_checkbox)
            self.dynamic_area_layout.addWidget(self.streamable_checkbox)    
            self.dynamic_area_layout.addWidget(self.secondary_files_input)

            # Add File format ListWidget for selecting multiple file types with search
            # self.file_type_list_widget = QTagWidget(parent=self)
            self.file_type_list_widget= QSchemaListGroupWidget(parent=self)
            self.dynamic_area_layout.addWidget(self.file_type_list_widget)


        if data_type != "File":
            if self.load_content_checkbox:
                self.load_content_checkbox.setParent(None)
                self.load_content_checkbox = None
            if self.streamable_checkbox:
                self.streamable_checkbox.setParent(None)
                self.streamable_checkbox = None
            if self.secondary_files_input:
                self.secondary_files_input.setParent(None)
                self.secondary_files_input = None
            if self.file_type_list_widget:
                self.file_type_list_widget.setParent(None)
                self.file_type_list_widget = None
            if self.file_type_table:
                self.file_type_table.setParent(None)
                self.file_type_table = None

        if data_type == 'record':

            self.record_type_list_widget=QComboBox(self)
            self.record_type_list_widget.addItems(['dependent','mutually exclusive'])
            self.record_type_label = QLabel("Record type:")
            self.dynamic_area_layout.addWidget(self.record_type_label)
            self.dynamic_area_layout.addWidget(self.record_type_list_widget)    

            if hasattr(self, 'command_line_checkbox') and self.command_line_checkbox:
                # records are bound through their fields; restored when leaving record
                if self._command_line_before_record is None:
                    self._command_line_before_record = self.command_line_checkbox.isChecked()
                self.command_line_checkbox.setChecked(False)

            # Hide scalar default; show read-only record default summary
            self.defaultvalue_label.setVisible(False)
            self.defaultvalue_input.setVisible(False)
            self.record_default_widget.setVisible(True)


        # show the name field if it is a record
        self.field_name_label.setVisible(data_type=='enum' or self.input_parameter_type == 'CommandInputRecordField')
        self.field_name_input.setVisible(data_type=='enum' or self.input_parameter_type == 'CommandInputRecordField')

        if data_type !='record':
            if self._command_line_before_record is not None and hasattr(self, 'command_line_checkbox'):
                self.command_line_checkbox.setChecked(self._command_line_before_record)
            self._command_line_before_record = None
            if self.record_type_label:
                self.record_type_label.setParent(None)
                self.record_type_label=None
            if self.record_type_list_widget:
                self.record_type_list_widget.setParent(None)
                self.record_type_list_widget=None
            # Show scalar default, hide record default widget
            self.record_default_widget.setVisible(False)

    def updateRecordDefaultFields(self, field_names, defaults=None, record_type='dependent', field_types=None):
        """
        Rebuild the editable per-field default widgets in record_default_widget.

        Args:
            field_names: list of field name strings from the record schema.
            defaults: optional dict of {field_name: default_value}.
            record_type: 'dependent' or 'exclusive'.
            field_types: optional dict of {field_name: cwl_type_string}.
        """
        if defaults is None:
            defaults = {}
        if field_types is None:
            field_types = {}
        self.record_default_record_type = record_type
        self.record_default_field_types = field_types

        # Clear existing widgets
        for i in reversed(range(self.record_default_layout.count())):
            item = self.record_default_layout.itemAt(i)
            w = item.widget() if item else None
            if w:
                w.setParent(None)
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().setParent(None)
                self.record_default_layout.removeItem(item.layout())
        self.record_default_fields = {}

        if record_type == 'exclusive':
            selected_class = defaults.get('class', '')
            # If no class selected, pick the first field with a non-empty default
            if not selected_class and field_names:
                for name in field_names:
                    if name and defaults.get(name, ''):
                        selected_class = name
                        break
                if not selected_class:
                    selected_class = field_names[0] if field_names else ''

            # Combobox for selecting the active class
            class_row = QHBoxLayout()
            class_label = QLabel("Selected:")
            class_label.setStyleSheet("font-weight: bold;")
            self._exclusive_class_combo = QComboBox(self)
            valid_names = [n for n in field_names if n]
            self._exclusive_class_combo.addItems(valid_names)
            if selected_class in valid_names:
                self._exclusive_class_combo.setCurrentText(selected_class)
            self._exclusive_class_combo.currentTextChanged.connect(self._onExclusiveClassChanged)
            class_row.addWidget(class_label)
            class_row.addWidget(self._exclusive_class_combo)
            self.record_default_layout.addLayout(class_row)

            for name in field_names:
                if not name:
                    continue
                row = QHBoxLayout()
                label = QLabel(f"{name}:")
                line_edit = QLineEdit(self)
                value = defaults.get(name, '')
                line_edit.setText(str(value) if value else '')
                ft = field_types.get(name, '')
                if ft:
                    line_edit.setPlaceholderText(f"({ft})")
                if name == selected_class:
                    label.setStyleSheet("font-weight: bold;")
                    line_edit.setStyleSheet("background-color: rgba(0, 120, 215, 0.25);")
                else:
                    line_edit.setStyleSheet("background-color: rgba(128, 128, 128, 0.15);")
                line_edit.setObjectName(name)
                row.addWidget(label)
                row.addWidget(line_edit)
                self.record_default_layout.addLayout(row)
                self.record_default_fields[name] = line_edit
        else:
            for name in field_names:
                if not name:
                    continue
                row = QHBoxLayout()
                label = QLabel(f"{name}:")
                line_edit = QLineEdit(self)
                line_edit.setText(str(defaults.get(name, '')))
                ft = field_types.get(name, '')
                if ft:
                    line_edit.setPlaceholderText(f"({ft})")
                line_edit.setObjectName(name)
                row.addWidget(label)
                row.addWidget(line_edit)
                self.record_default_layout.addLayout(row)
                self.record_default_fields[name] = line_edit

    def _onExclusiveClassChanged(self, selected):
        """Update styling when the exclusive class selection changes."""
        for name, line_edit in self.record_default_fields.items():
            if name == selected:
                line_edit.setStyleSheet("background-color: rgba(0, 120, 215, 0.25);")
            else:
                line_edit.setStyleSheet("background-color: rgba(128, 128, 128, 0.15);")
        # Also update labels
        for i in range(self.record_default_layout.count()):
            item = self.record_default_layout.itemAt(i)
            if item and item.layout():
                for j in range(item.layout().count()):
                    w = item.layout().itemAt(j).widget()
                    if isinstance(w, QLabel) and w.text().endswith(':'):
                        name = w.text()[:-1]
                        if name == selected:
                            w.setStyleSheet("font-weight: bold;")
                        else:
                            w.setStyleSheet("")

    def _convertFieldDefault(self, field_name, text_value):
        """Convert a field default text value to the appropriate Python type based on field_types."""
        if not text_value:
            return None
        ft = self.record_default_field_types.get(field_name, '')
        if ft in ('int', 'long'):
            try:
                return int(text_value)
            except ValueError:
                return text_value
        if ft in ('float', 'double'):
            try:
                return float(text_value)
            except ValueError:
                return text_value
        if ft == 'boolean':
            if text_value.lower() in ('true', '1', 'yes'):
                return True
            if text_value.lower() in ('false', '0', 'no'):
                return False
            return text_value
        return text_value

    def toggleCommandLineOptions(self):
        """
        Show or hide the 'Prefix', 'Value', 'Separate value and prefix', and 'Item Separator'
        widgets based on the 'Include in command line' checkbox state and Array Handling options.
        """
        # For InputParameter type, these widgets don't exist, so skip
        is_input_parameter = self.input_parameter_type in ['InputParameter', 'WorkflowInputParameter']
        if is_input_parameter:
            return
        
        data_type = self.data_type_combobox.currentText()
        
        # For record dependent arguments or record mutually exclusive arguments:
        # Automatically uncheck "Include in command line" checkbox
        # is_special_record_type = data_type in ["record dependent arguments", "record mutually exclusive arguments"]
        # if is_special_record_type:
        #     self.command_line_checkbox.setChecked(False)
        
        is_checked = self.command_line_checkbox.isChecked()

        # Show/hide 'Prefix', 'Value', 'Separate value and prefix' based on 'Include in command line'
        self.prefix_label.setVisible(is_checked)
        self.prefix_input.setVisible(is_checked)
        self.code_button.setVisible(is_checked)
        self.separate_value_prefix_checkbox.setVisible(is_checked)
        # For record types, show read-only summary; hide scalar default
        if data_type == 'record':
            self.defaultvalue_label.setVisible(False)
            self.defaultvalue_input.setVisible(False)
            self.record_default_widget.setVisible(True)
        elif self.input_parameter_type == 'CommandInputRecordField':
            # For record fields, always show the default value widget
            self.defaultvalue_label.setVisible(True)
            self.defaultvalue_input.setVisible(True)
            self.record_default_widget.setVisible(False)
        else:
            self.defaultvalue_label.setVisible(is_checked)
            self.defaultvalue_input.setVisible(is_checked)
            self.record_default_widget.setVisible(False)
        self.position_label.setVisible(is_checked)
        self.position_input.setVisible(is_checked)  
        self.shellquote_checkbox.setVisible(is_checked)

        # Show/hide 'Item Separator' based on 'Include in command line' and Array Handling options
        if is_checked and data_type != "enum" and self.array_combobox.currentText() in ['Allow Array','Array Only']:
            self.item_separator_label.setVisible(True)
            self.item_separator_combobox.setVisible(True)
        else:
            self.item_separator_label.setVisible(False)
            self.item_separator_combobox.setVisible(False)
        
        # Make field_name_input visible only for enum types
        is_enum = data_type == "enum"
        
        self.field_name_label.setVisible(is_enum or self.input_parameter_type == 'CommandInputRecordField')
        self.field_name_input.setVisible(is_enum or self.input_parameter_type == 'CommandInputRecordField')
            


    def setDefaults(self):
        '''
        set the default values in the widgets
        The input follows the CommandInputParameter
        # https://www.commonwl.org/v1.2/CommandLineTool.html#CommandInputParameter
        it also needs the

        data: Any the CommandinputParameter to show
        '''
        self.logger.debug(f"InputDialog received {type(self.input_parameter)} {save(self.input_parameter)}")
        self.input_parameter_type= type(self.input_parameter).__name__ 
        if self.input_parameter_type not in [
                    'CommandInputParameter',
                    'CommandInputRecordField',
                    'WorkflowInputParameter',
                    'InputParameter'
                ]:
            raise ValueError(f"Expected one of CommandInputParameter, CommandInputRecordField, WorkflowInputParameter, InputParameter, got {type(self.input_parameter).__name__}")

        if hasattr(self.input_parameter, 'id') and self.input_parameter.id:
            self.id_input.setText( self.input_parameter.id.split('#')[-1].split('/')[-1] )
        if hasattr( self.input_parameter, 'label'):
            self.label_input.setText(self.input_parameter.label )
        if hasattr( self.input_parameter, 'loadcontents' ):
            self.load_content_checkbox.setChecked( self.input_parameter.loadContents)
        if hasattr( self.input_parameter, 'doc'):
            self.description_input.setText(self.input_parameter.doc) 

        


        required=not  is_optional(self.input_parameter) 
        self.required_checkbox.setChecked(required)
        if not required:
            try:
                self.input_parameter.type_.remove('null')
            except ValueError:
                pass

        # set the data type
        # for now keep only the first type if an array
        # if not isinstance(self.data.get('type',[]), list):
        #     self.logger.critical(f"Type is not a list {self.data.get('type')}")
        #     sys.exit(23)
        single_item=False
        array_optional=is_optional_array(self.input_parameter)
        array_item=is_array( self.input_parameter )


        if array_optional and not array_item:
            self.array_combobox.setCurrentText('Allow Array')
        elif array_item:
            self.array_combobox.setCurrentText('Array Only')
        else:
            self.array_combobox.setCurrentText('Single Item')
      
            
        # self.logger.debug(f"Setting type {type_single_array[0]}")
        # sys.exit(55) # stop here  -> need to get the type_ and set it
        input_type=get_type( self.input_parameter,result=[]) 
        self.logger.debug(f"Setting data type '{input_type}'")

        # show the 
        self.field_name_label.setVisible('enum' in input_type or self.input_parameter_type == 'CommandInputRecordField')
        self.field_name_input.setVisible('enum' in input_type or self.input_parameter_type == 'CommandInputRecordField')


        try:
            input_type.remove('array')
        except ValueError:
            pass
        if hasattr( self.input_parameter, 'name'):
            self.field_name_input.setText( self.input_parameter.name)
        
        # get the tags for an enum
        if (isinstance(input_type, list) and 'enum' in input_type) or \
            input_type == 'enum':
            enum_fields = []
            field_name = ''
            if self.input_parameter.type_ == 'enum':
                enum_fields = self.input_parameter.symbols if hasattr(self.input_parameter, 'symbols') else []
                if hasattr(self.input_parameter, 'name'):
                    field_name = self.input_parameter.name
            elif hasattr(self.input_parameter.type_, 'type_') and self.input_parameter.type_.type_ == 'enum':
                enum_fields = self.input_parameter.type_.symbols if hasattr(self.input_parameter.type_, 'symbols') else []
                if hasattr(self.input_parameter.type_, 'name'):
                    field_name = self.input_parameter.type_.name
            elif isinstance(self.input_parameter , list):
                for e in self.input_parameter:
                    if hasattr(e, 'type_') and e.type_ == 'enum':
                        enum_fields = e.symbols if hasattr(e, 'symbols') else []
                        if hasattr(e, 'name'):
                            field_name = e.name
                        break
            elif isinstance(self.input_parameter.type_ , list):
                for e in self.input_parameter.type_:
                    if hasattr(e, 'type_') and e.type_ == 'enum':
                        enum_fields = e.symbols if hasattr(e, 'symbols') else []
                        if hasattr(e, 'name'):
                            field_name = e.name
                        break
            if field_name:
                self.field_name_input.setText(field_name.split('#')[-1].split('/')[-1])
            if enum_fields:
                enum_fields=[ y.split("/")[-1] for y in [ x.split('#')[-1] for x in enum_fields ] ]
            self.logger.debug(f"We have an enum type {input_type} with fields {enum_fields}")
        # get the information for a record
        if 'record' in input_type or input_type == 'record':
            self.logger.debug(f"Record id { self.input_parameter.id.split('#')[-1]}")
            input_type='record'
        # Record field handling is now removed
            

        if isinstance(input_type, list) and len(input_type)>1:
            raise Exception(f"input type {input_type} is a list with many elements {len(input_type)}")
        
        self.data_type_combobox.setCurrentText( input_type[0] if isinstance(input_type, list) else input_type)
        self.logger.debug(f"Setting type to { self.data_type_combobox.currentText()}")
        self.onDataTypeChanged()
        # We need to add the enum_fields after the tag widget has been enabled
        try:
            if enum_fields:
                self.enum_table_widget.setTags( enum_fields )
        except UnboundLocalError: # we don't have enum
            pass
        # Record field handling is now removed

        if hasattr(self.input_parameter, 'default') and self.input_parameter.default is not None:
            if isinstance(self.input_parameter.default, dict):
                # Determine if this is an exclusive or dependent record
                is_exclusive = (
                    'class' in self.input_parameter.default
                    and hasattr(self.input_parameter, 'type_')
                    and isinstance(self.input_parameter.type_, list)
                )
                if is_exclusive:
                    # Exclusive record: extract record names and field types from each schema
                    field_names = []
                    field_types = {}
                    for schema in self.input_parameter.type_:
                        if hasattr(schema, 'name') and schema.name:
                            schema_name = schema.name.split('#')[-1].split('/')[-1]
                            field_names.append(schema_name)
                            if hasattr(schema, 'fields') and schema.fields:
                                child = schema.fields[0]
                                child_type = get_type(child, result=[])
                                if isinstance(child_type, list):
                                    try:
                                        child_type.remove('array')
                                    except ValueError:
                                        pass
                                    child_type = child_type[0] if child_type else ''
                                field_types[schema_name] = child_type
                    if not field_names:
                        field_names = [k for k in self.input_parameter.default.keys() if k != 'class']
                    self.updateRecordDefaultFields(field_names, self.input_parameter.default, record_type='exclusive', field_types=field_types)
                    if hasattr(self, 'record_type_list_widget') and self.record_type_list_widget:
                        self.record_type_list_widget.setCurrentText('mutually exclusive')
                    logger.debug(f"Setting exclusive record default summary '{self.input_parameter.default}'")
                else:
                    # Dependent record: show all fields and their defaults
                    field_names = []
                    field_types = {}
                    if hasattr(self.input_parameter, 'type_') and hasattr(self.input_parameter.type_, 'fields') and self.input_parameter.type_.fields:
                        for f in self.input_parameter.type_.fields:
                            fname = f.name.split('#')[-1].split('/')[-1] if hasattr(f, 'name') and f.name else ''
                            field_names.append(fname)
                            if fname:
                                ft = get_type(f, result=[])
                                if isinstance(ft, list):
                                    try:
                                        ft.remove('array')
                                    except ValueError:
                                        pass
                                    ft = ft[0] if ft else ''
                                field_types[fname] = ft
                    if not field_names:
                        field_names = list(self.input_parameter.default.keys())
                    self.updateRecordDefaultFields(field_names, self.input_parameter.default, record_type='dependent', field_types=field_types)
                    logger.debug(f"Setting dependent record default summary '{self.input_parameter.default}'")
                self.record_default_widget.setVisible(True)
            else:
                self.defaultvalue_input.setText(str(self.input_parameter.default))
                logger.debug(f"Setting default value '{self.input_parameter.default}'")

        # For CommandInputRecordField, check for _field_default (set by parent record)
        if hasattr(self.input_parameter, '_field_default') and self.input_parameter._field_default is not None:
            self.defaultvalue_input.setText(str(self.input_parameter._field_default))
            self.defaultvalue_label.setVisible(True)
            self.defaultvalue_input.setVisible(True)
            logger.debug(f"Setting field default value '{self.input_parameter._field_default}'")

        # The binding edited here is the parameter's own one, or, when it has
        # none, the one an enum/record type carries. The binding of array
        # items stays as it is (and is put back by getData).
        own_binding = getattr(self.input_parameter, 'inputBinding', None)
        schema = _mainSchema(getattr(self.input_parameter, 'type_', None))
        if getattr(schema, 'type_', None) == 'array':
            self._item_binding = getattr(schema, 'inputBinding', None)
        elif own_binding is None:
            self._type_binding = getattr(schema, 'inputBinding', None)
        self._original_binding = own_binding or self._type_binding
        inputBindings = [self._original_binding] if self._original_binding is not None else []

        if len(inputBindings) > 0:
            if hasattr(self, 'command_line_checkbox'):
                self.command_line_checkbox.setChecked(True)
            self.order=0
            for inputBinding in inputBindings:
                logger.debug(f"InputBinding {save(inputBinding)}")
                self.prefix_input.setText(getattr(inputBinding, 'prefix', None) or '')
                self.value_input.setText(getattr(inputBinding, 'valueFrom', None) or '')
                
                item_separator = getattr(inputBinding, 'itemSeparator', None)
                if item_separator is not None:
                    if item_separator == ' ':
                        item_separator = 'space'
                    elif item_separator not in [',',';',':','-','/']:
                        item_separator = 'other'
                    self.item_separator_combobox.setCurrentText(item_separator)
                # CWL separates prefix and value unless separate is explicitly false
                self.separate_value_prefix_checkbox.setChecked(
                    getattr(inputBinding, 'separate', None) is not False)
                if hasattr(inputBinding,'shellQuote'):
                    self.shellquote_checkbox.setChecked(bool(inputBinding.shellQuote))
                else:
                    self.shellquote_checkbox.setChecked(False)

                if hasattr(inputBinding,'position'):
                    self.order=inputBinding.position
            self.position_input.setText( str(self.order or 0))
        else:
            if hasattr(self, 'command_line_checkbox'):
                self.command_line_checkbox.setChecked(False)
        self.description_input.setText( self.input_parameter.doc  or '')
        # (type_of_item, list_of_items)=CWLdataType( self.data )
        # if  'enum' in type_of_item:
        #     idx=type_of_item.index('enum')
        #     self.enum_table_widget.setTags( list_of_items[idx] )
            
        if hasattr(self.input_parameter,'format') and self.input_parameter.format and hasattr(self,'file_type_list_widget'):
            # self.file_type_list_widget.setTags( self.input_parameter.format)
            self.file_type_list_widget.populateFromCWL( self.input_parameter.format)
        
        if hasattr(self.input_parameter,'secondaryFiles') and self.input_parameter.secondaryFiles:
            self.secondary_files_input.populateFromCWL( self.input_parameter.secondaryFiles)
        if hasattr(self.input_parameter,'streamable') and self.input_parameter.streamable:
            self.streamable_checkbox.setChecked( self.input_parameter.streamable or False)

        # Record field handling has been removed
        #     if self.data.get('record').get('record_type') == 'exclusive':
        #         if hasattr(self, 'record_mutually_exclusive'):
        #             self.record_mutually_exclusive.setChecked(True)
        #     self.record_name.setText(self.data.get('record').get('name'))
        #     self.record_name.setVisible(True)
            # Set data for inputs group widget if available

        



    def onCodeEditor(self, widget_to_update=None):

         # Show the dialog
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.cwl_dict=self.input_parameter
        if self.value_input.text():
            dialog.editor.setText( self.value_input.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            self.code = dialog.get_javascript_code()
            # print("JavaScript code submitted:", code)
            if self.code:
                widget_to_update.setText( self.code)
                self.codeUpdated.emit()
            



# added this function here only for testing purposes.
# This function should be a copy of the same function
# in the qInputs.py
    def _editedBinding(self, module, position: int):
        """
        The binding from the dialog's fields, starting from the binding that
        was loaded: a field the user left as it was keeps its original value,
        so unset values (separate, shellQuote, itemSeparator, position) are
        not written out with defaults that would change what the tool does.
        """
        original = self._original_binding

        def kept(name, value, unset_value):
            before = getattr(original, name, None) if original is not None else None
            return None if before is None and value == unset_value else value

        separator_choice = self.item_separator_combobox.currentText()
        original_separator = getattr(original, 'itemSeparator', None) if original is not None else None
        if separator_choice == 'space':
            item_separator = ' ' if original_separator == ' ' else None
        elif separator_choice == 'other':
            item_separator = original_separator
        else:
            item_separator = separator_choice
        binding = module.CommandLineBinding(
            prefix=self.prefix_input.text() or None,
            separate=kept('separate', self.separate_value_prefix_checkbox.isChecked(), True),
            shellQuote=kept('shellQuote', self.shellquote_checkbox.isChecked(), False),
            itemSeparator=item_separator,
            position=kept('position', position, 0),
            valueFrom=self.value_input.text() or None,
        )
        # what the dialog does not edit (e.g. loadContents) is kept
        if original is not None and getattr(original, 'loadContents', None) is not None:
            binding.loadContents = original.loadContents
        return binding

    def getData( self) -> Any:
        """
        Create CWL CommandInputParameter object from
        the content of the Widgets in the dialog.
        
        Args:
            cwl_dict: Dictionary with argument properties
            
        Returns:
            A CWL CommandInputParameter object
            or a 
            tuple (CommandInputRecordSchema , record-name, record-type) where 
            the recor_id corresponds to the record that the input will be added
            the record_type can be dependent or mutual 

        """

        # Get the appropriate CWL module
        module = get_cwl_module(self.cwl_version) 
        
        
        position = 0
        try:
            if hasattr(self, 'position_input'):
                position = int(self.position_input.text())
        except ValueError:
            self.logger.warning(
                f"Invalid position value: {self.position_input.text()}, using 0"
            )
        # Create a CommandLineBinding object
        input_type=self.data_type_combobox.currentText()
        array_type=self.array_combobox.currentText()

        if input_type == 'enum':
            input_type=module.CommandInputEnumSchema(
                type_='enum',
                symbols=self.enum_table_widget.getTags(),
                name=self.field_name_input.text()
            )

        # handle array
        if array_type == 'Array Only':
            self.logger.debug("Preparing the input type as CommandInputArraySchema due to Array Only")
            input_type=module.CommandInputArraySchema(
                items=input_type,
                type_='array'
            )
        if array_type == 'Allow Array':
            self.logger.debug("Preparing the input type as null/CommandInputArraySchema due to Allow Array")
            input_type=[
                input_type,
                module.CommandInputArraySchema(
                    items=input_type,
                    type_='array'
                )
            ]
        
        if self.data_type_combobox.currentText() == 'record' and self.record_type_list_widget.currentText() =='dependent':
            self.logger.debug("Preparing the input type as CommandInputRecordSchema due to dependent record")
            input_type= module.CommandInputRecordSchema(
                type_='record',
                fields=[]
            )
        if self.data_type_combobox.currentText() == 'record' and self.record_type_list_widget.currentText() =='mutually exclusive':
            self.logger.debug("Preparing the input type as CommandInputRecordSchema due to mutually exclusive record")
            input_type= [ module.CommandInputRecordSchema(  type_='record', fields=[])]
        # handle not required
        if self.required_checkbox.isChecked() is False:
            input_type=['null', input_type]
        binding=None
        if hasattr(self, 'command_line_checkbox') and self.command_line_checkbox.isChecked():
            self.logger.debug("Preparing the inputBinding")
            binding = self._editedBinding(module, position)
        # put the bindings that live on the type back where they were
        schemas = list(_schemas(input_type))
        # a record type keeps its name
        original_schema = _mainSchema(getattr(getattr(self, 'input_parameter', None), 'type_', None))
        if getattr(original_schema, 'type_', None) == 'record' and getattr(original_schema, 'name', None):
            for record_schema in [t for t in schemas if getattr(t, 'type_', None) == 'record']:
                # cwl_utils names new schemas "_:<uuid>"
                if str(getattr(record_schema, 'name', None) or '_:').startswith('_:'):
                    record_schema.name = original_schema.name
        if binding is not None and self._type_binding is not None:
            typed = [t for t in schemas if getattr(t, 'type_', None) in ('enum', 'record')]
            if typed:
                typed[0].inputBinding = binding
                binding = None
        if self._item_binding is not None:
            for array_schema in [t for t in schemas if getattr(t, 'type_', None) == 'array']:
                if getattr(array_schema, 'inputBinding', None) is None:
                    array_schema.inputBinding = self._item_binding
        

        self.logger.debug(f"Input type {self.input_parameter_type} to return")
        # check the default 
        default=None
        if self.data_type_combobox.currentText() == 'record' and self.record_default_fields:
            if self.record_default_record_type == 'exclusive':
                # Collect exclusive default: {'class': selected, selected: value}
                selected_class = ''
                if hasattr(self, '_exclusive_class_combo'):
                    selected_class = self._exclusive_class_combo.currentText()
                if selected_class and selected_class in self.record_default_fields:
                    value = self._convertFieldDefault(
                        selected_class,
                        self.record_default_fields[selected_class].text()
                    )
                    if value is not None:
                        default = {'class': selected_class, selected_class: value}
            else:
                # Collect dependent defaults: {field_name: value}
                record_defaults = {}
                for field_name, line_edit in self.record_default_fields.items():
                    value = self._convertFieldDefault(field_name, line_edit.text())
                    if value is not None:
                        record_defaults[field_name] = value
                if record_defaults:
                    default = record_defaults
        elif (hasattr(self, 'defaultvalue_input') and 
            self.defaultvalue_input.text() ):
            default = self.defaultvalue_input.text().strip()
            it = self.data_type_combobox.currentText()
            array_mode = self.array_combobox.currentText() in ['Allow Array', 'Array Only']
            if array_mode and default.startswith('[') and default.endswith(']'):
                # Accept JSON-like bracket notation for array defaults.
                try:
                    parsed_default = json.loads(default)
                except Exception:
                    parsed_default = [v.strip() for v in default[1:-1].split(',') if v.strip()]
                if not isinstance(parsed_default, list):
                    parsed_default = [parsed_default]
                if it in {'int', 'long'}:
                    default = [int(v) for v in parsed_default]
                elif it in {'double', 'float'}:
                    default = [float(v) for v in parsed_default]
                else:
                    default = parsed_default
            elif it in {'int', 'long'}:
                default = int(default)
            elif it in {'double', 'float'}:
                # keep "10" an integer: a float input accepts it as it was written
                default = int(default) if re.fullmatch(r'[+-]?\d+', default) else float(default)


        # optional attributes are only written when set (no [] / false defaults)
        secondary_files = (self.secondary_files_input.getData() if self.secondary_files_input else None) or None
        streamable = None
        if self.streamable_checkbox is not None:
            streamable = True if self.streamable_checkbox.isChecked() else None
            if streamable is None and getattr(getattr(self, 'input_parameter', None), 'streamable', None) is False:
                streamable = False

        if self.input_parameter_type=='CommandInputParameter':
            inputparameter=module.CommandInputParameter(
                id=self.id_input.text(), # can be many input types
                label=self.label_input.text(),
                secondaryFiles=secondary_files,
                streamable=streamable, 
                doc=self.description_input.toPlainText(),
                inputBinding=binding,
                default=default,
                type_=input_type
            )
        elif self.input_parameter_type=='InputParameter':
            inputparameter=module.InputParameter(
                id=self.id_input.text(), # can be many input types
                label=self.label_input.text(),
                secondaryFiles=secondary_files,
                streamable=streamable, 
                doc=self.description_input.toPlainText(),
                inputBinding=binding,
                default=default,
                type_=input_type
            )
        elif self.input_parameter_type=='CommandInputRecordField':
            inputparameter=module.CommandInputRecordField(
                label=self.label_input.text(),
                name= self.field_name_input.text(),
                secondaryFiles=secondary_files,
                streamable=streamable, 
                doc=self.description_input.toPlainText(),
                inputBinding=binding,
                type_=input_type
            )
            # Store field default as custom attribute for the parent record to collect
            if default is not None:
                inputparameter._field_default = default
        elif self.input_parameter_type=='WorkflowInputParameter':
            inputparameter=module.WorkflowInputParameter(
                id=self.id_input.text(), # can be many input types
                label=self.label_input.text(),
                secondaryFiles=secondary_files,
                streamable=streamable, 
                doc=self.description_input.toPlainText(),
                # inputBinding=binding,
                default=default,
                type_=input_type
            )
        else:
            raise ValueError(f"Unknown parameter type.")
        if self.file_type_list_widget and self.file_type_list_widget.getData():
            inputparameter.format=self.file_type_list_widget.getData()

        self.logger.debug(f"Dialog returns InputParameter {inputparameter}: {save(inputparameter)}")
       
        return (inputparameter)

if __name__ == '__main__':
    from cwl_utils_handler import CWLType,get_cwl_module
    from cwl_utils.parser import save
    from CWLparser import Parser
   
    # load the configuration
    conf=Configuration()
    conf.loadConfiguration( "commandLineWindow.yaml")#,"dataStructures.yaml"] )
    data.configuration=conf.getConfiguration()
    datatypes=Configuration()
    datatypes.loadConfiguration("dataStructures.yaml")
    data.datatypes=datatypes.getConfiguration()
    app = QApplication(sys.argv)


    # simple inputs
    # tests_dir=Path(__file__).resolve().parents[1] / "tests"
    # cwl_dict=Parser( str(tests_dir / "05-input.cwl")).getCWL()
    # array inputs
    # cwl_dict=Parser( str(tests_dir / "06-array-inputs.cwl")).getCWL()
    # enum inputs
    # cwl_dict=Parser( str(tests_dir / "08-exclusive-parameter-input.cwl")).getCWL()
    # records
    # cwl_dict=Parser( str(tests_dir / "07-record.cwl")).getCWL()
    
    # print(f"{json.dumps( save(cwl_dict), indent=3)}")
    

    # populate the inputDialog with the first 
    # record which is a dependent type
    # dialog = InputDialog( parent=app.activeWindow())
    # input=cwl_dict.inputs[0]
    # for dependent records get the fields
    # input=input.type_.fields[0]
    # for mutually exclusive records get the fields
    # rec_id=input.id
    # input=input.type_[0].fields[0]
    
    # print(f"Field {save(input)}")
    # # dialog.setDefaults( input , rec_id)
    # dialog.setDefaults(input)
    # if dialog.exec():
    #     cwl_dict=dialog.getData()
    #     print("Accepted")
    #     (inputparameter, record_name, record_type)=convertDictToCWL( cwl_dict )

    #     print(f"The inputparameters is {json.dumps( save(inputparameter), indent=3)}")
    #     print(f"Record {record_name}, of type {record_type}")
    #     sys.exit(0)
    # else:
    #     print("Rejected")
    #     run=False
    #     sys.exit(0)


    # retrieve new information

    run=True
    while run:
        dialog = InputDialog( parent=app.activeWindow()) 

        if dialog.exec():
            cwl_dict=dialog.getData()
            print("Accepted")
            
        else:
            print("Rejected")
            run=False
        print(f"===\n{json.dumps(cwl_dict,indent=3)}\n===")

        (inputparameter, record_name, record_type)=convertDictToCWL( cwl_dict )

        print(f"The inputparameters is {json.dumps( save(inputparameter), indent=3)}")
        print(f"Record {record_name}, of type {record_type}")
        

    sys.exit(0)
    sys.exit(app.exec())


