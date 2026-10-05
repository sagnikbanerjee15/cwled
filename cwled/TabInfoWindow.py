from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                              QLabel, QComboBox, QScrollArea, QSizePolicy,
                              QPushButton, QCheckBox)
from PyQt6.QtGui import QIcon
from CWLparser import Parser
import builtins
import data
import theme
import logging
import getpass
from sanitizeName import sanitize
from widgets.qLabelLineEditWidget import QLabelLineEditWidget, QLabelTextEditWidget
from widgets.qExternalLinks import QExternalLinksGroupWidget 
from cwl_utils.parser import save
from typing import Any, Union
from cwl_utils_handler import get_cwl_version
from CWLtoolFactory import CWLRunner
from LLM import DocumentationToolLLM
import inspect
from pathlib import Path
import tempfile
from urllib.parse import urlparse
import re,json,sys,os
from datetime import datetime
logger = logging.getLogger(__name__)



class InfoWindow(QWidget):
    '''
    show the basic info for the app
    '''
    codeUpdated = pyqtSignal(str)  # Signal to notify when CWL tool is updated
    cwl_tool: Union[Any, None] = None  # The CWL tool being edited
    cwl_version: str = None  # The CWL version of the tool
    emit_message: str = "CWL info updated"
    def __init__(self,
                 cwl_tool: Union[Any, None],
                 parent=None):
        super().__init__(parent)

        self.logger = logging.getLogger(self.__class__.__name__)
        log_level = data.configuration.get('logLevel', {})
        self.logger.setLevel(log_level.get(self.__class__.__name__, 'DEBUG'))
        self.cwl_tool = cwl_tool
        self.childWindow = parent
        self.setCWLTool(cwl_tool)
        # self.setCWLVersion(cwl_tool.cwlVersion)
        self.initUI()

    def setCWLTool(self, cwl_tool: Union[Any, None] = None):
        '''
        set the cwl tool to be edited
        '''
        if cwl_tool:
            self.cwl_tool = cwl_tool
            self.setCWLVersion(self.cwl_tool.cwlVersion)

    def setCWLVersion(self, cwl_version: str):
        '''
        set the CWL version for the tool editor
        '''
        self.cwl_version = get_cwl_version(self.cwl_tool)
        # if cwl_version:
        #     if self.cwl_version:
        #         msg = (f"Changing version of CWL from {self.cwl_version} "
        #                f"to {cwl_version}")
        #         self.logger.debug(msg)
        #     self.cwl_version = cwl_version
        msg = (f"CWL version for {self.__class__.__name__} is set: "
               f"{cwl_version}")
        self.logger.debug(msg)

    def onClassChanged(self):
        old_class = self.cwl_tool.class_
        new_class = self.objectType.currentText()
        if new_class.upper() == 'COMMAND LINE TOOL':
            new_class = 'CommandLineTool'
        if new_class.upper() == 'EXPRESSION TOOL':
            new_class = 'ExpressionTool'
        msg = f"Updating the class of the document to {new_class}"
        self.logger.debug(msg)

        def CLT_Expression(input) -> Any:
            '''
            this is a hacky function to convert a CommandLineTool
            to ExpressionTool and viceversa

            input: either a CommandLineTool or an ExpressionTool
            '''
            logger.debug(f"Received  {input.class_}")
            if input.class_ == 'CommandLineTool':
                cwl_ver = input.cwlVersion
                output = Parser('ExpressionTool',
                                cwlVersion=cwl_ver).getCWL()
                output.expression = input.baseCommand
            elif input.class_ == 'ExpressionTool':
                cwl_ver = input.cwlVersion
                output = Parser('CommandLineTool',
                                cwlVersion=cwl_ver).getCWL()
                output.baseCommand = input.expression
            else:
                msg = (f"Trying to convert from {input.class_} "
                       f"which is not recognised")
                self.logger.warning(msg)

            if hasattr(input, 'id'):
                output.id = input.id
            if hasattr(input, 'inputs'):
                output.inputs = input.inputs
            if hasattr(input, 'outputs'):
                output.outputs = input.outputs
            if hasattr(input, 'requirements'):
                output.requirements = input.requirements
            if hasattr(input, 'hints'):
                output.hints = input.hints
            if hasattr(input, 'label'):
                output.label = input.label
            if hasattr(input, 'doc'):
                output.doc = input.doc
            logger.debug(f"Returning {output.class_}")
            return output

        if (old_class in ['CommandLineTool', 'ExpressionTool'] and
                new_class in ['CommandLineTool', 'ExpressionTool'] and
                old_class != new_class):
            # create a new object of the new type
            info_CWL = self.cwl_tool
            self.cwl_tool = CLT_Expression(info_CWL)
            msg = f"Updated the class of the document to {self.cwl_tool.class_}"
            logger.debug(msg)
        self.codeUpdated.emit(self.emit_message)

    def onCWLVersionChanged(self):

        self.logger.debug(f"{inspect.currentframe().f_code.co_name}")
        msg1 = (f"Current version of the tool is {self.cwl_version} "
                f"or {self.cwl_tool.cwlVersion}")
        self.logger.debug(msg1)
        msg2 = f"The user has selected {self.cwlVersion.currentText()}"
        self.logger.debug(msg2)

        new_version = self.cwlVersion.currentText()
        if new_version != self.cwl_tool.cwlVersion:
            self.setCWLVersion(new_version)
            # we need to reload the CWL object with the new version
            # i.e export it to a dictionalry and the parse it again
            obj = save(self.cwl_tool)
            obj['cwlVersion'] = new_version
            p= Parser(input=obj,
                      fileuri=self.cwl_tool.loadingOptions.fileuri,
                      baseuri=self.cwl_tool.loadingOptions.baseuri)
            self.cwl_tool=p.getCWL()
            msg = f"Updated the CWL tool to version {new_version}"
            self.logger.debug(msg)
            self.codeUpdated.emit(self.emit_message)

    def onAppIDChanged(self):
        new_id = self.app_id.text()
        self.cwl_tool.id = new_id
        self.codeUpdated.emit(self.emit_message)

    def onAppLabelChanged(self):
        new_label = self.app_label.text()
        self.cwl_tool.label = new_label
        self.codeUpdated.emit(self.emit_message)

    def onAppDescriptionChanged(self):
        new_desc = self.app_description.toPlainText()
        self.cwl_tool.doc = new_desc
        self.codeUpdated.emit(self.emit_message)


    def addMetadata(self,key:str,value:str):
        """Add metadata to the CWL tool's extension fields"""
        if hasattr(self.childWindow, 'addMetadata'):
            self.childWindow.addMetadata(
                 key = key, 
                 value= value,
                namespace = 'sc', 
                namespace_uri = 'https://schema.org/'
            )
        else:
            raise AttributeError("Parent does not have addMetadata method")


    def onToolkitAuthorChanged(self):
        toolkit_author = self.authorInfo[0].text()
        self.addMetadata(
             key = 'toolkitAuthor', 
             value= toolkit_author, 
        )
        # if not hasattr(self.cwl_tool, 'extension_fields'):
        #     self.cwl_tool.extension_fields = {}
        # self.cwl_tool.extension_fields['s:author'] = toolkit_author
        self.codeUpdated.emit(self.emit_message)

    def onToolkitLicenseChanged(self):
        toolkit_license = self.authorInfo[1].text()
        self.addMetadata(
             key = 'toolkitLicense', 
             value= toolkit_license 
        )
        # if not hasattr(self.cwl_tool, 'extension_fields'):
        #     self.cwl_tool.extension_fields = {}
        # self.cwl_tool.extension_fields['s:license'] = toolkit_license
        self.codeUpdated.emit(self.emit_message)

    def onWrapperAuthorChanged(self):
        wrapper_author = self.authorInfo[2].text()
        self.addMetadata(
             key = 'wrapperAuthor', 
             value= wrapper_author, 
        )
        # if not hasattr(self.cwl_tool, 'extension_fields'):
        #     self.cwl_tool.extension_fields = {}
        # self.cwl_tool.extension_fields['sbg:wrapperAuthor'] = wrapper_author
        self.codeUpdated.emit(self.emit_message)

    def onWrapperLicenseChanged(self):
        wrapper_license = self.authorInfo[3].text()
        self.addMetadata(
             key = 'wrapperLicense', 
             value= wrapper_license, 
        )
        # if not hasattr(self.cwl_tool, 'extension_fields'):
        #     self.cwl_tool.extension_fields = {}
        # self.cwl_tool.extension_fields['sbg:wrapperLicense'] = wrapper_license
        self.codeUpdated.emit(self.emit_message)

    def onExternalLinksChanged(self):
        """Handle external links changes."""
        links_data = self.external_links.getData()
        if links_data:
            self.addMetadata(
                key='external_links',
                value=json.dumps(links_data),
            )
            self.codeUpdated.emit(self.emit_message)

    def onToolkitNameChanged(self):
        toolkit_name = self.authorInfo[4].text()
        self.addMetadata(
             key = 'toolkitName', 
             value= toolkit_name, 
        )
        self.codeUpdated.emit(self.emit_message)

    def onToolkitVersionChanged(self):
        toolkit_version = self.authorInfo[5].text()
        self.addMetadata(
            key='toolkitVersion',
            value=toolkit_version,
        )
        self.codeUpdated.emit(self.emit_message)

    def onDocumentVersionChanged(self):
        """Handle changes to the Document Version field."""
        doc_version = self.doc_version.text()
        self.addMetadata(
            key='version',
            value=doc_version,
        )
        # Uncheck the automatically change version checkbox
        self.auto_version_checkbox.setChecked(False)
        # Emit signal to notify that CWL has changed
        self.codeUpdated.emit(self.emit_message)

    def onAutoVersionCheckboxChanged(self):
        """Handle changes to the automatically change version checkbox."""
        if self.childWindow:
            self.childWindow.track_version = self.auto_version_checkbox.isChecked()
            if hasattr(self.childWindow, 'updateGitToolbarActions'):
                self.childWindow.updateGitToolbarActions()
        # Show/hide git commit message widget based on checkbox state
        self.git_commit_message.setVisible(self.auto_version_checkbox.isChecked())

    def onAIButtonPressed(self):
        """Handle AI button press event"""
        # Check if cwl_tool is empty (no inputs, outputs, args, baseCommand)
        if not self.cwl_tool:
            return

        inputs = getattr(self.cwl_tool, 'inputs', None) or []
        outputs = getattr(self.cwl_tool, 'outputs', None) or []
        arguments = getattr(self.cwl_tool, 'arguments', None) or []
        base_command = getattr(self.cwl_tool, 'baseCommand', None) or []

        # If all are empty, do nothing
        if not inputs and not outputs and not arguments and not base_command:
            return

        # Otherwise, create DocumentationToolLLM and get response

        # we will try to pack the workflow with all the tools and dependencies and
        # send that to the LLM. This may be too large for the LLM to handle, so we may need to
        # implement some logic to reduce the size of the input if needed.
        # If this fails we will fallback to just sending the tool itself.
        doc_for_tool = ""
        if self.cwl_tool.class_ == 'Workflow':
            try:
                # the problem with flattenWorkflow is that if the tools are of different cwl version the parser breaks.
                p= Parser( self.cwl_tool)
                p.gatherWorkflowDocumentation()
                
                doc_for_tool = p.documentation_summary
            except Exception as e:
                self.logger.error(f"Error packing workflow with tools: {e}")
                
        try:
            doc = DocumentationToolLLM(
                cwl_tool=self.cwl_tool, # this is the CWL tool object
                additional_documentation=doc_for_tool
            )
            response = doc.preparePrompt()

            # Place the response in the Application Description text box
            if response:
                self.app_description.setText(response)
                # Trigger the description changed event to update the CWL tool
                self.onAppDescriptionChanged()
        except Exception as e:
            self.logger.error(f"Error generating documentation with AI: {e}")

    def onCodesChanged(self, code_type):
        codes = None
        if code_type == 'successCodes':
            codes = self.success_codes_edit.text()
        if code_type == 'temporaryFailCodes':
            codes = self.temporary_fail_codes_edit.text()
        if code_type == 'permanentFailCodes':
            codes = self.permanent_fail_codes_edit.text()
        codes_int_array = []
        if codes:
            for item in codes.split(','):
                item = item.strip()  # Remove whitespace
                if item:  # Skip empty strings
                    try:
                        codes_int_array.append(int(item))
                    except ValueError:
                        pass

        if len(codes_int_array) > 0:
            if code_type == 'successCodes':
                self.cwl_tool.successCodes = codes_int_array
                self.codeUpdated.emit(self.emit_message)
            if code_type == 'temporaryFailCodes':
                self.cwl_tool.temporaryFailCodes = codes_int_array
                self.codeUpdated.emit(self.emit_message)
            if code_type == 'permanentFailCodes':
                self.cwl_tool.permanentFailCodes = codes_int_array
                self.codeUpdated.emit(self.emit_message)



    def initUI(self):
        ''' Initialize the UI components for the InfoWindow
        '''

        # Create a vertical layout
        layout = QVBoxLayout()

        self.app_label = QLabelLineEditWidget(
            label_text="Application name",
            placeholder_text="Application name",
            parent=self
        )
        self.app_label.editingFinished.connect(self.onAppLabelChanged)
        
        # Document version with checkbox
        self.doc_version_layout = QHBoxLayout()
        self.doc_version = QLabelLineEditWidget(
            label_text="Document version",
            placeholder_text="Document version",
            parent=self
        )
        self.doc_version.editingFinished.connect(self.onDocumentVersionChanged)
        
        self.auto_version_checkbox = QCheckBox("Track version with git", self)
        version_enabled = self.childWindow.track_version
        self.auto_version_checkbox.setChecked(version_enabled)
        self.auto_version_checkbox.stateChanged.connect(self.onAutoVersionCheckboxChanged)
        
        self.doc_version_layout.addWidget(self.doc_version)
        self.doc_version_layout.addWidget(self.auto_version_checkbox)
        
        # Git commit message widget (visible only when versioning is enabled)
        self.git_commit_message = QLabelLineEditWidget(
            label_text="Git commit message",
            placeholder_text="What changed in this version?",
            parent=self
        )
        self.git_commit_message.setVisible(version_enabled)
        
        self.app_id = QLabelLineEditWidget(
            label_text="Application ID ",
            placeholder_text="Application ID (spaces are not allowed)",
            parent=self
        )
        sanitize_lambda = lambda: self.sanitizeID(self.app_id.text()) 
        self.app_id.textChanged.connect(sanitize_lambda)
        self.app_id.editingFinished.connect(self.onAppIDChanged)

        self.app_description = QLabelTextEditWidget(
            label_text="Application Description",
            placeholder_text="Describe the application",
            parent=self)
        self.app_description.setPlaceholderText("Description of the tool")
        desc_handler = self.onAppDescriptionChanged
        self.app_description.editingFinished.connect(desc_handler)

        # Add AI button with sparkler icon
        self.ai_button = QPushButton(self)
        self.ai_button.setIcon(theme.icon('ai', color=theme.SKY))
        self.ai_button.setToolTip("AI")
        self.ai_button.setFixedSize(30, 30)  # Make button square and compact
        self.ai_button.clicked.connect(self.onAIButtonPressed)

        # Create layout for app_description with AI button on the right
        self.app_description_layout = QHBoxLayout()
        self.app_description_layout.addWidget(self.app_description)
        self.app_description_layout.addWidget(self.ai_button)
        self.app_description_layout.setContentsMargins(0, 0, 0, 0)

        # add a drop down list for the type of tool
        layoutCWLObjectType = QHBoxLayout()
        label5 = QLabel("Object type")
        label5.setFixedWidth(builtins.labelWidth)
        self.objectType = QComboBox(self)
        obj_items = ['Command line tool', 'Expression tool', 'Workflow']
        self.objectType.addItems(obj_items)
        layoutCWLObjectType.addWidget(label5)
        layoutCWLObjectType.addWidget(self.objectType)
        self.objectType.currentTextChanged.connect(self.onClassChanged)
        # add a drop down list for the CLW version
        layoutCWLversion = QHBoxLayout()
        label4 = QLabel("CWL version")
        label4.setFixedWidth(builtins.labelWidth)
        self.cwlVersion = QComboBox(self)
        cwl_versions = data.configuration.get('cwl_version')
        self.cwlVersion.addItems([x.get('name') for x in cwl_versions])
        self.cwlVersion.currentTextChanged.connect(self.onCWLVersionChanged)
        layoutCWLversion.addWidget(label4)
        layoutCWLversion.addWidget(self.cwlVersion)

        layoutCWLversion_object = QHBoxLayout()
        layoutCWLversion_object.addLayout(layoutCWLversion)
        layoutCWLversion_object.addLayout(layoutCWLObjectType)

        # add the author information
        self.authorInfo = []
        self.layoutAuthor = QVBoxLayout()
        self.author_information_layout()

        # add a place to capture success and failure codes
        self.success_codes_edit=QLabelLineEditWidget(label_text="Success codes",
                                                     placeholder_text="Success codes (comma separated)",
                                                     parent=self)
        
        self.permanent_fail_codes_edit=QLabelLineEditWidget( label_text="Permanent Failure codes",
                                                     placeholder_text="Failure codes (comma separated)",
                                                     parent=self)
        self.temporary_fail_codes_edit=QLabelLineEditWidget( label_text="Temporary Failure codes",
                                                     placeholder_text="Failure codes (comma separated)",
                                                     parent=self)
        self.success_codes_edit.editingFinished.connect(lambda:self.onCodesChanged('successCodes'))
        self.permanent_fail_codes_edit.editingFinished.connect(lambda:self.onCodesChanged('permanentFailCodes'))
        self.temporary_fail_codes_edit.editingFinished.connect(lambda:self.onCodesChanged('temporaryFailCodes'))
        
        # add the external linkns widget
        self.external_links = QExternalLinksGroupWidget(
            parent=self,
            cwl_tool=None,  # Will be populated later
            cwl_version=self.cwl_version
        )
        self.external_links.editingFinished.connect(self.onExternalLinksChanged)
        
        
        # Add the input boxes to the layout
        layout.addLayout(layoutCWLversion_object)
        layout.addWidget(self.app_label)
        layout.addLayout(self.doc_version_layout)
        layout.addWidget(self.git_commit_message)
        layout.addWidget(self.app_id)
        layout.addLayout(self.app_description_layout)
        layout.addWidget(self.success_codes_edit)
        layout.addWidget(self.permanent_fail_codes_edit)
        layout.addWidget(self.temporary_fail_codes_edit)
        layout.addLayout(self.layoutAuthor)
        layout.addWidget(self.external_links)
        


        container_widget=QWidget( parent=self )
        container_widget.setLayout( layout )
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidget(container_widget)  # Add the container widget to the scroll area
        self.scroll_area.setWidgetResizable(True)  # Make the widget resizable within the scroll area
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # Always show vertical scrollbar
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Bottom ribbon with file metadata
        self.file_info_ribbon = QWidget(self)
        ribbon_layout = QHBoxLayout(self.file_info_ribbon)
        ribbon_layout.setContentsMargins(8, 4, 8, 4)
        ribbon_layout.setSpacing(20)

        self.file_format_label = QLabel("Format: <unknown>", self.file_info_ribbon)
        self.file_created_label = QLabel("Created: <unknown>", self.file_info_ribbon)
        self.file_modified_label = QLabel("Modified: <unknown>", self.file_info_ribbon)

        ribbon_layout.addWidget(self.file_format_label)
        ribbon_layout.addWidget(self.file_created_label)
        ribbon_layout.addWidget(self.file_modified_label)
        ribbon_layout.addStretch(1)

        # Composer status-bar look for the file information ribbon
        self.file_info_ribbon.setObjectName('fileInfoRibbon')
        self.file_info_ribbon.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.file_info_ribbon.setStyleSheet(
            f"QWidget#fileInfoRibbon {{ background-color: {theme.STATUS_BAR_BG}; "
            f"border-top: 1px solid {theme.BLACK}; }} "
            f"QWidget#fileInfoRibbon QLabel {{ color: {theme.TEXT_MUTED}; padding: 3px 8px; }}"
        )

        # Main layout of the window
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.file_info_ribbon)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        # Set the layout for the widget
        self.setLayout(main_layout)

        self.updateFileInfoRibbon()

    def _formatTimestamp(self, ts: float) -> str:
        try:
            return datetime.fromtimestamp(ts).astimezone().strftime('%c')
        except Exception:
            return '<unknown>'

    def updateFileInfoRibbon(self):
        """Refresh the bottom file-info ribbon (format/created/modified)."""
        file_format = '<unknown>'
        file_created = '<unknown>'
        file_modified = '<unknown>'

        try:
            if self.childWindow and getattr(self.childWindow, 'file_format', None):
                file_format = str(self.childWindow.file_format)

            file_path = getattr(self.childWindow, 'file_path', None) if self.childWindow else None
            if file_path and Path(file_path).exists():
                stat_info = Path(file_path).stat()
                created_ts = getattr(stat_info, 'st_birthtime', stat_info.st_ctime)
                modified_ts = stat_info.st_mtime
                file_created = self._formatTimestamp(created_ts)
                file_modified = self._formatTimestamp(modified_ts)
        except Exception as e:
            self.logger.debug(f"Unable to update file info ribbon: {e}")

        self.file_format_label.setText(f"Format: {file_format}")
        self.file_created_label.setText(f"Created: {file_created}")
        self.file_modified_label.setText(f"Modified: {file_modified}")

    def getCWL(self):   
        '''
        return the CWL tool
        '''
        return self.cwl_tool
    
    def setCWLTool(self, cwl_tool:Union[Any,None]=None):
        '''
        set the cwl tool to be edited
        it must be a CommandLineTool 
        '''

        type_of_cwl_tool = type(cwl_tool).__name__ if cwl_tool else 'None'
        if type_of_cwl_tool not in ['CommandLineTool','ExpressionTool','Workflow']:
            self.logger.error(f"Expected a CommandLineTool, but got {type_of_cwl_tool}")
            raise TypeError(f"Expected a CommandLineTool, but got {type_of_cwl_tool}")

        self.cwl_tool=cwl_tool
        self.setCWLVersion( self.cwl_tool.cwlVersion)
        self.logger.debug(f"Received new cwl tool")
        self.logger.debug(f"Class       : {self.cwl_tool.class_}")
        self.logger.debug(f"CWL version : {self.cwl_tool.cwlVersion}")
        # self.updateSignal.emit('cwl_tool')


    def author_information_layout(self):
        '''
        setup a layout for the author information
        '''
        # Define the author elements and their positions
        authorElements = [
            ('Toolkit Author', 0, 0),
            ('Toolkit License', 0, 2),
            ('Wrapper Author', 1, 0),
            ('Wrapper License', 1, 2),
            ('Toolkit Name', 2, 0),
            ('Toolkit Version', 2, 2)
        ]
        layoutGrid = QGridLayout()
        # Loop through the author elements and add them to the grid layout
        for idx, (labelText, row, col) in enumerate(authorElements):
            
            # Create a QLineEdit and store it in the authorInfo list
            lineEdit = QLabelLineEditWidget(
                label_text=labelText,
                placeholder_text=labelText,
                parent=self
            )
            if labelText == 'Wrapper Author':
                lineEdit.setText(getpass.getuser())
            
            # Connect the appropriate signal based on the widget index
            if idx == 0:  # Toolkit Author
                lineEdit.editingFinished.connect(self.onToolkitAuthorChanged)
            elif idx == 1:  # Toolkit License
                lineEdit.editingFinished.connect(self.onToolkitLicenseChanged)
            elif idx == 2:  # Wrapper Author
                lineEdit.editingFinished.connect(self.onWrapperAuthorChanged)
            elif idx == 3:  # Wrapper License
                lineEdit.editingFinished.connect(self.onWrapperLicenseChanged)
            elif idx == 4:  # Toolkit Name
                lineEdit.editingFinished.connect(self.onToolkitNameChanged)
            elif idx == 5:  # Toolkit Version
                lineEdit.editingFinished.connect(self.onToolkitVersionChanged)
            
            self.authorInfo.append(lineEdit)
            
            # Add the label and the QLineEdit to the grid layout
            layoutGrid.addWidget(lineEdit, row, col + 1)


        # Set the grid layout as the layout for the main window
        self.layoutAuthor.addLayout(layoutGrid)


    def sanitizeID(self,text):
        new_text=sanitize(text).underscore().text
        self.app_id.setText(new_text)
        self.app_id.setCursorPosition(len( new_text ))

    def populateFromCWL(self):
        '''
        Initialize the widgets with the values in the CWL
        '''
        # Store original signal blocking state
        old_state = self.blockSignals(True)
        
        # Save scroll position before updating
        scroll_v_pos = 0
        scroll_h_pos = 0
        if hasattr(self, 'scroll_area'):
            scroll_v_pos = self.scroll_area.verticalScrollBar().value()
            scroll_h_pos = self.scroll_area.horizontalScrollBar().value()
        
        try:
            self.cwlVersion.setCurrentText( self.cwl_tool.cwlVersion if self.cwl_tool.cwlVersion else 'v1.2' )
            self.app_description.setText( self.cwl_tool.doc)
            self.app_id.setText( self.cwl_tool.id.split('#')[-1])
            self.app_label.setText( self.cwl_tool.label)

            # Set the object type based on the class in CWL
            cwl_class = self.cwl_tool.class_
            if cwl_class == 'CommandLineTool':
                self.objectType.setCurrentText('Command line tool')
            elif cwl_class == 'ExpressionTool':
                self.objectType.setCurrentText('Expression tool')
            elif cwl_class == 'Workflow':
                self.objectType.setCurrentText('Workflow')
            # Exit codes are edited in the Visual Editor's "Other" section (as in Composer)
            self.success_codes_edit.setVisible(False)
            self.temporary_fail_codes_edit.setVisible(False)
            self.permanent_fail_codes_edit.setVisible(False)

            if hasattr(self.cwl_tool, 'successCodes'):
                # Convert successCodes to a comma-separated string
                self.success_codes_edit.setText(','.join( map( str, self.cwl_tool.successCodes or [] )) )
                self.permanent_fail_codes_edit.setText(','.join( map(str, self.cwl_tool.permanentFailCodes or [] ) ))
                self.temporary_fail_codes_edit.setText(','.join( map(str, self.cwl_tool.temporaryFailCodes or [] ) )) 
            #author information
            if hasattr(self.cwl_tool, 'extension_fields') and self.cwl_tool.extension_fields:
                ext_fields = self.cwl_tool.extension_fields 
                toolkit_author = None
                wrapper_author = None
                toolkit_license = None
                wrapper_license = None
                toolkit_name = None
                toolkit_version = None
                doc_version = None
                
                for ext_field_key in list(ext_fields.keys()):
                    field_value=str(ext_fields.get(ext_field_key))
                    
                    if ext_field_key.endswith("toolkitAuthor"):
                        toolkit_author = field_value
                    if ext_field_key.endswith("wrapperAuthor"):
                        wrapper_author = field_value
                    if ext_field_key.endswith("toolkitLicense"):
                        toolkit_license = field_value
                    if ext_field_key.endswith("wrapperLicense"):
                        wrapper_license = field_value
                    if ext_field_key.endswith("toolkitName") or ext_field_key.endswith("toolkit"):
                        toolkit_name = field_value
                    if ext_field_key.endswith("toolkitVersion"):
                        toolkit_version = field_value
                    if ext_field_key.endswith("version") and not ext_field_key.endswith("toolkitVersion"):
                        doc_version = field_value
                    if ext_field_key.endswith("external_links"):
                        links_data = field_value
                        if links_data:
                            # print( f"Found external links data: {links_data}" )
                            # print( f"Type of links data: {type( links_data )}" )
                            links=json.loads( links_data )
                            # print( f"Parsed links data: {links}" )
                            self.external_links.populateFromCWL( 
                                links
                            )
                # Populate Toolkit Author (index 0)

                if toolkit_author and len(self.authorInfo) > 0:
                    self.authorInfo[0].setText(str(toolkit_author))
                
                if toolkit_license and len(self.authorInfo) > 1:
                    self.authorInfo[1].setText(str(toolkit_license))
                
                if wrapper_author and len(self.authorInfo) > 2:
                    self.authorInfo[2].setText(str(wrapper_author))
                
                if wrapper_license and len(self.authorInfo) > 3:
                    self.authorInfo[3].setText(str(wrapper_license))
                
                if toolkit_name and len(self.authorInfo) > 4:
                    self.authorInfo[4].setText(str(toolkit_name))
                
                if toolkit_version and len(self.authorInfo) > 5:
                    self.authorInfo[5].setText(str(toolkit_version))
                
                # Populate Document Version
                if doc_version:
                    self.doc_version.setText(str(doc_version))

            self.updateFileInfoRibbon()
        finally:
            # Restore original signal blocking state
            self.blockSignals(old_state)
            
            # Restore scroll position after updating
            if hasattr(self, 'scroll_area'):
                self.scroll_area.verticalScrollBar().setValue(scroll_v_pos)
                self.scroll_area.horizontalScrollBar().setValue(scroll_h_pos)
            
            