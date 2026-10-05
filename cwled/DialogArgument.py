from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor,QFontMetrics
from copy import deepcopy
import json
import sys
import builtins
import logging
from widgets.qButtons import *
from JavascriptEditor import JavaScriptEditorDialog
import theme
from dataTypes import argument
from copy import deepcopy
from typing import Any, Tuple 
from CWLparser import Parser, is_array, is_optional_array, is_optional, get_type
from cwl_utils.parser import save
from cwl_utils_handler import get_cwl_module, get_cwl_version
from BaseDialog import BaseDialog
logger = logging.getLogger(__name__)

class ArgumentDialog(BaseDialog):
    """A dialog that collects user input for prefix, argument, position, and checkbox options.
    if the mode is argument it works for arguments
    if the mode is inputs it works for inputs
    if the mode is outputs it works for outputs
    """
    code=''
    codeUpdated = pyqtSignal() # emit this signal when the code is updated
    argument_parameter=None
    def __init__(self, 
                 parent=None, 
                 argument_parameter:Any=None,
                 cwl_version:str=None):
        super().__init__(parent)
        self.logger=logging.getLogger(__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(__name__, 'DEBUG'))
        # self.cwl_dict={}
        # self.logger.debug("Inside the ArgumentsDialog")
        if argument_parameter is not None and cwl_version is None:
            self.setCWLVersion(argument_parameter)
        elif cwl_version is not None:
            self.setCWLVersion(cwl_version)
        else:
            raise ValueError("Either input_parameter or cwl_version must be provided.")
        # self.data=deepcopy(argument)
        # if initialCode:
            # self.code=initialCode
        self.setWindowTitle(f"Arguments (cwl: {self.cwl_version})")
        self.initUI()
        if argument_parameter is not None:
            self.argument_parameter=argument_parameter
            self.setDefaults()

        self.setModal(True)  # Make the dialog modal (blocking interaction with main window)

    def initUI(self):
        layout = QVBoxLayout()

        # Create QLineEdit widgets for Prefix, Argument, and Position
        self.prefix_edit = QLineEdit(self)
        self.prefix_edit.setPlaceholderText("Prefix")

        self.argument_edit = QLineEdit(self)
        self.argument_edit.setPlaceholderText("Value")

        self.position_edit = QLineEdit(self)
        self.position_edit.setPlaceholderText("Position")

        # Create QCheckBox widgets
        # self.command_line_binding_check = QCheckBox("Command Line Binding", self)
        self.separate_value_and_prefix_check = QCheckBox("Separate Value and Prefix", self)
        self.separate_value_and_prefix_check.setChecked(True)
        self.shell_quote_check = QCheckBox("Shell Quote", self)
        self.shell_quote_check.setChecked(False)

        # Add widgets to layout
        layout.addWidget(QLabel("Prefix:"))
        layout.addWidget(self.prefix_edit)


        layout_in=QHBoxLayout()
        layout.addWidget(QLabel("Argument:"))
        code_button=QCodeButton()
        code_button.clicked.connect( lambda:self.onCodeEditor(self.argument_edit))
        # the </> button is attached to the value field (Composer input group)
        layout_in.addWidget(theme.InputGroup(self.argument_edit, code_button, parent=self))
        layout.addLayout(layout_in)
        

        layout.addWidget(QLabel("Position:"))
        layout.addWidget(self.position_edit)

        # layout.addWidget(self.command_line_binding_check) # not used for arguments
        layout.addWidget(self.separate_value_and_prefix_check)
        layout.addWidget(self.shell_quote_check)

        # Add OK/Cancel buttons
        self.button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.button_layout.addWidget(self.ok_button)
        self.button_layout.addWidget(self.cancel_button)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        layout.addStretch(1)
        layout.addLayout(self.button_layout)

        # Set the dialog layout
        self.setLayout(layout)

    def setCWLVersion(self, cwl_version: str):
        if not isinstance(cwl_version, str):
            self.cwl_version = get_cwl_version(cwl_version)
        else:
            self.cwl_version = cwl_version

    def set_prefix(self, value):
        self.prefix_edit.setText(value)

    def set_argument(self, value:str):
        self.argument_edit.setText(value)

    def set_position(self, value:int):
        self.position_edit.setText(str(value))

    def set_command_line_binding(self, value:bool):
        if hasattr(self, 'command_line_binding_check'):
            self.command_line_binding_check.setChecked(value)

    def setSeparateValuePrefix(self, value:bool):
        self.separate_value_and_prefix_check.setChecked(value)

    def set_shell_quote(self, value:bool):
        self.shell_quote_check.setChecked(value)

    def setDefaults(self):
        '''
        inputbinding according to
        https://www.commonwl.org/v1.2/CommandLineTool.html#CommandLineBinding
        '''
        self.logger.debug(f"ArgumenDialog received {type(self.argument_parameter)} {save(self.argument_parameter)}")
        # self.data=data

        self.set_prefix(self.argument_parameter.prefix)
        self.set_argument(self.argument_parameter.valueFrom)
        # show the values without changing the argument being edited
        self.set_position(self.argument_parameter.position or 0)
        # CWL separates prefix and value unless separate is explicitly false
        self.setSeparateValuePrefix(getattr(self.argument_parameter, 'separate', None) is not False)
        if hasattr(self.argument_parameter, 'shellQuote') and self.argument_parameter.shellQuote :
            self.set_shell_quote(self.argument_parameter.shellQuote)




    def onSelectionChanged( self ):
        '''
        what happens when we change the selection of the input type
        '''
        self.logger.debug(f"Selection changed to  {self.input_type.currentText()}")
        selected_option = self.input_type.currentText()
        if selected_option == "enum":
            self.add_enum_tag_widget()
        else:
            # Remove the enum widget if it's no longer needed
            if self.enum_widget:
                self.enum_widget.setParent(None)
                self.enum_widget = None


    

    def on_submit_tags(self):
        """
        Handle the event when the user submits the enum tags.
        Get the input from the QLineEdit and process the tags.
        """
        tags = self.tag_input.text().strip()
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",")]
            logger.debug(f"Submitted tags: {tag_list}")
        else:
            logger.debug("No tags entered.")

    def getData(self):
        """Return the values entered in the dialog.
        Create a CommandLine

        """
        
        module = get_cwl_module(self.cwl_version) 
        position = 0
        try:
            position = int(self.position_edit.text())
        except ValueError:
            self.logger.warning(
                f"Invalid position value: {self.position_edit.text()}, using 0"
            )
        # a value the user left unset is not written with its default, so the
        # argument stays as it was (shellQuote: false would change what a
        # ShellCommandRequirement tool runs)
        original = getattr(self, 'argument_parameter', None)

        def kept(name, value, unset_value):
            before = getattr(original, name, None) if original is not None and not isinstance(original, str) else None
            return None if before is None and value == unset_value else value

        argumentparameter = module.CommandLineBinding(
            position=kept('position', position, 0),
            prefix=self.prefix_edit.text() or None,
            separate=kept('separate', self.separate_value_and_prefix_check.isChecked(), True),
            shellQuote=kept('shellQuote', self.shell_quote_check.isChecked(), False)
        )
        if self.argument_edit.text():
            argumentparameter.valueFrom=self.argument_edit.text()
        return argumentparameter

    def onCodeEditor(self, widget_to_update=None):

         # Show the dialog
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.cwl_dict=self.argument_parameter
        if self.argument_edit.text():
            dialog.editor.setText( self.argument_edit.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            self.code = dialog.get_javascript_code()
            # print("JavaScript code submitted:", code)
            if self.code:
                widget_to_update.setText( self.code)
                self.codeUpdated.emit()

if __name__ == '__main__':
    app = QApplication(sys.argv)

    dialog = ArgumentDialog()
    if dialog.exec():
        print("Accepted")
    else:
        print("Rejected")

    sys.exit(app.exec())