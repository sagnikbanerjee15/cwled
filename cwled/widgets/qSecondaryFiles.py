from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor,QFontMetrics

from pathlib import Path, PurePath
from CWLparser import Parser
import json
from markdown2 import markdown 
from configuration import Configuration
import builtins
import data
import data
import logging
from sanitizeName import sanitize
from typing import Union, Any, List, Optional
from helperFunctions import addArrayItem
from nested_lookup import nested_lookup, nested_update
from widgets.qLabelLineEditWidget import QLabelLineEditWidget
from widgets.qButtons import *
from widgets.QCWLedWidget import QCWLedWidget
from widgets.QCWLedGroupWidget import QCWLedGroupWidget
import sys
from cwl_utils_handler import get_cwl_module
from typing import Optional, Any
logger = logging.getLogger(__name__)

class QSecondaryFilesGroupWidget(QCWLedGroupWidget):
    # Define a custom signal to indicate that some information has changed
   
    def __init__(self, 
                 parent=None,
                 cwl_tool:Optional[List]=None,
                 cwl_version:Optional[str]=None):

        if parent is None:
            self.logger.critical("no parent provided to QSecondaryFilesGroupWidget")
            sys.exit(1)
        else:
            logger.debug(f"Parent provided to QSecondaryFilesGroupWidget: {parent.__class__.__name__}")

        if cwl_version is None and hasattr(parent, 'cwl_version'):
            cwl_version=getattr(parent, 'cwl_version')
            logger.debug(f"QSecondaryFilesGroupWidget Setting cwl_version from parent: {cwl_version}  ")
        super().__init__(
            parent=parent,
            cwl_tool=cwl_tool,
            cwl_version=cwl_version,
            widget_class=QSecondaryFiles,
            label="Secondary Files")
        logger.debug(f"QSecondaryFilesGroupWidget cwl_version is: {self.cwl_version}  ")
        

class QSecondaryFiles(QCWLedWidget):
    '''
    class to handle  a row of input for a basecommand
    param: entry_order : the order that this row was added (it is not shown on the UI)

    param: parent: the parent

    this class emits an editingFinished signal
    one can get the baseCommand, baseCommandOrder, baseCommandEntry using the named attributes
    '''
    # Define a custom signal to indicate that some information has changed
 
    def __init__(self, 
                 entry_order=0,
                 secondary_file:Optional[Any|str]=None,
                 cwl_version:Optional[str]=None,
                 parent=None):
        if parent is None:
            self.logger.critical("no parent provided to QSecondaryFiles")
            sys.exit(1)
        # else:
        #     print(f"Parent provided to QSecondaryFilesWidget: {parent.__class__.__name__}")

        if cwl_version is None and hasattr(parent, 'cwl_version'):
            cwl_version=getattr(parent, 'cwl_version')
        # print(f"QSecondaryFiles Setting cwl_version from parent: {cwl_version}  ")
        super().__init__(
            parent=parent, 
            cwl_tool=secondary_file,
            cwl_version=cwl_version
            
        )
        
        # self.logger=logging.getLogger(__name__)
        self.logger.setLevel('DEBUG')
        # self.entry_order=entry_order
        # if secondary_file:
        #     self.secondary_file=secondary_file.get('pattern')
        #     self.required=secondary_file.get('required',True)
        # self.initUI()
    
    def initUI(self):
        # Initialize widgets
        self.line_edit1 = QLineEdit(self)
        self.line_edit1.setPlaceholderText("extension")
        req=QLabel("Required")
        self.line_checkbox=QCheckBox(self)
        
        # Connect the remove button's clicked signal to the removeRequested signal
        self.line_edit1.editingFinished.connect(self.onTextChange)
        self.line_checkbox.stateChanged.connect(self.onStateChange)
        # Create a layout and add widgets to it
        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.line_edit1)
        layout.addWidget(req)
        layout.addWidget(self.line_checkbox)
        
        # Set the layout for the widget
        self.setLayout(layout)

    def setCWL(self, cwl_data: Optional[Any]=None):
        """
        Sets the CWL data for this secondary file widget.
        
        Args:
            cwl_data (Any): The CWL data object to set. Expected to be a
        """

        if (cwl_data  and 
            (not type(cwl_data).__name__ in ["SecondaryFileSchema",
                                             "str",
                                             "DoubleQuotedScalarString",
                                             "SingleQuotedScalarString"])):
            self.logger.critical(f"Expected SecondaryFileSchema or string, got {type(cwl_data).__name__}")

        super().setCWL(cwl_data)

    def populateFromCWL(self, 
                        cwl_data: Optional[Any] = None):
        super().populateFromCWL(cwl_data)    
        logger.debug(f"populateFromCWL called with cwl_data: {cwl_data}")
        logger.debug(f"Type of cwl_data: {type(cwl_data).__name__}")
        if type(cwl_data).__name__ == "SecondaryFileSchema":
            if hasattr( cwl_data, 'pattern'):
                self.line_edit1.setText( cwl_data.pattern)
            if hasattr( cwl_data, 'required'):
                if cwl_data.required is not None:
                    self.line_checkbox.setChecked( cwl_data.required)
                else:
                    self.line_checkbox.setChecked( True) # default to True if not specified
            else:
                self.line_checkbox.setChecked( True) # default to True if not specified
        elif type(cwl_data).__name__ in ["str","DoubleQuotedScalarString","SingleQuotedScalarString"]:
            self.line_edit1.setText( cwl_data)
            self.line_checkbox.setChecked( True)
            self.line_checkbox.setEnabled( False)

    @pyqtSlot()
    def onStateChange(self):
        pass


    @pyqtSlot()
    def onTextChange(self):
        self.editingFinished.emit()


    def getData(self):
        """
        Retrieves the secondary file data as a CWL SecondaryFileSchema object.
        
        Constructs and returns a SecondaryFileSchema object based on the
        current CWL version, containing the pattern and required flag from
        the widget's input fields.
        
        Returns:
            SecondaryFileSchema | str: If the CWL module supports SecondaryFileSchema,
                returns a SecondaryFileSchema object with pattern and required fields.
                Otherwise, returns just the pattern string.
        
        Note:
            Requires self.cwl_version to be set for proper CWL module resolution.
        """
        mod=get_cwl_module( self.cwl_version)
        pattern=self.line_edit1.text()
        required=self.line_checkbox.isChecked()
        if hasattr( mod, 'SecondaryFileSchema'):
            return mod.SecondaryFileSchema( pattern=pattern,
                                            required=required)
        else:
            return pattern

    def clear(self):
        """Clear all fields in this widget."""
        super().clear()  # Call base class method
        self.line_checkbox.setChecked(False)
        self.line_edit1.setText("")
        # self.writable_checkbox.setChecked(False)
    
# Application setup
if __name__ == "__main__" :


    conf=Configuration()
    conf.loadConfiguration( "commandLineWindow.yaml")#,"dataStructures.yaml"] )
    data.configuration=conf.getConfiguration()
    app = QApplication(sys.argv)
    tag_widget = QSecondaryFilesGroupWidget()
    tag_widget.show()

    tag_widget.populateFromCWL( [{"pattern":".bai"},{"pattern":"^bai"}])
    # Example usage to get tag values
    def print_tag_values():
        print("Tag values:", tag_widget.getData())

    # Print tag values after adding some tags
    print_tag_values()
    import time
    time.sleep(2)  # Allow some time for user interaction


    sys.exit(app.exec())
