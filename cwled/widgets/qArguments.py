from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QHBoxLayout, QVBoxLayout,
    QDialog, QLabel
)
import data
import theme
from .qInspector import Inspector
from .qButtons import QEditButton, QRemoveButton
from DialogArgument import ArgumentDialog
from typing import Union, Any, List, Dict, Optional
from widgets.QCWLedWidget import QCWLedWidget
from cwl_utils_handler import get_cwl_module

class QArgumentsGroupWidget(QCWLedWidget):
    """
    Manages a list of CWL Arguments.
    Each argument is represented by a QArgumentWidget.
    """
    argument_counter = 0
    cwl_tool: Optional[Union[List[Any], Dict[str, Any]]] = None
    cwl_version: Optional[str] = None
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        cwl_tool: Optional[Union[List[Any], Dict[str, Any]]] = None,
        cwl_version: Optional[str] = None
    ):
        """
        Initialize the arguments group widget.
        
        Args:
            parent: Parent widget
            cwl_tool: CWL tool data, either a list of argument objects or
                      a dict with {'arguments': [...], 'cwlVersion': '...'}
            cwl_version: Version of the CWL specification
        """
        super().__init__(
            parent=parent, 
            cwl_tool=cwl_tool, 
            cwl_version=cwl_version
        )
        self.logger.debug(
            f"Initialized with arguments list: {self.getCWL()}, "
            f"cwlVersion: {self.cwl_version}"
        )

    def initUI(self):
        """Initialize the user interface."""
        super().initUI()
        
        # Use the common header with add button
        from .qHeader import HeaderWithAddButton
        self.header = HeaderWithAddButton("Arguments", self)
        self.header.addButtonClicked.connect(self.onAddArgumentWidget)

        # Set up the container layout for argument widgets
        self.container_layout = QVBoxLayout()
        self.container_layout.setSpacing(0)  # No space between rows
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Set up the final layout
        final_layout = QVBoxLayout()
        final_layout.addWidget(self.header)
        final_layout.addLayout(self.container_layout)
        final_layout.addStretch(1)
        
        # Set the layout for the main widget
        self.setLayout(final_layout)

    # def setCWLVersion(self, cwl_version: str):
    #     """
    #     Set the CWL version for this widget and its children.
        
    #     Args:
    #         cwl_version: CWL version string (e.g. 'v1.2')
    #     """
    #     super().setCWLVersion(cwl_version)
    #     # self.logger.debug(f"Setting CWL version for arguments group: {cwl_version}")
    #     # # Update version in all child argument widgets
    #     # if hasattr(self, 'container_layout'):
    #     #     for i in range(self.container_layout.count()):
    #     #         self.logger.debug(f"Updating child widget {i} with CWL version {cwl_version}")
    #     #         item = self.container_layout.itemAt(i)
    #     #         if (item and item.widget() and
    #     #                 isinstance(item.widget(), QArgumentWidget)):
    #     #             widget = item.widget()
    #     #             if hasattr(widget, 'setCWLVersion'):
    #     #                 widget.setCWLVersion(cwl_version)
    
    @pyqtSlot()
    def onTextChange(self):
        """Handle text changes in child widgets."""
        self.logger.debug("Text has changed for arguments, updating CWL")
        self._emit_editing_finished()

    @pyqtSlot()
    def addArgumentWidget(self, 
                          data: Optional[Any]=None
                          ):
        """
        Add a new QArgumentWidget to the container.
        
        Args:
            arg_data: Optional argument data to initialize the widget with
            
        Returns:
            The created widget
        """
        arg_obj = data
            
        command_widget = QArgumentWidget(
            entry_order=self.argument_counter,
            cwl_version=self.cwl_version,
            parent=self,
            cwl_tool=arg_obj
        )
        command_widget.editingFinished.connect(self.onTextChange)
        command_widget.removeRequested.connect(self.removeArgumentWidget)
        self.container_layout.addWidget(command_widget)
        command_widget.populateFields()
        # if data is None:
        #     command_widget.onEditClicked()
        
        self.argument_counter += 1
        return command_widget
    
    def onAddArgumentWidget(self, argument_obj=None):
        """
        Add a widget with existing argument object.
        
        Args:
            argument_obj: Argument object to add
            
        Returns:
            The created widget
        """

        # create an empty argument parameter object
        # and pass it to the dialog
        module= get_cwl_module(self.cwl_version)
        ap=module.CommandLineBinding()
        dialog = ArgumentDialog(
            parent=self,
            argument_parameter=ap
        )

        # Composer adds the entry right away and opens it in the inspector
        inspector = Inspector.forWidget(self)
        if inspector is not None:
            argument_obj = dialog.getData()
            dialog.deleteLater()
            widget = self.addArgumentWidget(argument_obj)
            self.container_layout.update()
            self._emit_editing_finished()
            inspector.openEntry(argument_obj, QArgumentWidget)
            return widget
        
        dialog.show_next_to_main_window()
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            argument_obj = dialog.getData()
            self.logger.debug(f"Dialog returned: {argument_obj}")
            if argument_obj:
                # Only create widget if we have data
                widget = self.addArgumentWidget(argument_obj)
                # Force layout update after adding a widget
                self.container_layout.update()
                self._emit_editing_finished()
                return widget
            return None
        else:
            self.logger.debug("Dialog canceled, not creating widget")
            return None

    def removeArgumentWidget(self, widget):
        """
        Remove an argument widget from the container.
        
        Args:
            widget: Widget to remove
        """
        if widget in self.findChildren(QArgumentWidget):
            widget.setParent(None)
            widget.deleteLater()
            self._emit_editing_finished()
            self.logger.debug("Removed argument widget")

    def getData(self) -> List[Any]:
        """
        Get the data from all argument widgets.
        
        Returns:
            List of argument objects.
        """
        self.logger.debug("Retrieving updated data from argument widgets")
        contents = []
        for i in range(self.container_layout.count()):
            item = self.container_layout.itemAt(i)
            if (item and item.widget() and
                    isinstance(item.widget(), QArgumentWidget)):
                widget_data = item.widget().getData()
                if widget_data and 'argument' in widget_data:
                    contents.append(widget_data)
        
        self.logger.debug(f"Arguments group contains {len(contents)} items")
        return contents

    def clear(self, layout=None):
        """Clear all argument widgets and reset counter."""
        if not layout:
            layout = self.container_layout
        
        self.logger.debug("Clearing arguments widgets")
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item.layout() and item.layout() != layout:
                self.clear(item.layout())
            elif item.widget():
                item.widget().deleteLater()
        
        self.argument_counter = 0
        self.logger.debug("Arguments group cleared")
        super().clear()  # Clear self.cwl_tool via superclass

    def populateFromCWL(self, cwl_data: Optional[List[Any]] = None):
        """
        Populate with CWL Arguments.
        
        Args:
            cwl_data: List of argument objects
        """

        if cwl_data is None:    
            return
        self.clear()  # Clear existing widgets and reset counter
        
        # Set new data via superclass
        super().populateFromCWL(cwl_data)
        
        self.logger.debug(f"Populating arguments from CWL: {self.getCWL()}")
        
        current_arguments = self.getCWL()
        if current_arguments:
            self.logger.debug(f"Current inputs: {len(current_arguments)}")

            for argument_item in current_arguments:

                self.logger.debug(f"Adding argument item: {argument_item}")
                self.logger.debug(f"Current inputs: {type(argument_item).__name__}") 
                if type(argument_item).__name__ not in [
                    'CommandLineBinding',
                    'DoubleQuotedScalarString',
                    'str']:
                    self.logger.warning(
                        f"Expected CommandLineBinding, got {type(argument_item).__name__}"
                    )
                    continue
                if type(argument_item).__name__ in ['str','DoubleQuotedScalarString']:
                    module=get_cwl_module( self.cwl_version)
                    self.logger.info("Updating input to CommandLineBinding")
                    argument_item=module.CommandLineBinding(
                        valueFrom=argument_item
                    )
                self.addArgumentWidget(data=argument_item)


class QArgumentWidget(QCWLedWidget):
    """
    Widget for a single CWL Argument.
    Displays argument properties (prefix, valueFrom, position) and allows
    editing.
    """
    removeRequested = pyqtSignal(QWidget)

    def __init__(
        self,
        entry_order: int = 0,
        cwl_version: Optional[str] = None,
        parent: Optional[QWidget] = None,
        cwl_tool: Optional[Any] = None
    ):
        """
        Initialize an argument widget.
        
        Args:
            entry_order: Order of creation
            cwl_version: CWL version string
            parent: Parent widget
            cwl_tool: Argument object data
        """
        super().__init__(parent=parent, 
                         cwl_tool=cwl_tool, 
                         cwl_version=cwl_version
                         )
        
        self.entry_order = entry_order
        # Create a child logger with unique identifier
        self.logger = self.logger.getChild(f"arg.{self.entry_order}")
        self.logger.debug(
            f"Initialized. CWL version: {self.cwl_version}. "
            f"Initial data: {self.getCWL()}"
        )
        self.populateFields()

    def setCWL(self, cwl_tool: Optional[Any]):
        """
        Set the CWL argument object and update display fields.
        
        Args:
            cwl_tool: A CWL CommandLineBinding object
        """
        super().setCWL(cwl_tool)
        if self.default_value and type(self.default_value).__name__ != 'CommandLineBinding':
            self.logger.warning(
                f"Expected CommandLineBinding, got {type(self.default_value).__name__}"
            )
            self.default_value = None
        # self.populateFields()
        self._emit_editing_finished()

    def initUI(self):
        """Initialize the user interface."""
        super().initUI()

        # Initialize widgets
        self.line_edit_ID = QLineEdit(self)
        self.line_edit_ID.setText("ID")
        
        # Safely get configuration values with defaults
        input_window_config = data.configuration.get('input_window', {})
        
        id_width = input_window_config.get('id_width', 200)
        self.line_edit_ID.setFixedWidth(id_width)
        self.line_edit_ID.setReadOnly(True)

        self.line_edit_type = QLineEdit(self)
        self.line_edit_type.setText("Argument")
        
        type_width = input_window_config.get('type_width', 100)
        self.line_edit_type.setFixedWidth(type_width)
        self.line_edit_type.setReadOnly(True)

        self.line_edit_prefix = QLineEdit(self)
        self.line_edit_prefix.setPlaceholderText("Prefix")
        
        prefix_width = input_window_config.get('prefix_width', 100)
        self.line_edit_prefix.setFixedWidth(prefix_width)
        self.line_edit_prefix.setReadOnly(True)

        self.line_edit_argument = QLineEdit(self)
        self.line_edit_argument.setPlaceholderText("Argument Value")
        
        value_width = input_window_config.get('value_width', 200)
        self.line_edit_argument.setFixedWidth(value_width)
        self.line_edit_argument.setReadOnly(True)

        self.line_edit_order = QLineEdit(self)
        self.line_edit_order.setPlaceholderText("Order")
        
        order_width = input_window_config.get('order_width', 50)
        self.line_edit_order.setFixedWidth(order_width)
        self.line_edit_order.setReadOnly(True)

        # Create buttons using their correct constructor signature
        self.remove_button = QRemoveButton(self)
        self.edit_button = QEditButton(self)

        # Connect signals
        self.remove_button.clicked.connect(self.onRemoveClicked)
        self.edit_button.clicked.connect(self.onEditClicked)

        # Composer argument list entry: Value | Prefix | Separate | #
        # The whole bar opens the ArgumentDialog; ID and type are not shown.
        self.separate_label = QLabel(self)
        self.separate_label.setFont(theme.iconFont())
        self.row_bar = theme.ListRow(self)
        self.row_bar.addColumn(self.line_edit_argument, 4)
        self.row_bar.addColumn(self.line_edit_prefix, 3)
        self.row_bar.addColumn(self.separate_label, 3)
        self.row_bar.addColumn(self.line_edit_order, 2)
        self.row_bar.clicked.connect(self.onEditClicked)
        self._hidden_fields = QWidget(self)
        self._hidden_fields.hide()
        for hidden in (self.line_edit_ID, self.line_edit_type, self.edit_button):
            hidden.setParent(self._hidden_fields)
        theme.listRowLayout(self, self.row_bar, self.remove_button)
        
        # Update fields display
        # self.populateFields()

    @pyqtSlot()
    def onRemoveClicked(self):
        """Remove this widget when the remove button is clicked."""
        if self.parent():
            self.removeRequested.emit(self)
            self.setParent(None)
            self.deleteLater()
            self._emit_editing_finished()

    @pyqtSlot()
    def onEditClicked(self):
        """
        Open the ArgumentDialog to edit this argument.
        If we already have data, populate the dialog fields.
        """
        dialog = ArgumentDialog(parent=self, argument_parameter=self.getCWL())

        # In the tool editor the argument opens in the Composer object inspector
        inspector = Inspector.forWidget(self)
        if inspector is not None:
            inspector.inspect(self, dialog, lambda d: d.argument_edit.text() or d.prefix_edit.text() or "Argument")
            return

        # Position the dialog next to the main window
        dialog.show_next_to_main_window()

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get inputs from the dialog
            arguments = dialog.getData()
            self.logger.debug(f"Dialog returned: {arguments}")
            
            # Convert to CWL object and update widget
            self.setCWL(arguments)

        self.logger.debug("Edit button clicked, opening ArgumentDialog")


    def populateFields(self):
        """Update display fields from the current argument data."""
        arg = self.getCWL()
        if arg:
            self.logger.debug(f"Populating fields from argument: {arg}")
            self.line_edit_prefix.setText(arg.prefix or '')
            self.line_edit_argument.setText(arg.valueFrom or '')
            
            position_text = '0'
            if hasattr(arg, 'position') and arg.position is not None:
                position_text = str(arg.position)
            self.line_edit_order.setText(position_text)
            # CWL separates prefix and value unless separate is false
            separate = getattr(arg, 'separate', None) is not False
            self.separate_label.setText(theme.FA['check'] if separate else '')
        else:
            self.line_edit_prefix.setText('')
            self.line_edit_argument.setText('')
            self.line_edit_order.setText('0')
            self.separate_label.setText('')


    def clear(self):
        """Clear the argument data and display fields."""
        super().clear()  # This sets self.cwl_tool to None
        self.populateFields()
        self.logger.debug("Argument widget cleared")

    def getData(self) -> Optional[Dict[str, Any]]:
        """
        Get the argument data with metadata for sorting.
        
        Returns:
            Dictionary containing the argument object and metadata,
            or None if no data is available.
        """
        arg = self.getCWL()

        
        if not arg:
            return None
            
        return {
            'entry_order': self.entry_order,
            'order': arg.position if (hasattr(arg, 'position') and arg.position) else 0,
            'argument': arg
        }

