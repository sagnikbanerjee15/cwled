from PyQt6.QtCore import (
    pyqtSignal, pyqtSlot
)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QCheckBox, QDialog,
    QPushButton, QLineEdit, QApplication, QLabel
)
import re
import data
import logging
import sys
from typing import Optional, Any, Dict

from JavascriptEditor import JavaScriptEditorDialog
import theme
from widgets.QCWLedWidget import QCWLedWidget
from .qButtons import QRemoveButton, QCodeButton
from cwl_utils_handler import get_cwl_module

# Define a constant for label width
LABEL_WIDTH = 100


class QInitialWorkDirGroup(QCWLedWidget):
    """
    A widget that manages a collection of QWorkDir instances representing
    files in the initial working directory for a CWL tool.
    """
    files_counter = 0

    def __init__(self, 
                 cwl_tool: Optional[Dict] = None, 
                 parent=None, 
                 cwl_version: Optional[str] = None):
        
        super().__init__(parent=parent, 
                         cwl_tool=cwl_tool, 
                         cwl_version=cwl_version)
        # if cwl_tool is not None:
        #     self.setCWL( cwl_tool)
        # logger and initUI are called in QCWLedWidget's __init__

    def initUI(self):
        # Use the common header with add button
        from .qHeader import HeaderWithAddButton
        self.header = HeaderWithAddButton("Working directory", self)
        self.header.addButtonClicked.connect(self.addWorkDirWidget)
        
        # Set up the layout
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
    
        # Set up the container layout for work dir widgets
        self.container_layout = QVBoxLayout()
        
        # Add header and container to the main layout
        self.layout.addWidget(self.header)
        self.layout.addLayout(self.container_layout)
        self.layout.addStretch(1)
        
        # Set the layout for the widget
        self.setLayout(self.layout)


    def setCWLVersion(self, cwl_version: Optional[str] = None):
        """
        Set the CWL version for this widget and its children.
        
        Args:
            cwl_version: CWL version string (e.g. 'v1.2')
        """
        super().setCWLVersion(cwl_version)
        
        # # Update version in all child argument widgets
        # if hasattr(self, 'container_layout'):
        #     for i in range(self.container_layout.count()):
        #         item = self.container_layout.itemAt(i)
        #         if (item and item.widget() and
        #                 isinstance(item.widget(), QInitialWorkDir)):
        #             widget = item.widget()
        #             if hasattr(widget, 'setCWLVersion'):
        #                 widget.setCWLVersion(cwl_version)
    

    @pyqtSlot()
    def onTextChange(self):
        self._emit_editing_finished()  # Use base class method

    @pyqtSlot()
    def addWorkDirWidget(self, working_directory: Optional[Dict] = None):
        """
        Add a new QWorkDir to the container.
        
        Args:
            working_directory: Optional dictionary with initial values
        """
        command_widget = QInitialWorkDir(
            entry_order=self.files_counter,
            working_directory=working_directory,
            cwl_version=self.cwl_version,
            parent=self
        )
        command_widget.editingFinished.connect(self.onTextChange)
        if working_directory:
            command_widget.populateFromCWL(working_directory)
        self.container_layout.addWidget(command_widget)
        
        self.files_counter += 1  # Increment counter when adding a widget

    def getData(self, *args: Any, **kwargs: Any) -> Dict:
        """
        Returns the data from all QWorkDir widgets as a CWL
        InitialWorkDirRequirement object.
        
        Returns:
            Dictionary representing an InitialWorkDirRequirement
        """
        contents = []
        for i in range(self.container_layout.count()):
            item = self.container_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if isinstance(widget, QInitialWorkDir):
                    contents.append(widget.getData())

        mod=get_cwl_module( self.cwl_version)
        return mod.InitialWorkDirRequirement(listing=contents)             
    
    def populateFromCWL(self, cwl_data: Optional[Any] = None):
        """
        Populates the widget with data from a CWL InitialWorkDirRequirement.
        
        Args:
            cwl_data: CWL object with 'listing' property
        """
        super().populateFromCWL(cwl_data)  # Call base class method
        
        # If we didn't get data, nothing to do
        if cwl_data is None:
            return
            
        self.logger.debug(f"Received commands {cwl_data} to add to the layout")
        self.files_counter = 0
        self.clear()

        if hasattr(cwl_data, 'listing'):
            for ev in cwl_data.listing:
                self.logger.debug(f"Adding working directory {ev}")
                self.addWorkDirWidget(working_directory=ev)

    def clear(self, layout=None):
        """
        Clears all QWorkDir widgets from the container.
        
        Args:
            layout: Optional layout to clear
        """
        super().clear()  # Call base class method
        
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
        self.files_counter = 0  # Reset counter when clearing


class QInitialWorkDir(QCWLedWidget):
    """
    Class to handle a row of input for a working directory.
    Represents a single file entry in the initial working directory.
    
    Emits editingFinished and codeUpdated signals when changes occur.
    """
    codeUpdated = pyqtSignal()

    def __init__(
        self,
        entry_order=0,
        working_directory: Optional[Any] = None,
        parent=None,
        cwl_version: Optional[str] = None
    ):
        self.entry_order = entry_order
        self.working_directory = working_directory
        super().__init__(parent=parent, cwl_tool=working_directory, cwl_version=cwl_version)
        # logger and initUI are called in QCWLedWidget's __init__
    
    def initUI(self):
        # Initialize widgets
        self.entry_edit_box = QLineEdit(self)
        self.entry_edit_box.setPlaceholderText("Filename or Contents of file")
        self.entryname_edit_box = QLineEdit(self)
        self.entryname_edit_box.setPlaceholderText("Target Filename")
        self.writable_checkbox = QCheckBox("Writable")
        
        if self.working_directory:
            self.populateFromCWL()
            # the entry could be just a string


        self.remove_button = QRemoveButton(parent=self)
        self.edit_button = QCodeButton(parent=self)
        
        # Connect signals
        self.remove_button.clicked.connect(self.onRemoveClicked)
        self.entry_edit_box.editingFinished.connect(self.onTextChange)
        self.entryname_edit_box.editingFinished.connect(self.onTextChange)
        self.edit_button.clicked.connect(
            lambda: self.onCodeEditor(self.entry_edit_box)
        )
        
        # Create a layout and add widgets to it
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        # the </> button is attached to the entry field it edits
        layout.addWidget(theme.InputGroup(self.entry_edit_box, self.edit_button, parent=self))
        layout.addWidget(self.entryname_edit_box)
        layout.addWidget(self.writable_checkbox)
        layout.addWidget(self.remove_button)
        
        # Set the layout for the widget
        self.setLayout(layout)

    @pyqtSlot()
    def onCodeEditor(self, widget_to_update=None):
        """
        Opens a JavaScript editor dialog for the entry field.
        
        Args:
            widget_to_update: The widget to update with the resulting code
        """
        # Show the dialog
        dialog = JavaScriptEditorDialog(parent=self)
        if hasattr(self, 'cwl_dict') and self.cwl_dict:
            dialog.cwl_dict = self.cwl_dict
        
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
        super().populateFromCWL(cwl_data)  # Call base class method
        
        if cwl_data is None:
            return
        
        if isinstance( self.working_directory, str):
            entry=self.working_directory
            entryname=""
            writable=False
        if re.search("Dirent", str(type( self.working_directory))):
            entry = self.working_directory.entry
            entryname = self.working_directory.entryname
            writable = self.working_directory.writable
        
        self.entry_edit_box.setText(entry)
        self.entryname_edit_box.setText(entryname)
        self.writable_checkbox.setChecked(writable)


    @pyqtSlot()
    def onRemoveClicked(self):
        """
        Remove this widget from its parent layout.
        """
        if self.parent():
            self.setParent(None)  # Remove widget from its parent layout
            self.hide()  # Hide the widget
            self.deleteLater()  # Schedule for deletion

    @pyqtSlot()
    def onTextChange(self):
        self._emit_editing_finished()  # Use base class method

    def getData(self, *args: Any, **kwargs: Any) -> Dict:
        """
        Returns the data from this widget as a dictionary.
        
        Returns:
            Dictionary with entry, entryname, and writable properties
        """

        if self.entryname_edit_box or self.writable_checkbox:
            # we will make a Dirent
            mod=get_cwl_module( self.cwl_version)
            dirent=mod.Dirent( 
                entry=self.entry_edit_box.text() if self.entry_edit_box else "",
                writable=self.writable_checkbox.isChecked() 
            )
            if hasattr(self, 'entryname_edit_box') and self.entryname_edit_box.text():
                dirent.entryname=self.entryname_edit_box.text()
            return dirent
        else:
            return self.entry_edit_box.text() 
        # return {
        #     'entry': self.entry_edit_box.text(),
        #     'entryname': self.entryname_edit_box.text(),
        #     'writable': self.writable_checkbox.isChecked()
        # }
        
    def clear(self):
        """Clear all fields in this widget."""
        super().clear()  # Call base class method
        self.entry_edit_box.setText("")
        self.entryname_edit_box.setText("")
        self.writable_checkbox.setChecked(False)


# Application setup
if __name__ == "__main__":
    logger = logging.getLogger('')
    from configuration import Configuration
    conf = Configuration()
    conf.loadConfiguration("commandLineWindow.yaml")
    data.configuration = conf.getConfiguration()
    app = QApplication(sys.argv)

    tag_widget = QInitialWorkDirGroup()
    tag_widget.show()
    mod=get_cwl_module( 'v1.2')

    le=mod.Dirent( entry="NAME", entryname="TEST", writable=True)
    i=mod.InitialWorkDirRequirement(listing=[le])
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
