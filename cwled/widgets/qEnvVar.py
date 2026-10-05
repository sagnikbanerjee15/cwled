from PyQt6.QtCore import (
    pyqtSignal, pyqtSlot
)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QCheckBox, QDialog,
    QPushButton, QLineEdit, QApplication, QLabel
)
import data
import logging
import sys
from typing import Optional, Any, Dict, List
from .qButtons import QCodeButton
from widgets.QCWLedWidget import QCWLedWidget
from widgets.QCWLedGroupWidget import QCWLedGroupWidget
from cwl_utils_handler import get_cwl_module
from JavascriptEditor import JavaScriptEditorDialog
import theme

# Define a constant for label width
LABEL_WIDTH = 100

from PyQt6.QtCore import QObject, QEvent
logger = logging.getLogger(__name__)

class FocusDebugger(QObject):
    def eventFilter(self, obj, event):
        if event.type() in [QEvent.Type.FocusIn, QEvent.Type.FocusOut, 
                            QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate]:
            logger.debug(f"Focus event: {event.type().name} on {obj.__class__.__name__}")
        return False

class QEnvVarGroupWidget(QCWLedGroupWidget):
    """
    A widget that manages a collection of QEnvVar instances representing
    environment variables for a CWL tool.
    """
    def __init__(self, 
                 cwl_tool: Optional[Dict] = None, 
                 parent=None, 
                 cwl_version: Optional[str] = None):
        # if cwl_tool is not None:
        #     self.setCWL( cwl_tool)
        super().__init__(parent=parent,
                         cwl_tool=cwl_tool,
                         cwl_version=cwl_version,
                         widget_class=QEnvVar,
                         label="Environment Variables")
        # logger and initUI are called in QCWLedWidget's __init__
    
    def makeList(self) -> List[Any]:
        """
        Return the list of env variables
        which are in the attribute envDef .
        """
        return self.getCWL().envDef 

    def setCWL(self, cwl_data: Optional[Any] = None):
        """
        Sets the CWL data for this widget.
        
        Args:
            cwl_data: The CWL data to set
        """
        if cwl_data  and not type(cwl_data).__name__ == "EnvVarRequirement":
            self.logger.critical(f"Expected EnvVarRequirement, got {type(cwl_data).__name__}")

        super().setCWL(cwl_data)

    def getData(self):
        """
        Returns a list of environment variable definitions from the child widgets.
        
        Returns:
            List of environment variable definitions
        """
        contents=super().getData() # this retuns a list of the child widget data
        mod=get_cwl_module( self.cwl_version)
        return mod.EnvVarRequirement(envDef=contents)
        

class QEnvVar(QCWLedWidget):
    """
    Class to handle a row of input for a working directory.
    Represents a single file entry in the initial working directory.
    
    Emits editingFinished and codeUpdated signals when changes occur.
    """
    codeUpdated = pyqtSignal() # emit it when JS code is updated
    def __init__(
        self,
        parent=None,
        cwl_version: Optional[str] = None,
        env_variable: Optional[Any] = None
    ):

        # self.env_variable = env_variable
        super().__init__(parent=parent, 
                         cwl_tool=env_variable, 
                         cwl_version=cwl_version)
        # logger and initUI are called in QCWLedWidget's __init__
    
    def initUI(self):
        # Initialize widgets
        super().initUI()

        self.envName_edit_box = QLineEdit(self)
        self.envName_edit_box.setPlaceholderText("Name")
        self.envValue_edit_box = QLineEdit(self)
        self.envValue_edit_box.setPlaceholderText("Value")
        self.code_button = QCodeButton(parent=self)
        self.code_button.clicked.connect(
            self.onCodeEditor)
        self.envName_edit_box.editingFinished.connect(self._emit_editing_finished)
        self.envValue_edit_box.editingFinished.connect(self._emit_editing_finished)
        
        # Create a layout and add widgets to it
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.envName_edit_box)
        # the </> button is attached to the value field it edits
        layout.addWidget(theme.InputGroup(self.envValue_edit_box, self.code_button, parent=self))
        
        # Set the layout for the widget
        self.setLayout(layout)
        if self.cwl_tool:
            self.populateFromCWL()

    def onCodeEditor(self, widget_to_update=None):
        """
        Opens a JavaScript editor dialog for the entry field.
        Args:
            widget_to_update: The widget to update with the resulting code
        """
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.editor.setText(self.envValue_edit_box.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            code = dialog.get_javascript_code()
            if code is not None:
                self.envValue_edit_box.setText(code)
                self.codeUpdated.emit()
                self._emit_editing_finished()  # Use base class method


    def populateFromCWL(self, cwl_data: Optional[Any] = None):
        """
        Populates the widget with data from a CWL working directory entry.
        
        Args:
            cwl_data: Dictionary with entry, entryname, and writable properties
        """
        super().populateFromCWL(cwl_data)  # Call base class method
        
        if cwl_data is None:
            return
        self.envName_edit_box.setText(self.getCWL().envName)
        self.envValue_edit_box.setText(self.getCWL().envValue)

    def setCWL(self, cwl_data: Optional[Any] = None):
        """
        Sets the CWL data for this widget.
        
        Args:
            cwl_data: The CWL data to set
        """
        if cwl_data  and not type(cwl_data).__name__ == "EnvironmentDef":
            self.logger.critical(f"Expected EnvironmentDef, got {type(cwl_data).__name__}")

        super().setCWL(cwl_data)
        
   
    def getData(self, *args: Any, **kwargs: Any) -> Dict:
        """
        Returns the data from this widget as a dictionary.
        
        Returns:
            Dictionary with entry, entryname, and writable properties
        """

        if self.envValue_edit_box or self.writable_checkbox:
            # we will make a Dirent
            mod=get_cwl_module( self.cwl_version)
            dirent=mod.EnvironmentDef( envName=self.envName_edit_box.text(),
                               envValue=self.envValue_edit_box.text() )
            return dirent
        else:
            return self.envName_edit_box.text() 
        # return {
        #     'entry': self.entry_edit_box.text(),
        #     'entryname': self.entryname_edit_box.text(),
        #     'writable': self.writable_checkbox.isChecked()
        # }
        
    def clear(self):
        """Clear all fields in this widget."""
        super().clear()  # Call base class method
        self.envName_edit_box.setText("")
        self.envValue_edit_box.setText("")
        # self.writable_checkbox.setChecked(False)


# Application setup
if __name__ == "__main__":
    logger = logging.getLogger('')
    from configuration import Configuration
    conf = Configuration()
    conf.loadConfiguration("commandLineWindow.yaml")
    data.configuration = conf.getConfiguration()
    app = QApplication(sys.argv)

    tag_widget = QEnvVarGroupWidget()
    tag_widget.show()
    mod=get_cwl_module( 'v1.2')

    le=mod.EnvironmentDef( envName="NAME", envValue="TEST")
    i=mod.EnvVarRequirement(envDef=[le])
    test_data = i
    tag_widget.populateFromCWL(test_data)
    
    # Example usage to get tag values
    def print_tag_values():
        print("Tag values:", tag_widget.getData())

    # Print tag values after adding some tags
    print_tag_values()
    import time
    time.sleep(2)  # Allow some time for user interaction

    sys.exit(app.exec())
