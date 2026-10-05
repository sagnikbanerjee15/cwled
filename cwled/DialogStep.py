from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QFontMetrics

import json
from copy import deepcopy
import sys
import builtins
import logging
from widgets.qButtons import *
from widgets.qDefaultValue import QDefaultValueGroupWidget,QDefaultValueWidget
from widgets.qConditionalInput import QConditionalInputsGroupWidget
from widgets.qSortedList import QSortList
from JavascriptEditor import JavaScriptEditorDialog
import data
import theme
import jinja2
from pathlib import Path
from typing import Optional, Any, Union,List
from cwl_utils.parser import save
from cwl_utils_handler import get_cwl_module, get_cwl_version
from ports import PortSplitter
from CWLparser import get_type, get_items, get_symbols
from BaseDialog import BaseDialog
logger = logging.getLogger(__name__)

# Define the step data structure
step = {
    'id': None,
    'label': None,
    'scatter': None,
    'scatterMethod': None,
    'doc': None,
    'when': None,
    'in': []  # List to store input configuration - matches the jinja2 template format
}

class InputRowWidget(QWidget):
    """Widget for displaying and editing a single input row in the StepDialog."""
    cwl_step:Any=None # this is the WorkflowStepInput object
    cwl_input:Any=None # this is the CWL input parameter object (Inputparameter or WorkflowInputParameter or CommandInputParameter)
    cwl_version:str=None
    
    editingFinished = pyqtSignal()
    
    def __init__(self, 
                 parent=None, 
                 cwl_step=None,
                 cwl_input=None,
                 cwl_version=None):
        super().__init__(parent)
        if type(cwl_step).__name__ != 'WorkflowStepInput':
            raise TypeError(f"Expected WorkflowStepInput, got {type(cwl_step).__name__}. Using empty step.")
        if type(cwl_input).__name__ not in ['InputParameter','WorkflowInputParameter','CommandInputParameter']:
            raise TypeError(f"Expected InputParameter, WorkflowInputParameter or CommandInputParameter, got {type(cwl_input).__name__}. Using empty input.")
        self.cwl_step = cwl_step
        self.cwl_input = cwl_input
        if cwl_step is not None and cwl_version is None:
            self.setCWLVersion(cwl_step)
        elif cwl_version is not None:
            self.setCWLVersion(cwl_version)
        else:
            raise ValueError("Either output_parameter or cwl_version must be provided.")
        self.initUI()
        
    def setCWLVersion(self, cwl_version: Union[Any, str]):
        """Set the CWL version for this widget."""
        if not isinstance(cwl_version, str):
            self.cwl_version = get_cwl_version(cwl_version)
        else:
            self.cwl_version = cwl_version

    def initUI(self):
        # Main layout for this widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(5)
        logger.debug(f"Adding input row for: {save(self.cwl_step)}")
        logger.debug(f"With CWL input {save(self.cwl_input)}")
        # Top row with name and type
        top_row = QVBoxLayout()
        
        # Create horizontal layout for id_label and info icon
        id_row = QHBoxLayout()
        
        # Input display name (id)
        self.id_label = QLabel(self.cwl_step.id.split('#')[-1])  # Use the last part after '#'
        test_split=self.cwl_step.id.split("#")
        if len( test_split ) >1:
            self.filename_prefix=test_split[0]
        else:
            self.filename_prefix=None
        self.id_label.setStyleSheet("font-weight: bold;")
        self.id_label.setMinimumWidth(150)
        
        # Add info icon next to id_label
        self.info_icon = QLabel()
        theme.setLabelIcon(self.info_icon, theme.icon('info'), 16)
        
        # Set tooltip based on cwl_step.doc value
        if hasattr(self.cwl_step, 'doc') and self.cwl_step.doc:
            self.info_icon.setToolTip(self.cwl_step.doc)
        elif hasattr(self.cwl_input, 'doc') and self.cwl_input.doc:
            self.info_icon.setToolTip(self.cwl_input.doc)
        else:
            self.info_icon.setToolTip("No documentation available for this input")
        
        id_row.addWidget(self.id_label)
        id_row.addWidget(self.info_icon)
        id_row.addStretch()
        
        # Input display name (from label or id)
        lbl=None
        if hasattr(self.cwl_step, 'label') and self.cwl_step.label:
            lbl=self.cwl_step.label

        self.name_label = QLabel(lbl)
        self.name_label.setStyleSheet("font-weight: bold;")
        self.name_label.setMinimumWidth(150)
        
        # Input type label (read-only)
        # self.type_label = QLabel(f"Type: {self.input_type}")
        # self.type_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #cccccc; border-radius: 2px; padding: 2px;")
        top_row.addLayout(id_row)
        # top_row.addWidget(self.type_label)  # Uncomment if type is needed
        if lbl:
            top_row.addWidget(self.name_label)
        # top_row.addWidget(self.type_label)
        top_row.addStretch()
        
        # Middle row with default value
        
        t=get_type( self.cwl_input) # returns all types except null
        if len(t)>1:
            if 'array' in t:
                t.remove('array')
            elif 'record' in t:
                t = ['record']
            else:
                raise NotImplementedError(f"Default values for multiple types {t} are not supported.")
        t=set(t).pop()
        # print(f"Got type {t} \n\n\n")
        # add default values for all inputs except Files and Directories
        middle_row=None
        self.is_record = False
        if t in ['File','Directory']:
            # print(f"\n\nSkipping line for File\n\n")
            pass
        elif t == 'record':
            # Handle record type: break down into individual field widgets
            record_fields = self._get_record_fields()
            if record_fields:
                self.is_record = True
                self.field_widgets = {}

                record_group = QGroupBox("Record Fields")
                record_group.setStyleSheet(
                    f"QGroupBox {{ border: 1px solid {theme.BLACK}; border-radius: 2px; "
                    "margin-top: 8px; padding-top: 12px; } "
                    "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
                )
                record_layout = QVBoxLayout()

                for field in record_fields:
                    field_name = field.name if hasattr(field, 'name') else str(field)
                    field_types = get_type(field)
                    field_type = field_types[0] if field_types else 'string'

                    # Skip File/Directory fields
                    if field_type in ['File', 'Directory']:
                        continue

                    field_row = QHBoxLayout()
                    field_label = QLabel(f"{field_name}:")
                    field_label.setMinimumWidth(100)

                    # Get default value for this field from the step default dict
                    default_val = None
                    if isinstance(self.cwl_step.default, dict) and field_name in self.cwl_step.default:
                        default_val = self.cwl_step.default[field_name]

                    symbols = None
                    if field_type == 'enum' and hasattr(field, 'type_'):
                        (symbols, _) = get_symbols(field)
                        symbols = [PortSplitter(x, self.parent().workflow_id).port_id for x in symbols]

                    field_widget = QDefaultValueWidget(
                        default_value=default_val,
                        array=False,
                        input_type=field_type,
                        enum_list=symbols if field_type == 'enum' else None,
                        parent=self
                    )
                    field_widget.editingFinished.connect(self.editingFinished.emit)

                    field_row.addWidget(field_label)
                    field_row.addWidget(field_widget)
                    record_layout.addLayout(field_row)

                    self.field_widgets[field_name] = field_widget

                record_group.setLayout(record_layout)
                middle_row = QHBoxLayout()
                middle_row.addWidget(record_group)
        else:
            middle_row = QHBoxLayout()
            symbols=None
            if t=='enum' :
                (symbols,field_name)=get_symbols(self.cwl_input)
                symbols=[PortSplitter(x, self.parent().workflow_id).port_id  for x in symbols]
            # print(f"Creating Default widget with value {self.cwl_step.default} ")
            # print(f"for type {t} (as array:{isinstance(self.cwl_step.default,list)}) and items {symbols if symbols else None}")
            if isinstance(self.cwl_step.default,list):
                self.default_input = QDefaultValueGroupWidget( 
                    default_value=self.cwl_step.default, 
                    array= True,
                    input_type=t,
                    enum_list=symbols if t=='enum' else None,
                    parent=self
                )
            else:
                self.default_input = QDefaultValueWidget( 
                    default_value=self.cwl_step.default, 
                    array= False,
                    input_type=t,
                    enum_list=symbols if t=='enum' else None,
                    parent=self
                )
            self.default_input.editingFinished.connect(self.editingFinished.emit)
            # self.code_button = QCodeButton()
            # self.code_button.clicked.connect(self.openJavaScriptEditor)
            
            middle_row.addWidget(self.default_input)
        # middle_row.addWidget(self.code_button)
        
        # Bottom row with link merge and pick value options
        bottom_row = QHBoxLayout()
        self.link_merge_label = QLabel("Link Merge:")
        self.link_merge_combobox = QComboBox()
        self.link_merge_combobox.addItems(["-- None --","merge_nested", "merge_flattened"])
        
        # Add pickValue field for CWL v1.2
        self.pick_value_label = QLabel("Pick Value:")
        self.pick_value_combobox = QComboBox()
        self.pick_value_combobox.addItems(["-- None --", "first_non_null", "the_only_non_null", "all_non_null"])
        self.pick_value_combobox.setToolTip("Specifies how to pick non-null values among inbound data links")
        self.pick_value_combobox.currentTextChanged.connect(
            self.onPickValueChanged
        )
        
        bottom_row.addWidget(self.link_merge_label)
        bottom_row.addWidget(self.link_merge_combobox)
        bottom_row.addWidget(self.pick_value_label)
        bottom_row.addWidget(self.pick_value_combobox)
        bottom_row.addStretch()
        
        # Add all rows to main layout
        layout.addLayout(top_row)
        if middle_row:
            layout.addLayout(middle_row)
        layout.addLayout(bottom_row)

        self.pick_sort_widget = None
        self.pick_sort_container = QVBoxLayout()
        self.pick_sort_container.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.pick_sort_container)

        self._update_pick_sort_widget_visibility()
        
        # Add a separator line at the bottom
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(f"color: {theme.BLACK};")
        layout.addWidget(line)
        
        self.setLayout(layout)

    def _get_source_values_for_sort(self) -> List[str]:
        source_values = []
        if not hasattr(self.cwl_step, 'source'):
            source = None
        else:
            source = self.cwl_step.source

        if source is not None:
            if isinstance(source, list):
                source_values = [str(item) for item in source]
            else:
                source_values = [str(source)]
            return source_values

        parent_step = getattr(self.parent(), 'cwl_step', None)
        if parent_step is not None and hasattr(parent_step, 'in_'):
            for in_item in parent_step.in_:
                if hasattr(in_item, 'id'):
                    source_values.append(str(in_item.id))
                else:
                    source_values.append(str(in_item))
        return source_values

    def _remove_pick_sort_widget(self):
        if self.pick_sort_widget is None:
            return
        self.pick_sort_widget.setParent(None)
        self.pick_sort_widget.deleteLater()
        self.pick_sort_widget = None

    def _show_pick_sort_widget(self):
        values = self._get_source_values_for_sort()
        if not values:
            self._remove_pick_sort_widget()
            return

        if self.pick_sort_widget is None:
            self.pick_sort_widget = QSortList(
                parent=self,
                cwl_tool=values,
                cwl_version=self.cwl_version,
            )
            self.pick_sort_widget.editingFinished.connect(
                self.editingFinished.emit
            )
            self.pick_sort_container.addWidget(self.pick_sort_widget)
        else:
            self.pick_sort_widget.populateFromCWL(values)

    def _update_pick_sort_widget_visibility(self):
        has_pick_attr = hasattr(self.cwl_step, 'pickValue')
        pick_value = self.pick_value_combobox.currentText()
        is_defined = pick_value and pick_value != "-- None --"

        if has_pick_attr and is_defined:
            self._show_pick_sort_widget()
            return
        self._remove_pick_sort_widget()

    @pyqtSlot(str)
    def onPickValueChanged(self, _: str):
        self._update_pick_sort_widget_visibility()
        self.editingFinished.emit()
        
    def openJavaScriptEditor(self):
        # Show the JavaScript editor dialog
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.cwl_dict = self.cwl_step
        
        # Get the current text from the default input widget
        current_text = self.default_input.text()
        if current_text:
            dialog.editor.setText(current_text)
            
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            code = dialog.get_javascript_code()
            if code:
                self.default_input.setText(code)
    
    def _get_record_fields(self):
        """Extract record fields from the cwl_input parameter.
        
        Handles both dependent records (single record with multiple fields)
        and exclusive records (union of multiple record types).
        
        Returns:
            list: List of field objects from the record type(s)
        """
        fields = []
        type_ = self.cwl_input.type_ if hasattr(self.cwl_input, 'type_') else self.cwl_input

        if isinstance(type_, list):
            for t in type_:
                if t != 'null' and hasattr(t, 'fields') and t.fields:
                    fields.extend(t.fields)
        elif hasattr(type_, 'fields') and type_.fields:
            fields.extend(type_.fields)

        return fields

    def getData(self):
        """Return the input configuration as a dictionary."""

        module = get_cwl_module(self.cwl_version)
        data = module.WorkflowStepInput(
            id=f"{self.filename_prefix}#{self.id_label.text()}" if self.filename_prefix else self.id_label.text(),
            source=self.cwl_step.source
        )
        if self.is_record and hasattr(self, 'field_widgets'):
            record_data = {}
            for field_name, field_widget in self.field_widgets.items():
                val = field_widget.getData()
                if val is not None:
                    record_data[field_name] = val
            if record_data:
                data.default = record_data
        elif hasattr(self, 'default_input'):
            if self.default_input.getData():
                data.default=self.default_input.getData()
        if self.link_merge_combobox.currentText() != "-- None --":
            data.linkMerge=self.link_merge_combobox.currentText()

        if self.pick_value_combobox.currentText() != "-- None --":
            data.pickValue = self.pick_value_combobox.currentText()

        if self.pick_sort_widget is not None and hasattr(data, 'source'):
            ordered_sources = self.pick_sort_widget.getData()
            if isinstance(self.cwl_step.source, list):
                data.source = ordered_sources
            elif len(ordered_sources) == 1:
                data.source = ordered_sources[0]
            elif ordered_sources:
                data.source = ordered_sources
        if hasattr( data, 'label'):
            data.label=self.name_label.text()


        return data

class StepDialog(BaseDialog):
    """A dialog that collects user input for workflow step information."""
    code = ''
    codeUpdated = pyqtSignal()  # emit this signal when the code is updated
    cwl_step:Any=None # The CWL step dictionary to edit
    cwl_step_inputs:List[Any]=[] # List of CWL input parameter objects available for this step i.e. cwl_tool.inputs 
    cwl_version:str=None  # The CWL version for this step
    workflow_id:str=None
    parent_obj=None # parent object. Needed if we have to traverse the object hierarchy
    def __init__(self, 
                 cwl_step:Optional[Any]=None, 
                 cwl_tool:Optional[Any]=None,
                 cwl_step_inputs:Optional[List[Any]]=None,
                 cwl_version:Optional[str]=None,
                 workflow_id:Optional[str]=None,
                 parent=None):
        if not isinstance(parent, QWidget):
            parent=None
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(__name__, 'DEBUG'))
        
        
        # Set the dialog title
        self.setWindowTitle("Edit Step")
        # Initialize with a deep copy of the step structure
        
        self.input_widgets = {}  # Dictionary to store input widgets
        self.available_inputs = []  # List to store available input IDs
        if type(cwl_step).__name__ != 'WorkflowStep':
            raise TypeError(f"Expected WorkflowStep, got {type(cwl_step).__name__}. Using empty step.")
        
        self.cwl_step_inputs=cwl_step_inputs
        self.setCWL(cwl_step)

        if cwl_step is not None and cwl_version is None:
            self.setCWLversion(cwl_step)
        elif cwl_version is not None:
            self.setCWLversion(cwl_version)
        else:   
            raise ValueError("Either output_parameter or cwl_version must be provided.")
        if workflow_id:
            self.workflow_id=workflow_id
        else:
            raise ValueError("workflow_id must be provided.")

        # print(f"Initializing StepDialog with step: {json.dumps(save(self.cwl_step), indent=2)}")
        # print(f"the input steps are: {[save(inp) for inp in self.cwl_step_inputs]}")
        # print(f"CWL version: {self.cwl_version}")
        # sys.exit(123)
        self.initUI()
    

    def setCWL(self, 
               cwl_step:Optional[Any]):
        if type(cwl_step).__name__ != 'WorkflowStep':
            raise TypeError(f"Expected WorkflowStep, got {type(cwl_step).__name__}. Using empty step.")
        self.cwl_step = cwl_step


    def setCWLversion(self, cwl_version: Union[Any, str]):
        """Set the CWL version for this widget."""
        if not isinstance(cwl_version, str):
            self.cwl_version = get_cwl_version(cwl_version)
        else:
            self.cwl_version = cwl_version

    def initUI(self):
        # Main layout for the dialog
        self.layout = QVBoxLayout(self)
        
        # Create a scroll area
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # ID input
        self.id_label = QLabel("ID:")
        self.id_input = QLineEdit(self)
        self.id_input.setPlaceholderText("Enter ID")
        
        # Label input
        self.label_label = QLabel("Label:")
        self.label_input = QLineEdit(self)
        self.label_input.setPlaceholderText("Enter Label")
        
        # Scatter input with selection of available inputs
        self.scatter_label = QLabel("Scatter:")
        self.scatter_group = QGroupBox("Select inputs to scatter over")
        self.scatter_layout = QVBoxLayout(self.scatter_group)
        self.scatter_checkboxes = {}  # To store checkboxes for each input
        
        # Create "None" checkbox as the default option
        # self.scatter_none_checkbox = QCheckBox("None")
        # self.scatter_none_checkbox.setChecked(True)
        # self.scatter_none_checkbox.stateChanged.connect(self.onNoneCheckboxChanged)
        # self.scatter_layout.addWidget(self.scatter_none_checkbox)
        
        # Add a scrollable area for checkboxes if there are many inputs
        self.scatter_scroll = QScrollArea()
        self.scatter_scroll.setWidgetResizable(True)
        self.scatter_scroll_content = QWidget()
        self.scatter_scroll_layout = QVBoxLayout(self.scatter_scroll_content)
        self.scatter_scroll.setWidget(self.scatter_scroll_content)
        self.scatter_scroll.setMaximumHeight(150)  # Limit height
        self.scatter_layout.addWidget(self.scatter_scroll)
        
        # Scatter Method input
        self.scatter_method_label = QLabel("Scatter Method:")
        self.scatter_method_combobox = QComboBox(self)
        self.scatter_method_combobox.addItems(["dotproduct", "nested_crossproduct", "flat_crossproduct"])
        
        # When input (with JavaScript editor)
        self.when_container = QWidget()
        self.when_label = QLabel("When:")
        self.when_input = QLineEdit(self)
        self.when_input.setPlaceholderText("Enter condition expression")
        self.when_code_button = QCodeButton()
        self.when_code_button.clicked.connect(lambda: self.onCodeEditor(self.when_input))
        
        self.when_layout = QHBoxLayout(self.when_container)
        self.when_layout.setContentsMargins(0, 0, 0, 0)
        self.when_layout.addWidget(self.when_label)
        # the </> button is attached to the field (Composer input group)
        self.when_layout.addWidget(theme.InputGroup(self.when_input, self.when_code_button, parent=self))
        
        # Documentation input
        self.doc_label = QLabel("Documentation:")
        self.doc_input = QTextEdit(self)
        self.doc_input.setPlaceholderText("Enter documentation for this step")
        
        # Inputs section header
        inputs_header = QLabel("Step Inputs")
        inputs_header.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        
        # Container for input widgets
        self.inputs_container = QWidget()
        self.inputs_layout = QVBoxLayout(self.inputs_container)
        self.inputs_layout.setContentsMargins(0, 0, 0, 0)
        self.inputs_layout.setSpacing(5)
        
        # Conditional inputs group widget
        self.conditional_inputs_widget = QConditionalInputsGroupWidget(
            parent=self,
            cwl_version=self.cwl_version
        )
        self.conditional_inputs_widget.setVisible(False)  # Hidden by default
        
        # Add widgets to the layout
        scroll_layout.addWidget(self.id_label)
        scroll_layout.addWidget(self.id_input)
        
        scroll_layout.addWidget(self.label_label)
        scroll_layout.addWidget(self.label_input)
        
        scroll_layout.addWidget(self.scatter_label)
        scroll_layout.addWidget(self.scatter_group)
        
        scroll_layout.addWidget(self.scatter_method_label)
        scroll_layout.addWidget(self.scatter_method_combobox)
        
        
        scroll_layout.addWidget(self.when_container)
        
        # Add conditional inputs section (right after when)
        scroll_layout.addWidget(self.conditional_inputs_widget)
        
        scroll_layout.addWidget(self.doc_label)
        scroll_layout.addWidget(self.doc_input)
        
        # Add inputs section
        scroll_layout.addWidget(inputs_header)
        scroll_layout.addWidget(self.inputs_container)
        
        # Set up scroll area
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
    
    
    def set_scatter(self, value):
        """
        Set the scatter checkboxes based on the provided value.
        Value can be a string (single input) or a list of strings (multiple inputs).
        """
        # Convert single string to list for uniform handling
        if isinstance(value, str):
            value = [value]
        
        # If we have a valid list and not empty, uncheck 'None'
        if value and isinstance(value, list) and value[0]:
            # self.scatter_none_checkbox.setChecked(False)
            
            # Check the matching checkboxes
            for input_id in value:
                if input_id in self.scatter_checkboxes:
                    self.scatter_checkboxes[input_id].setChecked(True)
        else:
            # If no valid scatter, check 'None'
            # self.scatter_none_checkbox.setChecked(True)
            pass
    
    def set_scatter_method(self, value):
        if value and value in ["dotproduct", "nested_crossproduct", "flat_crossproduct"]:
            self.scatter_method_combobox.setCurrentText(value)
    
    
    def update_scatter_options(self):
        """Update the scatter checkbox options based on available inputs"""
        # Clear existing checkboxes
        for widget in self.scatter_checkboxes.values():
            widget.setParent(None)
        self.scatter_checkboxes = {}
        
        # Clear the scroll layout
        while self.scatter_scroll_layout.count():
            item = self.scatter_scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Add new checkboxes for each available input
        for input_id in self.cwl_step.in_:
            checkbox = QCheckBox(input_id.id.split('#')[-1])  # Use the last part after '#'
            # checkbox.stateChanged.connect(self.onInputCheckboxChanged)
            self.scatter_checkboxes[input_id.id] = checkbox
            self.scatter_scroll_layout.addWidget(checkbox)
        
        # If no inputs are available, disable the scatter group
        self.scatter_group.setEnabled(len(self.cwl_step.in_) > 0)
    
    def addInputWidget(self, input:Any=None):
        """Add a widget for an input to the inputs section."""
        # Use label if provided, otherwise use ID
        # display_label = input.label if input.label else input.id
        
        # Find the corresponding CWL input parameter object
        inp_port=PortSplitter(input.id, self.workflow_id)        
        inp=None
        for cwl_inp in self.cwl_step_inputs:
            cwl_inp_port=PortSplitter( cwl_inp.id , self.workflow_id)
            if cwl_inp_port.port_id == inp_port.port_id:
                inp=cwl_inp
                break
        
        # If no matching input parameter found, add as conditional input
        if inp is None:
            self.logger.info(f"No matching input parameter found for step input '{inp_port.port_id}'. Adding as conditional input.")
            self.conditional_inputs_widget.addWidget(cwl_data=input)
            self.conditional_inputs_widget.setVisible(True)
            return
        
        input_widget = InputRowWidget(parent=self,
                                      cwl_step=input,
                                      cwl_input=inp)
        
        # Set default values if provided
        if hasattr(input, 'default') and hasattr(input_widget, 'default_input'):
            input_widget.default_input.populateFromCWL()
        input_widget.link_merge_combobox.setCurrentText(input.linkMerge)
        if hasattr(input, 'pickValue'):
            input_widget.pick_value_combobox.setCurrentText(input.pickValue)
        
        self.inputs_layout.addWidget(input_widget)
        self.input_widgets[input.id] = input_widget
        
        # Add this input to available inputs for scatter
    


    def clearInputWidgets(self):
        """Remove all input widgets from the layout."""
        for input_id, widget in self.input_widgets.items():
            widget.setParent(None)
        self.input_widgets = {}
        
        # Clear conditional inputs
        self.conditional_inputs_widget.clear()
        self.conditional_inputs_widget.setVisible(False)
        
        # Clear available inputs for scatter
        self.available_inputs = []
    
    def setInputs(self, inputs:Any=None):
        """
        Set up input widgets based on the available inputs.
        
        Args:
            inputs: List of inputs to add to the ui. This is coming from the .in_ of the WorkflowStep
            
        """
        self.clearInputWidgets()
        
        for input in inputs:
            self.addInputWidget(input)
        # Update scatter options after inputs are set
        self.update_scatter_options()
    
    def setDefaults(self):
        self.logger.debug(f"StepDialog received {type(self.cwl_step).__name__} {json.dumps(save(self.cwl_step), indent=3)}")
        
        test_split=self.cwl_step.id.split("#")
        if len( test_split ) >1:
            self.filename_prefix=test_split[0] 
        else:
            self.filename_prefix=None
        self.id_input.setText(self.cwl_step.id.split("#")[-1])  # Use the last part after '#'
        
        
        self.label_input.setText(self.cwl_step.label)
        
        # If the data contains input info, set up the input widgets
        # we want to get the union of the in_ and cwl_inputs 
        # this way we will include the active ins but also potential inputs that need to setup the default values.
        ids=[]
        self.clearInputWidgets()

        # if self.cwl_step.in_:
        #     self.setInputs(self.cwl_step.in_)
        for input in self.cwl_step.in_:
            id=PortSplitter( input.id, self.workflow_id).port_id
            self.addInputWidget(input)
            ids.append(id)
        # now go through the rest of the inputs. use only inputs that have not
        # been used before, and convert them to WorkflowStepInput in order to
        # work with the InputRowWidget
        for input in self.cwl_step_inputs:
            id=PortSplitter( input.id, self.workflow_id).port_id
            if id in ids: continue
            module=get_cwl_module( self.cwl_version )
            step=module.WorkflowStepInput( id=id, source=None, default=None)
            self.addInputWidget( step )
            ids.append(id)


        # Update scatter options before setting scatter value
        self.update_scatter_options()
        
        # After input widgets are created and scatter options updated, set scatter value
        if self.cwl_step.scatter:
            self.set_scatter(self.cwl_step.scatter)
        
        if self.cwl_step.scatterMethod:
            self.scatter_method_combobox.setCurrentText(self.cwl_step.scatterMethod)
        

        if hasattr(self.cwl_step, 'when'):
            self.when_container.setVisible(True)
            if self.cwl_step.when:
                self.when_input.setText(self.cwl_step.when)
        else:
            self.when_container.setVisible(False)
        
        if self.cwl_step.doc:
            self.doc_input.setPlainText(self.cwl_step.doc)
    
    def getData(self):
        """
        Return the values entered as a WorkflowStep 
        """
        # Prepare the data to return
        module= get_cwl_module(self.cwl_step)


        data = module.WorkflowStep(
            id=f"{self.filename_prefix}#{self.id_input.text()}" if self.filename_prefix else self.id_input.text(),
            label=self.label_input.text(),
            doc=self.doc_input.toPlainText(),
            in_=[],  # Will collect input configurations
            out=self.cwl_step.out if hasattr(self.cwl_step, 'out') else None,
            run=self.cwl_step.run if hasattr(self.cwl_step, 'run') else None
        )

            
        if self.when_input.text():
            data.when = self.when_input.text()
        
        # Handle scatter field - collect checked input IDs
        scatter_inputs = []
        for input_id, checkbox in self.scatter_checkboxes.items():
            if checkbox.isChecked():
                scatter_inputs.append(input_id)
        
        # If there's only one selected, use string format, otherwise use list
        if len(scatter_inputs) == 1:
            data.scatter = scatter_inputs[0]
        elif len(scatter_inputs) > 1:
            data.scatter = scatter_inputs
            
        # If scatter is set, also set scatterMethod
        if scatter_inputs:
            data.scatterMethod = self.scatter_method_combobox.currentText()
        
        # Collect input configurations into a list format as required by the template
        inputs_list = []
        
        # Add regular inputs
        if self.input_widgets:
            for input_id, widget in self.input_widgets.items():
                input_data = widget.getData()
                if input_data and (input_data.source or input_data.default):  # Only add if there's actual data
                    inputs_list.append(input_data)
        
        # Add conditional inputs from the group widget
        conditional_inputs = self.conditional_inputs_widget.getData()
        if conditional_inputs:
            inputs_list.extend(conditional_inputs)
        
        if inputs_list:
            data.in_ = inputs_list
        

        return data
    
    def onCodeEditor(self, widget_to_update=None):
        """Open JavaScript editor for the when expression."""
        # Show the dialog
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.cwl_dict = self.cwl_step
        
        if widget_to_update.text():
            dialog.editor.setText(widget_to_update.text())
            
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            self.code = dialog.get_javascript_code()
            if self.code:
                widget_to_update.setText(self.code)
                self.codeUpdated.emit()

if __name__ == '__main__':
    # load the configuration
    from configuration import Configuration
    from CWLparser import Parser
    conf=Configuration()
    conf.loadConfiguration("config.yaml")
    data.configuration=conf.getConfiguration()
    datatypes=Configuration()
    datatypes.loadConfiguration("dataStructures.yaml")
    data.datatypes=datatypes.getConfiguration()
    app = QApplication(sys.argv)
    tests_dir=Path(__file__).resolve().parents[1] / "tests"
    cwl_dict=Parser( str(tests_dir / "50-workflow.cwl")).getCWL()
    # For testing purposes
    dialog = StepDialog(parent=app.activeWindow(),cwl_step=cwl_dict.steps[1])
    dialog.setDefaults()
    
    if dialog.exec():
        print("Accepted")
        print(json.dumps(save(dialog.getData()), indent=2))
    else:
        print("Rejected")
    
    sys.exit(app.exec())