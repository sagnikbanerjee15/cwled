from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QDialog, QCheckBox, QLabel
from .qButtons import QRemoveButton, QEditButton
from DialogOutput import OutputDialog
import json
from typing import Dict, List, Any, Optional,Tuple
import data
import theme
from .qInspector import Inspector
from copy import deepcopy
from dataTypes import output
from widgets.QCWLedWidget import QCWLedWidget
from cwl_utils_handler import get_cwl_module, CWLType, format_parameter_type
from CWLparser import get_type, is_array, is_optional, is_optional_array
from cwl_utils.parser import save
import re
import uuid

class QOutputsGroupWidget(QCWLedWidget):
    """Widget group for handling output fields."""
    
    output_counter = 0
    
    def __init__(self,  
                 parent: Optional[QWidget] = None,
                 cwl_tool: Optional[Dict[str, Any]] = None, 
                 cwl_version: Optional[str] = None):
        """Initialize the widget with CWL tool data.
        
        Args:
            cwl_tool: CWL tool data dictionary
            parent: Parent widget
            cwl_version: Version of the CWL specification
        """
        super().__init__(parent=parent, cwl_tool=cwl_tool, cwl_version=cwl_version)
        self.logger.debug(
            f"Initialized with outputs list: {self.getCWL()}, "
            f"cwlVersion: {self.cwl_version}"
        )
        
    def initUI(self):
        """Initialize the user interface."""
        super().initUI()

        # Use the common header with add button
        from .qHeader import HeaderWithAddButton
        self.header = HeaderWithAddButton("Outputs", self)
        self.header.addButtonClicked.connect(self.onAddOutputWidget)

        # Set up the container layout for output widgets
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
    #     super().setCWLVersion(cwl_version)
        
    #     # Update version in all child argument widgets
    #     if hasattr(self, 'container_layout'):
    #         for i in range(self.container_layout.count()):
    #             item = self.container_layout.itemAt(i)
    #             if (item and item.widget() and
    #                     isinstance(item.widget(), QOutputWidget)):
    #                 widget = item.widget()
    #                 if hasattr(widget, 'setCWLVersion'):
    #                     widget.setCWLVersion(cwl_version)

    @pyqtSlot()
    def onTextChange(self):
        """Handle text change events."""
        self.logger.debug("Text has changed for outputs, we have to update the CWL")
        self._emit_editing_finished()

    @pyqtSlot()
    def addOutputWidget(self, data: Optional[ Any] = None):
        """Add a new QOutputWidget to the container.
        
        Args:
            data: A single output entry that follows CWL CommandOutputParameter
        """
        output_obj= data

        command_widget = QOutputWidget(
            cwl_tool=output_obj,
            cwl_version=self.cwl_version, 
            entry_order=self.output_counter,
            parent=self
        )
        command_widget.editingFinished.connect(self.onTextChange)
        command_widget.removeRequested.connect(self.removeOutputWidget)
        command_widget.populateFields()
        self.container_layout.addWidget(command_widget)
        
        # if not data:
        #     command_widget.onEditClicked()
            
        self.output_counter += 1
        return command_widget

    def onAddOutputWidget(self):
        """
        Add a widget with an output object.
        
        Args:
            argument_obj: Argument object to add
            
        Returns:
            The created widget
        """

        module=get_cwl_module( self.cwl_version)
        op=module.CommandOutputParameter(
            type_="CommandOutputParameter",
            id=f"output{ str(uuid.uuid4())[:4]}"
        )
        dialog = OutputDialog(
            parent=self,
            output_parameter=op
        )

        # Composer adds the entry right away and opens it in the inspector
        inspector = Inspector.forWidget(self)
        if inspector is not None:
            output_obj = dialog.getData()
            dialog.deleteLater()
            widget = self.addOutputWidget(output_obj)
            self.container_layout.update()
            self._emit_editing_finished()
            inspector.openEntry(output_obj, QOutputWidget)
            return widget
        
        dialog.show_next_to_main_window()
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            output_obj = dialog.getData()
            self.logger.debug(f"Dialog returned: {output_obj}")
            if output_obj:
                # Only create widget if we have data
                widget = self.addOutputWidget(output_obj)
                # Force layout update after adding a widget
                self.container_layout.update()
                self._emit_editing_finished()
                return widget
            return None
        else:
            self.logger.debug("Dialog canceled, not creating widget")
            return None
        
    
    def removeOutputWidget(self, widget):
        """
        Remove an argument widget from the container.
        
        Args:
            widget: Widget to remove
        """
        if widget in self.findChildren(QOutputWidget):
            widget.setParent(None)
            widget.deleteLater()
            self._emit_editing_finished()
            self.logger.debug("Removed output widget")

    def getData(self) -> List[Dict[str, Any]]:
        """Return the data from all the rows."""
        self.logger.debug("Retrieving updated data")
        contents = []
        
        for i in range(self.container_layout.count()):
            item = self.container_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if isinstance(widget, QOutputWidget):
                    widget_data = widget.getData()
                    self.logger.debug(f"Data for widget {i}: {json.dumps(widget_data, indent=3, default=str)}")
                    if widget_data:
                        contents.append(widget_data)
        
        self.logger.debug(f"Contents of outputs group: {contents}")
        return contents

    def clear(self, layout=None):
        """Clear the widget's content."""
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

    def populateFromCWL(self, cwl_data: Optional[Any] = None):
        """Add widgets with existing cwl values.
        
        Args:
            cwl_data: CWL data to populate from.
        """
        if cwl_data is None:
            return
            
        self.output_counter = 0
        self.clear()
        super().populateFromCWL(cwl_data)

        current_outputs= self.getCWL()
        if current_outputs:
            self.logger.debug(f"Populating outputs from CWL: {len(current_outputs)}")


            for output_item in current_outputs:
                self.logger.debug(f"Adding input item: {output_item}")
                self.logger.debug(f"Current outputs: {type(output_item).__name__}") 
                if type(output_item).__name__ not in ['CommandOutputParameter', 'OutputParameter', 'ExpressionToolOutputParameter']:
                    self.logger.warning(
                        f"Expected CommandOutputParameter, OutputParameter, or ExpressionToolOutputParameter, got {type(output_item).__name__}"
                    )
                    continue
                self.addOutputWidget(output_item)


class QOutputWidget(QCWLedWidget):
    """Class to handle a row of output for a tool.
    
    Attributes:
        entry_order: The order that this row was added.
    """
    removeRequested = pyqtSignal(QWidget)
    def __init__(self, 
                 cwl_tool: Optional[Dict[str, Any]] = None,
                 entry_order: int = 0, 
                 parent: Optional[QWidget] = None,
                 cwl_version: Optional[str] = None):
        """Initialize the widget.
        
        Args:
            cwl_tool: CWL tool data
            entry_order: Order index for this output
            parent: Parent widget
            cwl_version: Version of the CWL specification
        """
        super().__init__(parent=parent, 
                         cwl_tool=cwl_tool, 
                         cwl_version=cwl_version)
        self.entry_order = entry_order
        # self.main_window = None
        self.logger = self.logger.getChild(f"output.{self.entry_order}")
    
        self.logger.debug(
            f"Initialized. CWL version: {self.cwl_version}. "
            f"Initial data: {save(self.getCWL())}"
        )

    def setCWL(self, cwl_tool: Optional[Any]):
        """
        Set the CWL argument object and update display fields.
        
        Args:
            cwl_tool: A CWL CommandLineBinding object
        """
        super().setCWL(cwl_tool)
        if self.default_value and type(self.default_value).__name__ not in ['CommandOutputParameter', 'OutputParameter', 'ExpressionToolOutputParameter']:
            self.logger.warning(
                f"Expected CommandOutputParameter, OutputParameter, or ExpressionToolOutputParameter, got {type(self.default_value).__name__}"
            )
            self.default_value = None
        # self.populateFields()
        self._emit_editing_finished()
        
    def initUI(self):
        """Initialize the user interface."""
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

        self.line_edit_glob = QLineEdit(self)
        self.line_edit_glob.setPlaceholderText("Glob")
        glob_width = data.configuration.get('input_window', {}).get('glob_width', 400)
        self.line_edit_glob.setFixedWidth(glob_width)
        self.line_edit_glob.setReadOnly(True)

        self.remove_button = QRemoveButton(self)
        self.edit_button = QEditButton(self)

        # Connect signals
        self.remove_button.clicked.connect(self.onRemoveClicked)
        self.edit_button.clicked.connect(self.onEditClicked)

        # Composer output list entry: ID | Type | Glob. The whole bar opens
        # the OutputDialog; the detailed fields stay hidden but are kept up to date.
        self.type_label = QLabel(self)
        self.row_bar = theme.ListRow(self)
        self.row_bar.addColumn(self.line_edit_ID, 4)
        self.row_bar.addColumn(self.type_label, 3)
        self.row_bar.addColumn(self.line_edit_glob, 4)
        self.row_bar.addSpacer(1)
        self.row_bar.clicked.connect(self.onEditClicked)
        self._hidden_fields = QWidget(self)
        self._hidden_fields.hide()
        for hidden in (self.line_edit_type, self.line_edit_array, self.edit_button):
            hidden.setParent(self._hidden_fields)
        theme.listRowLayout(self, self.row_bar, self.remove_button)
        # Update fields display
        # self.populateFields()

    @pyqtSlot()
    def onRemoveClicked(self):
        """Handle the remove button click."""
        if self.parent():
            self.setParent(None)  # Remove widget from parent layout
            self.hide()
            self.deleteLater()
            self._emit_editing_finished()
    
    @pyqtSlot()
    def onEditClicked(self):
        """Handle the edit button click."""
        dialog = OutputDialog(parent=self, output_parameter=self.getCWL())

        # In the tool editor the output opens in the Composer object inspector
        inspector = Inspector.forWidget(self)
        if inspector is not None:
            inspector.inspect(self, dialog, lambda d: d.id_input.text())
            return

        # Show dialog
        dialog.show_next_to_main_window()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            outputs = dialog.getData()
            self.logger.debug(f"Dialog returned: {outputs}")
            
            
            self.setCWL(outputs)



    def populateFields(self):
        """Set the variables within the object.
        
        Args:
            data: Input data according to CWL CommandInputParameter spec
        """
        """Update display fields from the current argument data."""
        output = self.getCWL()
        if output:
            self.logger.debug(f"Populating fields from output: {save(output)}")
            if hasattr(output, 'outputBinding') and output.outputBinding:
                ib= output.outputBinding
                self.line_edit_glob.setText(ib.glob or '')
            field_type=get_type( output, result=[] )
            try:
                field_type.remove('array')
            except ValueError:
                pass
            self.logger.debug(f"Field type: {field_type}")
            
            opt=is_optional(output)
            self.logger.debug(f"Is optional: {opt}")
            self.type_label.setText(format_parameter_type(getattr(output, 'type_', None)))
            # Optional outputs are shown in the muted colour
            font_style = ""
            font_color = f"color: {theme.TEXT_MUTED};" if opt else f"color: {theme.TEXT};"
            style_sheet = f"{font_style} {font_color}"
            
            if is_optional_array( output ):
                self.line_edit_array.setCheckState(Qt.CheckState.PartiallyChecked)
            elif is_array(output):
                self.line_edit_array.setCheckState(Qt.CheckState.Checked)
            else :
                self.line_edit_array.setCheckState(Qt.CheckState.Unchecked)
                
            # Make the array checkbox read-only after setting its state
            self.line_edit_array.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.line_edit_array.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            self.line_edit_type.setText( '/'.join(field_type))
            self.line_edit_ID.setText( output.id.split("#")[-1].split("/")[-1] or '')
            
            # Apply style sheet to the ID and type fields
            self.line_edit_type.setStyleSheet(style_sheet)
            self.line_edit_ID.setStyleSheet(style_sheet)

        else:
            # Reset style when no input data
            self.line_edit_type.setStyleSheet("")
            self.line_edit_ID.setStyleSheet("")
            
            # Reset array checkbox to be editable
            self.line_edit_array.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.line_edit_array.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


    def clear(self):
        """Clear the input data and display fields."""
        super().clear()  # This sets self.cwl_tool to None
        self.populateFields()
        self.logger.debug("Input widget cleared")

    def getData(self) -> Optional[Dict[str, Any]]:
        """
        Get the input data with metadata for sorting.
        
        Returns:
            Dictionary containing the input object and metadata,
            or None if no data is available.
        """
        output = self.getCWL()
        if not output:
            return None
            
        return {
            'entry_order': self.entry_order,
            'order': output.position if hasattr(output, 'position') else 0,
            'argument': output
        }
    