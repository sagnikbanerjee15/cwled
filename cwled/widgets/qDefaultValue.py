from PyQt6.QtCore import (
    pyqtSignal, pyqtSlot
)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QDialog, QLineEdit, QApplication,
    QCheckBox, QComboBox
)
import sys
import os
import logging
from typing import Optional, Any, Dict, List, Union
from helperFunctions import traverseCWLversion
# Add parent directory to path to import data module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data

from JavascriptEditor import JavaScriptEditorDialog
import theme
from widgets.QCWLedWidget import QCWLedWidget
from widgets.QCWLedGroupWidget import QCWLedGroupWidget
from .qButtons import QRemoveButton, QCodeButton
from cwl_utils_handler import get_cwl_module

# Define a constant for label width
LABEL_WIDTH = 100


class QDefaultValueGroupWidget(QCWLedGroupWidget):
    """
    A widget that manages a collection of DefaultValue instances representing
    We use a GroupWidget for the case that we have multiple values,
    however the widget assumes that all values are of the same type
    Note that in order for this to work we need to call teh 
    populatedFromCWL() after the object is initialized.
    """

    def __init__(self, 
                 default_value: Optional[str] = None, 
                 parent=None, 
                 cwl_version: Optional[str] = None,
                 input_type: Union[List[str],str] = None,
                 array: bool=True,
                 enum_list:Optional[List[str]]=None
    ):

        """
        if array is set to False, the widget will show a single entry for the
        default value, without the capabilities to add more entries.
        """
        super().__init__(parent=parent, 
                         cwl_tool=default_value, 
                         cwl_version=cwl_version,
                         widget_class=QDefaultValueWidget,
                         label="Default Value"
                         )
        self.files_counter = 0

        # if cwl_tool is not None:
        #     self.setCWL( cwl_tool)
        self.array=array
        if isinstance(input_type, list):
            self.input_type = [item for item in input_type if item != 'null']
            if len( self.input_type )> 1: 
                raise ValueError( f"The input type contains many values {self.input_type}, but it must contain only one.")
            self.input_type = self.input_type[0]
        else:
            self.input_type=input_type
        
        if enum_list:
            self.enum_list=enum_list
        else:
            self.enum_list=None
        # logger and initUI are called in QCWLedWidget's __init__
        if default_value: 
            self.default_value=default_value
        
        




    def getData(self, *args: Any, **kwargs: Any) -> Dict:
        """
        Returns the data from all QDefaultValueWidget widgets as a CWL
        InitialWorkDirRequirement object.
        
        Returns:
            Dictionary representing an InitialWorkDirRequirement
        """
        # print(f"getting data from the GroupWidget")
        contents = super().getData()

        if not self.array and contents:
            return contents[0]  
        else:
            return contents     
    
    

    @pyqtSlot()
    def addWidget(
        self, 
        cwl_data: Optional[Any] = None
        ):
        """
        Add a new QDefaultValue to the container.
        
        Args:
            cwl_data: Optional dictionary with initial values
        """
        # print(f"###### Adding new Widget {default_value}, {input_type}, {enum_list}")
        super().addWidget(
            cwl_data=cwl_data,
            entry_order=self.files_counter,
            parent=self,
            cwl_version=self.cwl_version,
            array=self.array,
            input_type=self.input_type,
            enum_list=self.enum_list

        )

        self.files_counter += 1  # Increment counter when adding a widget

    # this implements the setCWLVersion function
    # without calling hte parental class
    # because default does not have a cwl version on its own
    def setCWLVersion(self, cwl_version: str=None):
        """
        Traverse the hierarchy of parent objects
        until we find the an object that has a
        CWL version set, and set that version
        for this widget and all its children.

        This happens because the baseCommand
        does not have a cwl version on its own,
        
        """
        self.cwl_version = traverseCWLversion(self)

class QDefaultValueWidget(QCWLedWidget):
    """
    Class to handle a row of default value.
    Represents a single file entry in the default values.
    
    Emits editingFinished and codeUpdated signals when changes occur.

    We need to call the populateFromCWL after the object has been created
    """
    codeUpdated = pyqtSignal()

    default_value=None
    array=None
    input_type=None
    enum_list=None
    def __init__(
        self,
        entry_order=0,
        default_value: Optional[Any] = None,
        parent=None,
        cwl_version: Optional[str] = None,
        array:bool=True,
        input_type='string',
        enum_list:Optional[List[str]]=None
    ):
        self.entry_order = entry_order
        self.default_value = default_value
        self.array=array
        self.input_type=input_type
        if enum_list:
            self.enum_list=enum_list
        # print(f"********* The single value {self.default_value} ({self.input_type} with list {self.enum_list})")    
        super().__init__(parent=parent, cwl_tool=default_value, cwl_version=cwl_version)
        
        # logger and initUI are called in QCWLedWidget's __init__
    
    def initUI(self):
        # Initialize widgets
        if self.input_type in ['bool','boolean','logical']:
            self.defaultValue_edit_box = QComboBox(self)
            self.defaultValue_edit_box.addItems(['-- None --','True','False'])
            self.defaultValue_edit_box.currentIndexChanged.connect(self._emit_editing_finished)
        elif self.input_type == 'enum':
            self.defaultValue_edit_box = QComboBox(self)
            if self.enum_list:
                if not '-- None --' in self.enum_list:
                    self.enum_list.insert(0, '-- None --')
                self.defaultValue_edit_box.addItems(self.enum_list)
            self.defaultValue_edit_box.currentIndexChanged.connect(self._emit_editing_finished)
        else:
            self.defaultValue_edit_box = QLineEdit(self)
            self.defaultValue_edit_box.setPlaceholderText("Value")
            self.defaultValue_edit_box.editingFinished.connect(self._emit_editing_finished)
        
        # if self.default_value:
        #     self.populateFromCWL()
            # the entry could be just a string


        self.edit_button = QCodeButton(parent=self)
        
        self.edit_button.clicked.connect(
            lambda: self.onCodeEditor(self.defaultValue_edit_box)
        )
        
        # Create a layout and add widgets to it
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        # the </> button is attached to the value field
        layout.addWidget(theme.InputGroup(self.defaultValue_edit_box, self.edit_button, parent=self))
        # Set the layout for the widget
        self.setLayout(layout)
        self.populateFromCWL()

    @pyqtSlot()
    def onCodeEditor(self, widget_to_update=None):
        """
        Opens a JavaScript editor dialog for the entry field.
        
        Args:
            widget_to_update: The widget to update with the resulting code
        """
        # Show the dialog
        dialog = JavaScriptEditorDialog(parent=self)
        
        if widget_to_update and widget_to_update.text():
            dialog.editor.setText(widget_to_update.text())
            
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            code = dialog.get_javascript_code()
            if code and widget_to_update is not None:
                widget_to_update.setText(code)
                self.codeUpdated.emit()
                self._emit_editing_finished()  # Use base class method
                
    def populateFromCWL(self, cwl_data: Optional[Any] = None):
        """
        Populates the widget with data from a CWL working directory entry.
        
        Args:
            cwl_data: Dictionary with entry, entryname, and writable properties
        """
        # print(f" The default value is {self.default_value}")
        super().populateFromCWL(cwl_data)  # Call base class method
        # print(f" The default value is {self.default_value}")
        # if cwl_data is None:
        #     return
        if self.input_type == 'enum':
            if not self.default_value :
                self.defaultValue_edit_box.setCurrentText('-- None --')
            else:
                self.defaultValue_edit_box.setCurrentText(str(self.default_value))
            # print(f" Setting the combobox default to {str(self.default_value)}")
            # sys.exit(234)
        elif self.input_type in ['bool','boolean','logical']:
            if self.default_value is None:
                self.defaultValue_edit_box.setCurrentText('-- None --')
            if self.default_value in [True, 'true', 'True', 1, '1']:
                self.defaultValue_edit_box.setCurrentText('True')
            if self.default_value in [False, 'false', 'False', 0, '0']:
                self.defaultValue_edit_box.setCurrentText('False')
        else:
            if self.default_value is None:
                self.default_value=""
            else:
                self.defaultValue_edit_box.setText(str(self.default_value))



    def getData(self, *args: Any, **kwargs: Any) -> Dict:
        """
        Returns the data from this widget as a string.
        
        Returns:
            Dictionary with entry, entryname, and writable properties
        """
        if self.input_type in ['bool', 'boolean', 'logical']:
            if self.defaultValue_edit_box.currentText() == '-- None --':
                return None
            if self.defaultValue_edit_box.currentText() == 'True':
                return True
            if self.defaultValue_edit_box.currentText() == 'False':
                return False
        elif self.input_type == 'enum':
            if self.defaultValue_edit_box.currentText() == '-- None --':
                return None
            return self.defaultValue_edit_box.currentText()
        else:
            if self.defaultValue_edit_box.text() == '':
                return None
            if self.input_type in ['int','long']:
                return int(self.defaultValue_edit_box.text())
            if self.input_type in ['double','float']:
                return float(self.defaultValue_edit_box.text())
            else:
                return self.defaultValue_edit_box.text() 

        
    def clear(self):
        """Clear all fields in this widget."""
        super().clear()  # Call base class method
        if self.input_type in ['bool', 'boolean', 'logical']:
            self.defaultValue_edit_box.setChecked(False)
        elif self.input_type == 'enum':
            self.defaultValue_edit_box.setCurrentIndex(0)
        else:
            self.defaultValue_edit_box.setText("")


# Application setup

if __name__ == "__main__":
    logger = logging.getLogger('')
    from configuration import Configuration
    conf = Configuration()
    conf.loadConfiguration("config.yaml")
    data.configuration = conf.getConfiguration()
    app = QApplication(sys.argv)

    # tag_widget = QDefaultValueGroupWidget( array=True)
    # tag_widget.show()
    mod=get_cwl_module( 'v1.2')

    # test_data = ['def1','def2']
    # tag_widget.populateFromCWL(test_data)
    
    # # Example usage to get tag values
    # def print_tag_values():
    #     print("Tag values:", tag_widget.getData())



    # # Print tag values after adding some tags
    # print_tag_values()
    # tag_widget = QDefaultValueGroupWidget( 
    #         cwl_tool=True, 
    #         array= False,
    #         input_type='boolean'
    #     )
    # tag_widget.show()
    # print("Tag values:", tag_widget.getData())


    # tag_widget = QDefaultValueGroupWidget( 
    #         cwl_tool='one', 
    #         array= False,
    #         input_type='enum',
    #         enum_list=['one','two','three']
    #     )
    # tag_widget.show()
    # print("Tag values:", tag_widget.getData())

    tag_widget = QDefaultValueGroupWidget( 
            cwl_tool='test_string', 
            array= False,
            input_type='string'
        )
    tag_widget.show()
    print("Tag values:", tag_widget.getData())
    import time
    time.sleep(2)  # Allow some time for user interaction

    sys.exit(app.exec())
