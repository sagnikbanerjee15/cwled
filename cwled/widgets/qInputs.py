from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QDialog, QCheckBox, QLabel
)
from .qButtons import QRemoveButton, QEditButton
from DialogInput import InputDialog
import json
from typing import Dict, List, Any, Optional
import data
import theme
from .qInspector import Inspector
import inspect
# Import for CWL operations
from widgets.QCWLedWidget import QCWLedWidget
from cwl_utils.parser import save
from CWLparser import (
    get_type, is_array, is_optional,
    is_optional_array, get_input_bindings
)
from cwl_utils_handler import get_cwl_module, format_parameter_type, format_input_binding
from cwl_utils.parser import save
import uuid
import logging
logger = logging.getLogger(__name__)
# Helper function to get calling function information

def get_caller_info():
    """Get information about the calling function."""
    try:
        frame = inspect.currentframe().f_back.f_back
        if frame:
            caller_name = frame.f_code.co_name
            caller_file = frame.f_code.co_filename.split('/')[-1]
            return f"{caller_file}:{caller_name}"
        return "unknown"
    except Exception:
        return "unknown"


class QInputsGroupWidget(QCWLedWidget):
    """Group widget for handling input fields."""
    
    input_counter = 0
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        cwl_tool: Optional[Dict[str, Any]] = None,
        cwl_version: Optional[str] = None
    ):
        """Initialize the widget with CWL tool data.
        
        Args:
            cwl_tool: CWL tool data dictionary
            parent: Parent widget
            cwl_version: Version of the CWL specification
        """
        super().__init__(
            parent=parent,
            cwl_tool=cwl_tool,
            cwl_version=cwl_version
        )
        
        self.logger.debug(
            f"Initialized with inputs list: {self.getCWL()}, "
            f"cwlVersion: {self.cwl_version}"
        )
        
    def initUI(self):
        """Initialize the user interface."""
        caller = get_caller_info()
        self.logger.debug(f"initUI called from {caller} with args: []")
        super().initUI()

        # Initialize widgets
        if isinstance(self.parent(), QInputWidget):
            title = "Fields:"
        else:
            title = "Inputs"
        
        # Create the header with add button
        from .qHeader import HeaderWithAddButton
        self.header = HeaderWithAddButton(title, self)
        self.header.addButtonClicked.connect(self.onAddInputWidget)

        # Set up the container layout for input widgets
        self.container_layout = QVBoxLayout()
        self.container_layout.setSpacing(0)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Set up the final layout
        final_layout = QVBoxLayout()
        final_layout.addWidget(self.header)
        final_layout.addLayout(self.container_layout)
        final_layout.addStretch(1)
        
        self.setLayout(final_layout)

    # def setCWLVersion(self, cwl_version: str):
    #     """
    #     Set the CWL version for this widget and its children.
        
    #     Args:
    #         cwl_version: CWL version string (e.g. 'v1.2')
    #     """
    #     caller = get_caller_info()
    #     self.logger.debug(
    #         f"setCWLVersion called from {caller} with args: [{cwl_version}]"
    #     )
    #     super().setCWLVersion(cwl_version)
        
    #     # Update version in all child argument widgets
    #     if hasattr(self, 'container_layout'):
    #         for i in range(self.container_layout.count()):
    #             item = self.container_layout.itemAt(i)
    #             if (item and item.widget() and
    #                     isinstance(item.widget(), QInputWidget)):
    #                 widget = item.widget()
    #                 if hasattr(widget, 'setCWLVersion'):
    #                     widget.setCWLVersion(cwl_version)
    def setCWL(self, cwl_tool: Any):
        """
        override the paternal version to run populateCWL
        """
        caller = get_caller_info()
        self.logger.debug(
            f"setCWL called from {caller} with args: [{cwl_tool}]"
        )
        super().setCWL(cwl_tool)

    @pyqtSlot()
    def onTextChange(self):
        """Handle text change events."""
        caller = get_caller_info()
        self.logger.debug(f"onTextChange called from {caller} with args: []")
        self._emit_editing_finished()

    @pyqtSlot()
    def addInputWidget(
        self,
        data: Any = None
    ):
        """Add a new QInputWidget to the container.
        
        Args:
            data: A single input entry that follows CWL CommandInputParameter
                or CommandInputRecordField structure.
            If None it will croak and fail.
        """
        caller = get_caller_info()
        self.logger.debug(
            f"addInputWidget called from {caller} with args: [{data}]"
        )
        
        if not data:
            self.logger.debug(f"addInputWidget called with no data")
            raise ValueError(
                "addInputWidget requires a data object of type "
                "CommandInputParameter or CommandInputRecordField."
            )
        
        command_widget = QInputWidget(
            entry_order=self.input_counter,
            cwl_version=self.cwl_version,
            parent=self,
            cwl_tool=data
        )
        
        command_widget.editingFinished.connect(self.onTextChange)
        command_widget.removeRequested.connect(self.removeInputWidget)
        command_widget.populateFields()
        self.container_layout.addWidget(command_widget)

        self.updateGeometry()
        # if not data:
        #     command_widget.onEditClicked()
        self.input_counter += 1
        
        # Update parent if we're a record field widget
        parent = self.parent()
        if isinstance(parent, QWidget):
            parent.updateGeometry()
        # self._emit_editing_finished()
        return command_widget

    def onAddInputWidget(self):
        """
        Add a widget with existing input object.
        
        This function is called when the + button is clicked
        on the QInputsGroupWidget.
        
        """
        caller = get_caller_info()
        self.logger.debug(
            f"onAddInputWidget called from {caller} "
            f"with args: [ ]"
        )
        logger.debug(f"We need to open a new dialog. decide what inpput we have")
        logger.debug(f"self = { type(self)}")
        logger.debug(f"parent= { type(self.parent())}  { isinstance( self.parent(),QInputWidget)}")
        logger.debug(f"grandparent= { type(self.parent().parent())} { isinstance( self.parent().parent(),QInputWidget)} ")
        # Create dialog with parent=self
        # to get the data that will populate the widget.
        # first we need to check what type of data we will get back from the dialog
        module=get_cwl_module(self.cwl_version)
        input_parameter_type='CommandInputParameter'
        ip=module.CommandInputParameter( 
            type_='CommandInputParameter',
            id=f"input{ str(uuid.uuid4())[:4]}"
        )
        if isinstance( self.parent().parent(),QInputWidget):
            input_parameter_type='CommandInputRecordField'
            ip=module.CommandInputRecordField(
                type_="CommandInputRecordField",
                name=f"name{ str(uuid.uuid4())[:4]}"
            )
        dialog = InputDialog(
            parent=self,
            input_parameter=ip
            # input_parameter=None,
            # input_parameter_type=input_parameter_type,
            # cwl_version=self.cwl_version
        )

        # Composer adds the entry right away and opens it in the inspector
        inspector = Inspector.forWidget(self)
        if inspector is not None:
            input_obj = dialog.getData()
            dialog.deleteLater()
            widget = self.addInputWidget(input_obj)
            self.container_layout.update()
            self._emit_editing_finished()
            inspector.openEntry(input_obj, QInputWidget)
            return widget
        
        dialog.show_next_to_main_window()
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            input_obj = dialog.getData()
            self.logger.debug(f"Dialog returned: {input_obj}")
            if input_obj:
                # Only create widget if we have data
                widget = self.addInputWidget(input_obj)
                # Force layout update after adding a widget
                self.container_layout.update()
                self._emit_editing_finished()
                return widget
            return None
        else:
            self.logger.debug("Dialog canceled, not creating widget")
            return None


    def removeInputWidget(self, widget):
        """
        Remove an argument widget from the container.
        
        Args:
            widget: Widget to remove
        """
        caller = get_caller_info()
        self.logger.debug(
            f"removeInputWidget called from {caller} with args: [{widget}]"
        )
        if widget in self.findChildren(QInputWidget):
            widget.setParent(None)
            widget.deleteLater()
            self._emit_editing_finished()
            self.logger.debug("Removed input widget")

    def getData(self) -> List[Dict[str, Any]]:
        """Return the data from all the rows."""
        caller = get_caller_info()
        self.logger.debug(f"getData called from {caller} with args: []")
        contents = []
        self.logger.debug("Collecting data from input widgets")
        for i in range(self.container_layout.count()):
            item = self.container_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if isinstance(widget, QInputWidget):
                    widget_data = widget.getData()
                    self.logger.debug(
                        f"Data for widget {i}: "
                        f"{json.dumps(widget_data, indent=3, default=str)}"
                    )
                    if widget_data:
                        contents.append(widget_data)
        
        self.logger.debug(f"Contents of inputs group: {contents}")
        return contents

    def clear(self, layout=None):
        """Clear the widget's content."""
        caller = get_caller_info()
        self.logger.debug(f"clear called from {caller} with args: [{layout}]")
        
        if not layout:
            layout = self.container_layout
            
        self.logger.debug("Cleaning up existing values")
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item.layout() and item.layout() != layout:
                self.clear(item.layout())
            elif item.widget():
                item.widget().deleteLater()
                
        self.logger.debug("Cleaning up finished")
        super().clear()

    def populateFromCWL(self, cwl_data: Optional[Any]):
        """Add widgets with existing cwl values.
        
        Args:
            cwl_data: CWL data to populate from.
        """
        caller = get_caller_info()
        self.logger.debug(f"populateFromCWL called from {caller} with args: [{cwl_data}]")
            
        if not cwl_data:
            return
        
        self.input_counter = 0
        self.clear()
        super().populateFromCWL(cwl_data)

        self.logger.debug(f"Data to populate widgets: {cwl_data}")
        
        current_inputs = self.getCWL()
        if current_inputs:
            self.logger.debug(f"Current inputs: {len(current_inputs)}")
             
            # for each input in the CWL data, create a widget
            for input_item in current_inputs:
                self.logger.debug(f"Adding input item: {input_item}")
                self.logger.debug(f"Current inputs: {type(input_item).__name__}")
                if type(input_item).__name__ not in [
                    'CommandInputParameter',
                    'CommandInputRecordField',
                    'InputParameter',
                    'InputRecordField',
                    'ExpressionToolInputParameter',
                    'WorkflowInputParameter'
                ]:
                    self.logger.warning(
                        f"Expected CommandInputParameter, CommandInputRecordField, InputParameter, InputRecordField, "
                        f"ExpressionToolInputParameter, or WorkflowInputParameter, "
                        f"got {type(input_item).__name__}"
                    )
                    continue
                self.addInputWidget(data=input_item)

    


class QInputWidget(QCWLedWidget):
    """Class to handle a row of input for a basecommand.
    
    Attributes:
        entry_order: The order that this row was added.
    """
    removeRequested = pyqtSignal(QWidget)
    
    def __init__(
            self,
            cwl_tool: Optional[Any] = None,
            entry_order: int = 0,
            parent: Optional[QWidget] = None,
            cwl_version: Optional[str] = None
    ):
        """Initialize the widget.
        
        Args:
            cwl_tool: CWL tool data
            entry_order: Order index for this input
            parent: Parent widget
            cwl_version: Version of the CWL specification
        """
        super().__init__(
            parent=parent,
            cwl_tool=cwl_tool,
            cwl_version=cwl_version
        )
        self.entry_order = entry_order
        # self.main_window = None
        self.logger = self.logger.getChild(f"input.{self.entry_order}")
        self.logger.debug(
            f"Initialized. CWL version: {self.cwl_version}. "
            f"Initial data: {self.getCWL()}"
        )
    
    def setCWL(self, cwl_tool: Optional[Any] = None):
        """
        Set the CWL tool data and update display fields.
        This function overrides the base class method to ensure
        that the CWL tool is of the correct type.
        Args:
            cwl_tool: CWL tool data object
        """
        caller = get_caller_info()
        self.logger.debug(f"setCWL called from {caller} with args: [{cwl_tool}]")
        
        super().setCWL(cwl_tool)
        if self.default_value and type(self.default_value).__name__ not in [
            'CommandInputParameter',
            'CommandInputRecordField',
            'InputParameter',
            'InputRecordField',
            'ExpressionToolInputParameter',
            'WorkflowInputParameter'
        ]:
            self.logger.warning(
                f"Expected CommandInputParameter, CommandInputRecordField, InputParameter, InputRecordField, "
                f"ExpressionToolInputParameter, or WorkflowInputParameter, got {type(self.default_value).__name__}"
            )
            self.default_value = None
        # self.populateFields()
        self._emit_editing_finished()

    def initUI(self):
        """Initialize the user interface."""
        caller = get_caller_info()
        self.logger.debug(f"initUI called from {caller} with args: []")
        
        super().initUI()

        # Initialize widgets
        self.line_edit_ID = QLineEdit(self)
        self.line_edit_ID.setPlaceholderText("ID")
        id_width = data.configuration.get('input_window', {}).get('id_width', 200)
        self.line_edit_ID.setFixedWidth(id_width)
        self.line_edit_ID.setReadOnly(True)

        self.line_edit_type = QLineEdit(self)
        self.line_edit_type.setPlaceholderText("Type")
        type_width = data.configuration.get('input_window', {}).get('type_width', 100)
        self.line_edit_type.setFixedWidth(type_width)
        self.line_edit_type.setReadOnly(True)
        
        # Add tristate checkbox for array handling
        self.line_edit_array = QCheckBox(self)
        self.line_edit_array.setTristate(True)
        self.line_edit_array.setText("[]")

        # Add record type widget (initially hidden)
        self.line_edit_record_type = QLineEdit(self)
        self.line_edit_record_type.setPlaceholderText("Record Type")
        record_type_width = data.configuration.get('input_window', {}).get('record_type_width', 150)
        self.line_edit_record_type.setFixedWidth(record_type_width)
        self.line_edit_record_type.setReadOnly(True)
        self.line_edit_record_type.hide()  # Initially hidden

        self.line_edit_prefix = QLineEdit(self)
        self.line_edit_prefix.setPlaceholderText("Prefix")
        prefix_width = data.configuration.get('input_window', {}).get('prefix_width', 200)
        self.line_edit_prefix.setFixedWidth(prefix_width)
        self.line_edit_prefix.setReadOnly(True)

        self.line_edit_argument = QLineEdit(self)
        self.line_edit_argument.setPlaceholderText(" Value")
        value_width = data.configuration.get('input_window', {}).get('value_width', 300)
        self.line_edit_argument.setFixedWidth(value_width)
        self.line_edit_argument.setReadOnly(True)

        self.line_edit_order = QLineEdit(self)
        self.line_edit_order.setPlaceholderText("Order")
        order_width = data.configuration.get('input_window', {}).get('order_width', 30)
        self.line_edit_order.setFixedWidth(order_width)
        self.line_edit_order.setReadOnly(True)

        self.remove_button = QRemoveButton(self)
        self.edit_button = QEditButton(self)

        # Connect signals
        self.remove_button.clicked.connect(self.onRemoveClicked)
        self.edit_button.clicked.connect(self.onEditClicked)

        # Composer input list entry: ID | Type | Binding. The whole bar opens
        # the InputDialog; the detailed fields stay hidden but are kept up to date.
        self.type_label = QLabel(self)
        self.binding_label = QLabel(self)
        self.row_bar = theme.ListRow(self)
        self.row_bar.addColumn(self.line_edit_ID, 4)
        self.row_bar.addColumn(self.type_label, 3)
        self.row_bar.addColumn(self.binding_label, 4)
        self.row_bar.addSpacer(1)
        self.row_bar.clicked.connect(self.onEditClicked)
        self._hidden_fields = QWidget(self)
        self._hidden_fields.hide()
        for hidden in (self.line_edit_type, self.line_edit_array, self.line_edit_record_type,
                       self.line_edit_prefix, self.line_edit_argument, self.line_edit_order,
                       self.edit_button):
            hidden.setParent(self._hidden_fields)
        theme.listRowLayout(self, self.row_bar, self.remove_button)
        # Update fields display
        # self.populateFields()

    @pyqtSlot()
    def onRemoveClicked(self):
        """Handle the remove button click."""
        caller = get_caller_info()
        self.logger.debug(f"onRemoveClicked called from {caller} with args: []")
        
        if self.parent():
            self.removeRequested.emit(self)
            self.setParent(None)  # Remove widget from parent layout
            self.deleteLater()
            self._emit_editing_finished()
    
    @pyqtSlot()
    def onEditClicked(self):
        """Handle the edit button click.
            it calls the InputDialog to edit the input.
            return: None (adds the information to the self.cwl_tool)
        
        """
        caller = get_caller_info()
        self.logger.debug(f"onEditClicked called from {caller} with args: []")

        # the input dialog needs to know what type of input it is handling.
        # it can get that from an existing InputParameter or RecordField,
        # but if we start a new empty one it needs to know what to work with.
        input_parameter_type = None
        if not self.getCWL():
            input_parameter_type = 'CommandInputParameter'
        # let's check if this is a record field.
        # this means that the parent QInputsGroupWidget belongs to a record
        # first find the parent widget (QInputWidget) that may host the record
        try:
            parent_widget = self.parent().parent().parent()
            if (hasattr(parent_widget, 'line_edit_record_type') 
                    and parent_widget.line_edit_record_type):
                # if the parent has a line_edit_record_type, it is a record field
                input_parameter_type = 'CommandInputRecordField'
        except Exception:
            pass
            
        self.logger.debug(
            f"Edit button clicked, opening InputDialog for {input_parameter_type}"
        )
        
        dialog = InputDialog(
            parent=self,
            input_parameter=self.getCWL(),
            input_parameter_type=input_parameter_type
        )

        # In the tool editor the input opens in the Composer object inspector
        inspector = Inspector.forWidget(self)
        if inspector is not None:
            inspector.inspect(self, dialog, lambda d: d.id_input.text())
            return
        
        # Position the dialog next to the main window
        dialog.show_next_to_main_window()
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get inputs from the dialog
            inputs = dialog.getData()
            self.logger.debug(f"Dialog returned: {inputs}")
            
            self.setCWL(inputs)

    def populateFields(self):
        """Set the variables within the object.
        
        Args:
            data: Input data according to CWL CommandInputParameter spec
        """
        caller = get_caller_info()
        self.logger.debug(f"populateFields called from {caller} with args: []")
        
        cwl_input = self.getCWL()
        
        # Clean up any existing record fields widget
        if hasattr(self, 'record_fields_widget'):
            if self.record_fields_widget:
                self.record_fields_widget.setParent(None)
                self.record_fields_widget = None
            
        if cwl_input:
            field_type = get_type(cwl_input, result=[])
            self.logger.debug(
                f"Populating fields from input: {cwl_input} - {field_type}"
            )
            self.logger.debug(f"{save(cwl_input)}")

            if hasattr(cwl_input, 'inputBinding') and cwl_input.inputBinding:
                ib = get_input_bindings(cwl_input)
                if hasattr(self, 'line_edit_prefix'):
                    self.line_edit_prefix.setText(ib.prefix or '')
                if hasattr(self, 'line_edit_argument'):
                    self.line_edit_argument.setText(ib.valueFrom or '')
            
            try:
                field_type.remove('array')
            except ValueError:
                pass
            
            opt = is_optional(cwl_input)
            
            # Optional inputs are shown in the muted colour
            font_style = ""
            font_color = f"color: {theme.TEXT_MUTED};" if opt else f"color: {theme.TEXT};"
            style_sheet = f"{font_style} {font_color}"
            self.type_label.setText(format_parameter_type(getattr(cwl_input, 'type_', None)))
            self.binding_label.setText(format_input_binding(getattr(cwl_input, 'inputBinding', None)))
            
            if is_optional_array(cwl_input):
                self.line_edit_array.setCheckState(Qt.CheckState.PartiallyChecked)
            elif is_array(cwl_input):
                self.line_edit_array.setCheckState(Qt.CheckState.Checked)
            else:
                self.line_edit_array.setCheckState(Qt.CheckState.Unchecked)
                
            # Make the array checkbox read-only after setting its state
            self.line_edit_array.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.line_edit_array.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            self.line_edit_type.setText('/'.join(field_type))
           
            if hasattr(cwl_input, 'id') and cwl_input.id:
                id_parts = cwl_input.id.split("#")[-1].split("/")[-1]
                self.line_edit_ID.setText(id_parts or '')
            elif hasattr(cwl_input, 'name') and cwl_input.name:
                self.line_edit_ID.setText(cwl_input.name or '')
            else:
                raise ValueError(
                    "Input object must have either 'id' or 'name' attribute"
                )
            # Apply style sheet to the ID and type fields
            self.line_edit_type.setStyleSheet(style_sheet)
            self.line_edit_ID.setStyleSheet(style_sheet)

            # Handle record type fields differently than regular fields
            if 'record' in field_type:
                # Hide prefix, value and order widgets
                self.line_edit_prefix.hide()
                self.line_edit_argument.hide()
                self.line_edit_order.hide()
                
                # Show and set the record type widget
                self.line_edit_record_type.show()
                
                # Set default value to 'dependent' if not already set
                record_type = 'dependent'
                record_schemas = []
                input_type = getattr(self.default_value, 'type_', None)
                if (hasattr(input_type, 'fields') and
                        not isinstance(input_type, list)):
                    record_schemas = [input_type]
                elif isinstance(input_type, list):
                    record_schemas = [
                        schema for schema in input_type
                        if hasattr(schema, 'fields')
                    ]
                # Only multiple record schemas represent mutually exclusive
                # records; unions like ['null', record] remain dependent.
                if len(record_schemas) > 1:
                    record_type = 'exclusive'
                self.line_edit_record_type.setText(record_type)
                
                # Apply the style sheet to the record type field
                self.line_edit_record_type.setStyleSheet(style_sheet)
            else:                # For non-record types, show standard fields
                self.line_edit_record_type.hide()
                self.line_edit_prefix.show()
                self.line_edit_argument.show()
                self.line_edit_order.show()
                
                # Set regular field values
                position_text = '0'
                if (hasattr(cwl_input.inputBinding, 'position') and
                        cwl_input.inputBinding.position is not None):
                    position_text = str(cwl_input.inputBinding.position)
                
                if hasattr(self, 'line_edit_order'):
                    self.line_edit_order.setText(position_text)
            
            if hasattr(self, 'line_record_field'):
                self.line_record_field.setText(self.record_id)
                
            # Add embedded QInputsGroupWidget for record type
            if 'record' in field_type:
                logger.debug("We are handling a record")
                # Store the original horizontal layout
                original_layout = self.layout()
                
                # Create a vertical layout to replace the original layout
                main_layout = QVBoxLayout()
                main_layout.setContentsMargins(0, 0, 0, 0)
                
                # Create a widget to contain the original widgets
                hbox_container = QWidget()
                hbox_layout = QHBoxLayout(hbox_container)
                hbox_layout.setContentsMargins(0, 0, 0, 0)
                hbox_layout.setSpacing(original_layout.spacing())
                
                # Move all widgets from original_layout to hbox_layout
                while original_layout.count():
                    item = original_layout.takeAt(0)
                    if item.widget():
                        hbox_layout.addWidget(item.widget())
                    elif item.spacerItem():
                        hbox_layout.addSpacerItem(item.spacerItem())
                
                # Add the horizontal container to the main layout
                main_layout.addWidget(hbox_container)
                
                # Create a new QInputsGroupWidget for record fields
                self.record_fields_widget = QInputsGroupWidget(
                    parent=self,
                    cwl_version=self.cwl_version
                )
                self.record_fields_widget.editingFinished.connect(self._emit_editing_finished)
                # Create a container with border for the record fields
                container = QWidget()
                container.setObjectName("recordFieldsContainer")
                container.setStyleSheet(f"""
                    QWidget#recordFieldsContainer {{
                        border: 1px solid {theme.BLACK};
                        border-radius: 2px;
                        margin-top: 5px;
                    }}
                """)
                
                # Create a layout for the container
                container_layout = QVBoxLayout(container)
                container_layout.setContentsMargins(10, 10, 10, 10)
                container_layout.addWidget(self.record_fields_widget)
                
                # Add the container to the main layout
                main_layout.addWidget(container)
                
                # Set the main vertical layout as the widget's layout
                QWidget().setLayout(original_layout)  # Detach the old layout
                self.setLayout(main_layout)
                
                self.logger.debug(
                    f"Added embedded QInputsGroupWidget for record fields, which should host {save(self.default_value)}"
                )
                self.logger.debug(
                    f"Adding {self.default_value.type_}"
                )
                # now we need to populate the widgets of the record fields widget
                logger.debug(f"{save( self.default_value)}")
                input_type = getattr(self.default_value, 'type_', None)
                record_schemas = []
                if (hasattr(input_type, 'fields') and
                        not isinstance(input_type, list)):
                    record_schemas = [input_type]
                elif isinstance(input_type, list):
                    record_schemas = [
                        schema for schema in input_type
                        if hasattr(schema, 'fields')
                    ]

                # Dependent record: direct record schema or optional union with
                # a single record schema.
                if len(record_schemas) == 1:
                    dependent_schema = record_schemas[0]
                    logger.debug(f"Adding fields {dependent_schema.fields}")
                    # Push parent record defaults to each field as _field_default
                    record_defaults = {}
                    if hasattr(self.default_value, 'default') and isinstance(self.default_value.default, dict):
                        record_defaults = self.default_value.default
                    if record_defaults:
                        for field in dependent_schema.fields:
                            if hasattr(field, 'name') and field.name:
                                field_name = field.name.split('#')[-1].split('/')[-1]
                                if field_name in record_defaults:
                                    field._field_default = record_defaults[field_name]
                    self.record_fields_widget.populateFromCWL(
                        dependent_schema.fields
                    )
                    # Force layout update
                    self.record_fields_widget.container_layout.update()
                # Mutually exclusive records: only when there are multiple
                # record schemas in the union.
                if len(record_schemas) > 1:
                    logger.debug(f"Adding records {record_schemas}")
                    # Push defaults to the matching exclusive child field
                    exclusive_defaults = {}
                    if hasattr(self.default_value, 'default') and isinstance(self.default_value.default, dict):
                        exclusive_defaults = self.default_value.default
                    selected_class = exclusive_defaults.get('class', '')
                    # If no 'class' key, select the first schema with a non-empty default
                    if not selected_class and exclusive_defaults:
                        for schema in record_schemas:
                            if hasattr(schema, 'name') and schema.name:
                                sname = schema.name.split('#')[-1].split('/')[-1]
                                if sname in exclusive_defaults and exclusive_defaults[sname]:
                                    selected_class = sname
                                    break
                    fields_to_populate = []
                    for schema in record_schemas:
                        field = schema.fields[0] if schema.fields else None
                        if field and selected_class and hasattr(schema, 'name') and schema.name:
                            schema_name = schema.name.split('#')[-1].split('/')[-1]
                            if schema_name == selected_class and selected_class in exclusive_defaults:
                                field._field_default = exclusive_defaults[selected_class]
                        fields_to_populate.append(field)
                    self.record_fields_widget.populateFromCWL(fields_to_populate)
                    


                
        else:
            # Show standard widgets, hide record widgets when no input
            self.line_edit_prefix.show()
            self.line_edit_argument.show()
            self.line_edit_order.show()
            self.line_edit_record_type.hide()
            
            # Clear all text fields
            self.line_edit_prefix.setText('')
            self.line_edit_argument.setText('')
            self.line_edit_order.setText('0')
            self.line_edit_record_type.setText('')
            self.type_label.setText('')
            self.binding_label.setText('')
            
            # Reset style when no input data
            self.line_edit_type.setStyleSheet("")
            self.line_edit_ID.setStyleSheet("")
            self.line_edit_record_type.setStyleSheet("")
            
            # Reset array checkbox to be editable
            self.line_edit_array.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
            )
            self.line_edit_array.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def clear(self):
        """Clear the input data and display fields."""
        caller = get_caller_info()
        self.logger.debug(f"clear called from {caller} with args: []")
        
        super().clear()  # This sets self.cwl_tool to None
        
        # Clean up any existing record fields widget
        if hasattr(self, 'record_fields_widget') and self.record_fields_widget:
            self.record_fields_widget.setParent(None)
            self.record_fields_widget = None
            
        # Find and remove container widget if it exists
        layout = self.layout()
        if layout and layout.count() > 1:  # More than one widget
            for i in range(layout.count()):
                item = layout.itemAt(i)
                widget = item.widget() if item else None
                if widget and widget.objectName() == "recordFieldsContainer":
                    widget.setParent(None)
                    widget.deleteLater()
                    break
        
        self.populateFields()
        self.logger.debug("Input widget cleared")
        
    def getData(self) -> Optional[Dict[str, Any]]:
        """
        Get the input data with metadata for sorting.
        
        Returns:
            Dictionary containing the input object and metadata,
            or None if no data is available.
        """
        caller = get_caller_info()
        self.logger.debug(f"getData called from {caller} with args: []")
        
        cwl_input = self.getCWL()
        self.logger.debug(f"Received {cwl_input}")
        logger.debug(f"Received {cwl_input}")
        if not cwl_input:
            return None
        
        module = get_cwl_module(self.cwl_version)
        
        if hasattr(self, 'record_fields_widget') and self.record_fields_widget:
            self.logger.debug("We need to get the fields of the record")
            logger.debug("Getting the fields of the record")
            # get the record fields
            record_fields = self.record_fields_widget.getData()
            if record_fields:  # Only process if there are record fields
                record_fields = [
                    x.get('argument')
                    for x in record_fields
                    if x and x.get('argument')
                ]
                self.logger.debug(f"Fields {record_fields}")
                logger.debug(f"Fields { record_fields}")
                
                # Store the original record type
                record_type = 'dependent'
                if hasattr(self, 'line_edit_record_type'):
                    record_type = self.line_edit_record_type.text()
                logger.debug(f"We store the records as {record_type}")
                # Update fields based on record type
                if record_type == 'dependent':
                    # For dependent records, set the fields directly
                    target_schema = None
                    if (hasattr(cwl_input, 'type_') and
                            hasattr(cwl_input.type_, 'fields')):
                        target_schema = cwl_input.type_
                    elif (hasattr(cwl_input, 'type_') and
                            isinstance(cwl_input.type_, list)):
                        record_schemas = [
                            schema for schema in cwl_input.type_
                            if hasattr(schema, 'fields')
                        ]
                        if len(record_schemas) == 1:
                            target_schema = record_schemas[0]
                    if target_schema:
                        target_schema.fields = record_fields
                    # Collect per-field defaults into a record default dict
                    record_defaults = {}
                    for rf in record_fields:
                        field_name = None
                        if hasattr(rf, 'name') and rf.name:
                            field_name = rf.name.split('#')[-1].split('/')[-1]
                        if field_name and hasattr(rf, '_field_default') and rf._field_default is not None:
                            record_defaults[field_name] = rf._field_default
                    if record_defaults:
                        cwl_input.default = record_defaults
                    else:
                        cwl_input.default = None
                else:
                    # For exclusive records, wrap each field in a CommandInputRecordSchema
                    wrapped_record_schemas = []
                    for rf in record_fields:
                        if type(rf).__name__ ==  'CommandInputRecordField' :
                            if self.cwl_version == 'v1.0':
                                rs=module.CommandInputRecordSchema(
                                    type_='record',
                                    label=rf.label,
                                    name=rf.name,
                                    fields=[ 
                                        rf
                                    ]
                                )
                            else:
                                rs=module.CommandInputRecordSchema(
                                    type_='record',
                                    doc=rf.doc,
                                    label=rf.label,
                                    name=rf.name,
                                    fields=[ 
                                        rf
                                    ]
                                )
                            wrapped_record_schemas.append(rs)
                    preserved_non_record = []
                    if isinstance(cwl_input.type_, list):
                        preserved_non_record = [
                            schema for schema in cwl_input.type_
                            if not hasattr(schema, 'fields')
                        ]
                    cwl_input.type_ = preserved_non_record + wrapped_record_schemas
                    # Collect exclusive default from child _field_default
                    exclusive_default = None
                    for schema in wrapped_record_schemas:
                        if hasattr(schema, 'fields') and schema.fields:
                            child = schema.fields[0]
                            if hasattr(child, '_field_default') and child._field_default is not None:
                                schema_name = schema.name.split('#')[-1].split('/')[-1] if hasattr(schema, 'name') and schema.name else ''
                                if schema_name:
                                    exclusive_default = {
                                        'class': schema_name,
                                        schema_name: child._field_default
                                    }
                                    break
                    cwl_input.default = exclusive_default

        position = 0
        if (hasattr(cwl_input.inputBinding, 'position') and
                cwl_input.inputBinding.position):
            position = cwl_input.inputBinding.position
        
        return {
            'entry_order': self.entry_order,
            'order': position,
            'argument': cwl_input
        }
