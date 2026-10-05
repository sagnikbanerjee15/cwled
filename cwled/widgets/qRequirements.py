from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QCheckBox, QDialog
)
from PyQt6.QtCore import pyqtSignal
from .qLabelLineEditWidget import QLabelLineEditWidget
from .qButtons import QCodeButton
import json
from JavascriptEditor import JavaScriptEditorDialog
import theme
from cwl_utils_handler import get_cwl_module
from typing import Any, Optional, List  # Import Optional and List
from widgets.QCWLedWidget import QCWLedWidget  # Import the base class


class QResourceRequirementsWidget(QCWLedWidget):
    """
    Widget for editing CWL resource requirements like RAM and CPU cores.
    """
    min_memory_requirement = ''
    min_cores_requirement = ''
    codeUpdated = pyqtSignal()

    def __init__(self, cwl_dict: Optional[dict] = None, parent=None, cwl_version: Optional[str] = None):
        super().__init__(parent=parent, cwl_tool=cwl_dict, cwl_version=cwl_version)
        self.cwl_dict = cwl_dict if cwl_dict is not None else {}
        # initUI() is called in QCWLedWidget's __init__

    def initUI(self):
        self.comp_layout = QVBoxLayout()
        self.comp_layout.setContentsMargins(0, 0, 0, 0)
        self.comp_layout.setSpacing(0)

        min_memory_layout = QHBoxLayout()
        min_memory_layout.setContentsMargins(0, 0, 0, 0)
        self.line_edit_min_memory = QLabelLineEditWidget(
            label_text="Min memory",
            placeholder_text="Minimum RAM (MB)",
            parent=self
        )
        min_memory_button = QCodeButton(self)
        min_memory_button.clicked.connect(
            lambda: self.onCodeEditor(self.line_edit_min_memory)
        )
        self.line_edit_min_memory.attachButton(min_memory_button)
        min_memory_layout.addWidget(self.line_edit_min_memory)
        self.line_edit_min_memory.editingFinished.connect(self.onTextChanged)
    
        max_memory_layout = QHBoxLayout()
        max_memory_layout.setContentsMargins(0, 0, 0, 0)
        self.line_edit_max_memory = QLabelLineEditWidget(
            label_text="Max memory",
            placeholder_text="Maximum RAM (MB)",
            parent=self
        )
        max_memory_button = QCodeButton(self)
        max_memory_button.clicked.connect(
            lambda: self.onCodeEditor(self.line_edit_max_memory)
        )
        self.line_edit_max_memory.attachButton(max_memory_button)
        max_memory_layout.addWidget(self.line_edit_max_memory)
        self.line_edit_max_memory.editingFinished.connect(self.onTextChanged)

        min_cores_layout = QHBoxLayout()
        min_cores_layout.setContentsMargins(0, 0, 0, 0)
        self.line_edit_min_cores = QLabelLineEditWidget(
            label_text="Min cores",
            placeholder_text="Minimum Cores",
            parent=self
        )
        min_cores_button = QCodeButton(self)
        min_cores_button.clicked.connect(
            lambda: self.onCodeEditor(self.line_edit_min_cores)
        )
        self.line_edit_min_cores.attachButton(min_cores_button)
        min_cores_layout.addWidget(self.line_edit_min_cores)
        self.line_edit_min_cores.editingFinished.connect(self.onTextChanged)
    
        max_cores_layout = QHBoxLayout()
        max_cores_layout.setContentsMargins(0, 0, 0, 0)
        self.line_edit_max_cores = QLabelLineEditWidget(
            label_text="Max cores",
            placeholder_text="Maximum Cores",
            parent=self
        )
        max_cores_button = QCodeButton(self)
        max_cores_button.clicked.connect(
            lambda: self.onCodeEditor(self.line_edit_max_cores)
        )
        self.line_edit_max_cores.attachButton(max_cores_button)
        max_cores_layout.addWidget(self.line_edit_max_cores)
        self.line_edit_max_cores.editingFinished.connect(self.onTextChanged)


        # a gap between the two columns, now that the </> buttons are attached
        memory_layout= QHBoxLayout()
        memory_layout.setContentsMargins(0, 0, 0, 0)
        memory_layout.setSpacing(theme.SECTION_SPACING)
        memory_layout.addLayout(min_memory_layout)
        memory_layout.addLayout(max_memory_layout)

        cores_layout = QHBoxLayout()
        cores_layout.setContentsMargins(0, 0, 0, 0)
        cores_layout.setSpacing(theme.SECTION_SPACING)
        cores_layout.addLayout(min_cores_layout)
        cores_layout.addLayout(max_cores_layout)
        self.comp_layout.addLayout(cores_layout)
        self.comp_layout.addLayout(memory_layout)

        self.setLayout(self.comp_layout)

    def onCodeEditor(self, widget_to_update=None):
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.cwl_dict = self.cwl_dict
        if widget_to_update and widget_to_update.text():
            dialog.editor.setText(widget_to_update.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            code = dialog.get_javascript_code()
            if code and widget_to_update is not None:
                widget_to_update.setText(code)
                self.codeUpdated.emit()
                self._emit_editing_finished()  # Use the base class method

    def onTextChanged(self):
        """
        Handle text changes in the memory or cores line edits.
        Emits a signal to indicate that the editing has finished.
        """
        self._emit_editing_finished()

    def populateFromCWL(self, cwl_data: Optional[Any] = None):
        """
        Populate this widget from a CWL ResourceRequirement object.
        
        Args:
            cwl_data: A CWL ResourceRequirement object
        """
        super().populateFromCWL(cwl_data)  # Call base class method
        
        # If we didn't get data, nothing to do
        if cwl_data is None:
            return
            
        self.logger.debug(
            f"Received data {json.dumps(cwl_data, indent=3, default=str)}"
        )
        if hasattr(cwl_data, 'ramMin') and cwl_data.ramMin is not None:
            self.line_edit_min_memory.setText(str(cwl_data.ramMin))
        if hasattr(cwl_data, 'coresMin') and cwl_data.coresMin is not None:
            self.line_edit_min_cores.setText(str(cwl_data.coresMin))
        if hasattr(cwl_data, 'ramMax') and cwl_data.ramMax is not None:
            self.line_edit_max_memory.setText(str(cwl_data.ramMax))
        if hasattr(cwl_data, 'coresMax') and cwl_data.coresMax is not None:
            self.line_edit_max_cores.setText(str(cwl_data.coresMax))

    def getData(self, cwlVersion: Optional[str] = None) -> Optional[Any]:
        """
        Create and return a CWL ResourceRequirement object based on widget
        data.
        
        Args:
            cwlVersion: CWL version to use for creating the requirement
            
        Returns:
            A CWL ResourceRequirement object or None if no requirements are set
            
        Raises:
            Exception: If cwlVersion is not provided
        """
        if not cwlVersion:
            raise Exception(
                "cwlVersion is required to create the ResourceRequirement"
            )
        ram_min_text = self.line_edit_min_memory.text()
        ram_max_text = self.line_edit_max_memory.text()
        cores_min_text = self.line_edit_min_cores.text()
        cores_max_text = self.line_edit_max_cores.text()

        if not (ram_min_text or cores_min_text or ram_max_text or cores_max_text):
            return None

        cwl_module = get_cwl_module(cwlVersion)
        resource_req = cwl_module.ResourceRequirement(
            
        )
        if ram_min_text:
            if ram_min_text.startswith('$'):    
                resource_req.ramMin = ram_min_text 
            else:
                resource_req.ramMin = float( ram_min_text )
        if ram_max_text:
            if ram_max_text.startswith('$'):    
                resource_req.ramMax = ram_max_text 
            else:
                resource_req.ramMax = float( ram_max_text )
        if cores_min_text:
            if cores_min_text.startswith('$'):    
                resource_req.coresMin = cores_min_text 
            else:
                resource_req.coresMin = float( cores_min_text )
        if cores_max_text:
            if cores_max_text.startswith('$'):    
                resource_req.coresMax = cores_max_text 
            else:
                resource_req.coresMax = float( cores_max_text )

        return resource_req

    def clear(self):
        """Clear all resource requirement fields."""
        super().clear()  # Call base class method
        self.line_edit_min_memory.setText("")
        self.line_edit_min_cores.setText("")


class QRequirementsWidget(QCWLedWidget):
    '''
    A widget that holds the requirements:
    InlineJavascriptRequirement,
    SchemaDefRequirement,
    SoftwareRequirement, EnvVarRequirement,
    ShellCommandRequirement,
    LoadListingRequirement,
    WorkReuse,
    NetworkAccess,
    InplaceUpdateRequirement,
    ToolTimeLimit
    '''
    codeUpdated = pyqtSignal()
    code = None  # Keeps the code for the InlineJavascript

    def __init__(self, parent=None, cwl_version: Optional[str] = None):
        super().__init__(parent=parent, cwl_version=cwl_version)
        # Logger and initUI() are set up in QCWLedWidget's __init__

    def initUI(self):
        # every requirement on its own line, one below the other
        self.layout = QVBoxLayout()
        self.layout.setSpacing(10)
        self.inlinejavascript_checkbox = QCheckBox(
            'InlineJavascript', parent=self
        )
        self.inlinejavascript_expression_lib = QLabelLineEditWidget(
            label_text='Expression library', parent=self, stacked=True
        )
        self.inlinejavascript_edit_button = QCodeButton(parent=self)
        self.inlinejavascript_edit_button.clicked.connect(
            lambda: self.onCodeEditor(self.inlinejavascript_expression_lib)
        )
        # the expression library field with its </> button attached
        self.inlinejavascript_expression_lib.attachButton(
            self.inlinejavascript_edit_button
        )

        self.shellcommand_checkbox = QCheckBox('ShellCommand', parent=self)
        self.inplaceupdate_checkbox = QCheckBox('InplaceUpdate', parent=self)

        self.layout.addWidget(self.inlinejavascript_checkbox)
        self.layout.addWidget(self.inlinejavascript_expression_lib)
        self.layout.addWidget(self.shellcommand_checkbox)
        self.layout.addWidget(self.inplaceupdate_checkbox)
        self.setLayout(self.layout)

        self.inlinejavascript_checkbox.stateChanged.connect(
            self.onCheckBoxChanged
        )
        self.shellcommand_checkbox.stateChanged.connect(self.onCheckBoxChanged)
        self.inplaceupdate_checkbox.stateChanged.connect(
            self.onCheckBoxChanged
        )

    def onCheckBoxChanged(self, state):
        self._emit_editing_finished()  # Use the base class method

    def onCodeEditor(self, widget_to_update=None):
        dialog = JavaScriptEditorDialog(parent=self)
        if widget_to_update and widget_to_update.text():
            dialog.editor.setText(widget_to_update.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            code_text = dialog.get_javascript_code()
            if code_text and widget_to_update is not None:
                widget_to_update.setText(code_text)
                self.codeUpdated.emit()
                self._emit_editing_finished()  # Use the base class method

    def populateFromCWL(self, cwl_data: Optional[Any] = None):
        """
        Populate requirements widgets from a list of CWL requirement objects.
        
        Args:
            cwl_data: List of CWL requirement objects
        """
        super().populateFromCWL(cwl_data)  # Call base class method
        
        # If we didn't get data, nothing to do
        if cwl_data is None:
            return
            
        # Convert to a list if it's not already
        data_list = cwl_data if isinstance(cwl_data, list) else [cwl_data]
            
        self.logger.debug(
            f"Received data for populating requirements: {data_list}"
        )
        # Block signals for all checkboxes before changing their state
        self.inlinejavascript_checkbox.blockSignals(True)
        self.shellcommand_checkbox.blockSignals(True)
        self.inplaceupdate_checkbox.blockSignals(True)

        # initialize all checkboxes to unchecked
        self.inlinejavascript_checkbox.setChecked(False)
        self.inlinejavascript_expression_lib.setText("")
        self.shellcommand_checkbox.setChecked(False)
        self.inplaceupdate_checkbox.setChecked(False)

        for requirement in data_list:
            if not hasattr(requirement, 'class_'):
                self.logger.warning(
                    f"Requirement object {requirement} lacks a "
                    f"'class_' attribute."
                )
                continue
            self.logger.debug(
                    f"\tChecking {requirement.class_} "
                )
            if requirement.class_ not in [
                'ShellCommandRequirement',
                'InplaceUpdateRequirement',
                'InlineJavascriptRequirement'
            ]:
                self.logger.debug(
                    f"\tSkipping {requirement.class_} as it is not "
                    f"a supported requirement."
                )
                continue
            if requirement.class_ == 'ShellCommandRequirement':
                self.shellcommand_checkbox.setChecked(True)
            elif requirement.class_ == 'InplaceUpdateRequirement':
                self.inplaceupdate_checkbox.setChecked(True)
            elif requirement.class_ == 'InlineJavascriptRequirement':
                self.inlinejavascript_checkbox.setChecked(True)
                expressionLib = requirement.expressionLib
                if isinstance(expressionLib, list):
                    if expressionLib:
                        self.logger.debug(
                            f"\twith expressionLib: "
                            f"{expressionLib[0][1:20]}..."
                        )
                        self.inlinejavascript_expression_lib.setText(
                            str(expressionLib[0])
                        )
                    else:
                        self.inlinejavascript_expression_lib.setText("")
                elif isinstance(expressionLib, str):
                    self.inlinejavascript_expression_lib.setText(expressionLib)
                else:
                    self.inlinejavascript_expression_lib.setText("")
                self.logger.debug(
                    f"Populated InlineJavascriptRequirement with "
                    f"expressionLib: "
                    f"{self.inlinejavascript_expression_lib.text()[:30]}"
                )
        # Unblock signals for all checkboxes after all changes are made
        self.inlinejavascript_checkbox.blockSignals(False)
        self.shellcommand_checkbox.blockSignals(False)
        self.inplaceupdate_checkbox.blockSignals(False)

    def getData(self, cwlVersion: str) -> List[Any]:
        """
        Constructs and returns a list of CWL requirement objects.

        This method checks which requirement checkboxes are selected in the UI
        (ShellCommand, InplaceUpdate, InlineJavascript) and creates the
        corresponding requirement objects using the cwl-utils library
        for the specified CWL version.

        For InlineJavascriptRequirement, it also includes the expressionLib
        if provided.

        Args:
            cwlVersion (str): The CWL version (e.g., 'v1.0', 'v1.2') to use
                              for creating the requirement objects.

        Returns:
            list[Any]: A list of cwl-utils requirement objects based on the
                       selected UI options. Returns an empty list if no
                       requirements are selected.
        """
        returnVal = []
        mod = get_cwl_module(cwlVersion)

        if self.shellcommand_checkbox.isChecked():
            returnVal.append(mod.ShellCommandRequirement())
        if self.inplaceupdate_checkbox.isChecked():
            try:
                returnVal.append(mod.InplaceUpdateRequirement())
            except AttributeError:
                pass  # this may not be available in all versions
        if self.inlinejavascript_checkbox.isChecked():
            expression_lib_text = self.inlinejavascript_expression_lib.text()
            if expression_lib_text:
                returnVal.append(
                    mod.InlineJavascriptRequirement(
                        expressionLib=expression_lib_text
                    )
                )
            else:
                returnVal.append(mod.InlineJavascriptRequirement())
        return returnVal
        
    def clear(self):
        """Clear all requirement checkboxes and fields."""
        super().clear()  # Call base class method
        self.inlinejavascript_checkbox.setChecked(False)
        self.inlinejavascript_expression_lib.setText("")
        self.shellcommand_checkbox.setChecked(False)
        self.inplaceupdate_checkbox.setChecked(False)
