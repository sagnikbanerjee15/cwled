from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel
)
from typing import List, Dict, Any, Optional, Union
from .qButtons import QRemoveButton
from widgets.QCWLedWidget import QCWLedWidget
from widgets.QCWLedGroupWidget import QCWLedGroupWidget
from helperFunctions import traverseCWLversion 
import logging
logger = logging.getLogger(__name__)

class QBaseCommandGroupWidget(QCWLedGroupWidget):
    '''
    This is the widget that shows a group of command line arguments.
    It manages a list of command entries.

    When data changes in any row it emits the editingFinished signal.
    The data can be retrieved with the getData function
    which returns a list of command strings.
    '''
    command_counter = 0
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        cwl_tool: Optional[Union[str|List[str]]] = None,
        cwl_version: Optional[str] = None
    ):
        """
        Initialize the base command group widget.
        
        Args:
            parent: Parent widget
            cwl_tool: List of command strings
            cwl_version: Version of the CWL specification
        """
        super().__init__(parent=parent, 
                         cwl_tool=cwl_tool, 
                         cwl_version=cwl_version,
                         widget_class=QBaseCommandWidget,
                         label="Commands")

    

    @pyqtSlot()
    def addWidget(self, 
                  cwl_data: Optional[str] = None):
        """
        Add a new QBaseCommandWidget to the container.
        
        Args:
            command: Optional command string to initialize the widget with
        """
        logger.debug(f"Adding new command widget with data: {cwl_data}")
        self.logger.debug(
            f"Adding a new Command widget with command: {cwl_data}"
        )
        super().addWidget(
            cwl_data=cwl_data,
            entry_order=self.command_counter,
            parent=self,
            cwl_version=self.cwl_version
        )
        self.command_counter += 1
    

    def getData(self) -> List[str]:
        """
        Get the data from all command widgets.
        
        Returns:
            List of command strings.
        """
        self.logger.debug("Requesting an update from command rows")
        contents = super().getData()
        
        self.logger.debug(f"Commands group contains {len(contents)} items")
        return contents

    # this implements the setCWLVersion function
    # without calling hte parental class
    # because baseCommand does not have a cwl version on its own
    def setCWLVersion(self, cwl_version: str=None):
        """
        Traverse the hierarchy of parent objects
        until we find the an object that has a
        CWL version set, and set that version
        for this widget and all its children.

        This happens because the baseCommand
        does not have a cwl version on its own,
        
        """
        # print(f"Traversing objects found {self.cwl_version}")
        self.cwl_version = traverseCWLversion(self)

class QBaseCommandWidget(QCWLedWidget):
    '''
    Widget for a single command entry.
    Displays command string and order.
    
    param: entry_order: The order this row was added (not shown in UI)
    param: parent: The parent widget
    param: cwl_tool: The command string
    
    Emits editingFinished signal when data changes.
    '''
    
    def __init__(
        self,
        entry_order: int = 0,
        parent: Optional[QWidget] = None,
        command: Optional[str] = None,
        cwl_version: Optional[str] = None
    ):
        """
        Initialize a base command widget.
        
        Args:
            entry_order: Order of creation
            parent: Parent widget
            cwl_tool: Command string
            cwl_version: Version of the CWL specification
        """
        super().__init__(parent=parent, 
                         cwl_tool=command, 
                         cwl_version=cwl_version)
        
        self.entry_order = entry_order
        # Create a child logger with unique identifier
        self.logger = self.logger.getChild(f"cmd.{entry_order}")
        self.logger.debug(f"Initialized with command: {self.getCWL()}")

    def initUI(self):
        """Initialize the user interface."""
        super().initUI()
        
        # Create a layout and add widgets to it
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Initialize widgets
        self.line_command = QLineEdit(self)
        self.line_command.setPlaceholderText("Command")
        
        # Set text if we have a command
        if self.getCWL():
            self.populateFromCWL()
            
        self.line_order = QLineEdit(self)
        self.line_order.setPlaceholderText("Order")
        self.line_order.setFixedWidth(36)
        self.line_order.setText('0')
        
        self.line_command.editingFinished.connect(self._emit_editing_finished)
        self.line_order.editingFinished.connect(self._emit_editing_finished)
        
        # Add widgets to layout. Like Composer, the commands are listed in
        # order and the order field is not shown.
        layout.addWidget(self.line_command)
        layout.addWidget(self.line_order)
        self.line_order.hide()
        
        # Set the layout for the widget
        self.setLayout(layout)

    def populateFromCWL(self, 
                        cwl_data: Optional[str] = None):
        
        logger.debug(f"Populating command widget from CWL data: {cwl_data}")
        super().populateFromCWL(cwl_data)
        logger.debug(f"after super populateFromCWL, cwl_tool is: {self.cwl_tool}   ")
        self.line_command.setText(cwl_data)

    def setCWL(self, cwl_tool: Optional[str]):
        """
        Set the command string and update UI.
        
        Args:
            cwl_tool: Command string
        """
        if not isinstance(cwl_tool, str) and cwl_tool is not None:
            self.logger.critical(
                f"Expected command to be a string, got {type(cwl_tool).__name__}"
            )
            return
        super().setCWL(cwl_tool)
        
        # Update UI if it's initialized
        # if hasattr(self, 'line_command') and self.line_command:
        #     current_text = self.line_command.text()
        #     new_text = cwl_tool or ""
        #     if current_text != new_text:
        #         self.line_command.setText(new_text)

    def getData(self) -> Dict[str, Any]:
        """
        Get the command data with metadata.
        
        Returns:
            Dictionary with command string and metadata.
        """
        try:
            line_order = int(self.line_order.text())
        except (ValueError, TypeError):
            line_order = 0
            
        return {
            "command": self.line_command.text(),
            "order": line_order,
            "entry_order": self.entry_order
        }
    
    def clear(self):
        """Clear all fields in this widget."""
        super().clear()  # Call base class method
        self.line_command.setText("")
        self.line_order.setText("0")