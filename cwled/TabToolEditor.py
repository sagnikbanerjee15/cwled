from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor,QFontMetrics
import json
import sys
import builtins
import data
import theme
import logging
from helperFunctions import addArrayItem
from nested_lookup import nested_lookup, nested_update
from widgets.qLabelLineEditWidget import QLabelLineEditWidget
from widgets.qBaseCommand import QBaseCommandGroupWidget
from widgets.qArguments import    QArgumentsGroupWidget, QArgumentWidget
from widgets.qInputs import QInputsGroupWidget, QInputWidget
from widgets.qOutputs import QOutputsGroupWidget
from widgets.qButtons import QCodeButton
from widgets.qInspector import Inspector
from widgets.qRequirements import QResourceRequirementsWidget, QRequirementsWidget
from widgets.qInitialWorkDir import QInitialWorkDirGroup
from widgets.qDocker import QDockerWidget
from widgets.qEnvVar import QEnvVarGroupWidget
from cwl_utils_handler import get_cwl_module, get_cwl_version
from qErrorMessage import QErrorMessage
from typing import Union, Any, Optional

from cwl_utils.parser import save
from JavascriptEditor import JavaScriptEditorDialog, validateExpression
# Don't import specific DockerRequirement, we'll import dynamically

class ToolEditor( QWidget ):
    '''
    main tool editor window 
    '''
    
    updateSignal = pyqtSignal(str)
    codeUpdated = pyqtSignal(str)  # Signal to notify when CWL tool is updated
    base_commands=[(None,None,None)] # tuples of (basecommand, order, entry_order)
    base_commands_entry_index=0 # what is the order of entry (not user specified)
    cwl_tool:Any=None
    cwl_version:str=None
    def __init__(self,
                 cwl_tool:Union[Any,None],
                 parent=None):
        super().__init__(parent)

        self.logger=logging.getLogger(self.__class__.__name__)
        
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        self.logger_requirements=logging.getLogger(f'{self.__class__.__name__}.requirements')
        self.logger_requirements.setLevel(data.configuration.get('logLevel',{}).get(f'{self.__class__.__name__}.requirements', 'DEBUG'))
       
        self.logger_sort=logging.getLogger(f'{self.__class__.__name__}.sortCWL')
        self.logger_sort.setLevel(data.configuration.get('logLevel',{}).get(f'{self.__class__.__name__}.sortCWL', 'DEBUG'))
        self.logger_basecommand=logging.getLogger(f'{self.__class__.__name__}.basecommand')
        self.logger_basecommand.setLevel(data.configuration.get('logLevel',{}).get(f'{self.__class__.__name__}.basecommand', 'DEBUG'))
        self.logger_setcwl=logging.getLogger(f'{self.__class__.__name__}.setcwl')
        self.logger_setcwl.setLevel(data.configuration.get('logLevel',{}).get(f'{self.__class__.__name__}.setcwl', 'DEBUG'))
        self.logger_envvar=logging.getLogger(f'{self.__class__.__name__}.envvar')
        self.logger_envvar.setLevel(data.configuration.get('logLevel',{}).get(f'{self.__class__.__name__}.envvar', 'DEBUG'))
        self.logger_inputs=logging.getLogger(f'{self.__class__.__name__}.inputs')
        self.logger_inputs.setLevel(data.configuration.get('logLevel',{}).get(f'{self.__class__.__name__}.inputs', 'DEBUG'))
        

        self.setCWLTool(cwl_tool)
        # self.setCWLVersion(cwl_tool.cwlVersion)
        self.initUI()
       
    def setCWLVersion(self, cwl_version:Optional[str]=None):
        '''
        set the CWL version for the tool editor
        '''
        self.cwl_version=get_cwl_version( self.cwl_tool)
        # if cwl_version:
        #     if self.cwl_version:
        #         self.logger_setcwl.debug(f"Changing version of CWL from {self.cwl_version} to  {cwl_version}") 
        #     self.cwl_version = cwl_version
        self.logger_setcwl.debug(f"CWL version for {self.__class__.__name__} is set: {cwl_version}")

    def getCWL(self):   
        '''
        return the CWL tool
        '''
        return self.cwl_tool
    

    def initUI(self):

        # Create a vertical layout
        layout = QVBoxLayout()

        # Create the docker widget
        self.docker_image = QDockerWidget(
            parent=self, 
            cwl_version=self.cwl_version
        )
        self.docker_image.editingFinished.connect(self.onDockerImageChange)


        # create the envVar layout
        self.envvar = QEnvVarGroupWidget(
            parent=self,
            cwl_version=self.cwl_version)
        self.envvar.editingFinished.connect(self.onEnvVarChange)
        # create the base command layout  which works for CommandLine tool
        self.basecommand=QBaseCommandGroupWidget(
            parent=self, 
            cwl_version=self.cwl_version
        )
        self.basecommand.editingFinished.connect(self.onBaseCommandChange)
        # create the expression layout which works for ExpressionTool
        self.expression=QLabelLineEditWidget(
            label_text='Expression',
            parent=self
        )
        self.expression_code=QCodeButton( parent=self)
        self.expression_code.clicked.connect(self.onExpressionCodeClicked)
        
        # Create layout for expression widget with JavaScript editor button
        # (the panel title names the field)
        self.expression.label.hide()
        self.expression.attachButton(self.expression_code)
        self.expression_layout = QHBoxLayout()
        self.expression_layout.setContentsMargins(0, 0, 0, 0)
        self.expression_layout.addWidget(self.expression)
        self.expression_widget = QWidget()
        self.expression_widget.setLayout(self.expression_layout)

        # create the arguments Layout
        self.argument = QArgumentsGroupWidget(
            parent=self,
            cwl_version=self.cwl_version
        )
        self.argument.editingFinished.connect(self.onArgumentsChange)

        # create the inputs Layout
        self.input = QInputsGroupWidget(
            parent=self,
            cwl_version=self.cwl_version
        )
        self.input.editingFinished.connect(self.onInputsChange)

        # create the outputs Layout
        self.output = QOutputsGroupWidget(
            parent=self,
            cwl_version=self.cwl_version
        )
        self.output.editingFinished.connect(self.onOutputsChange)

        # create the requirements layout
        self.resourcerequirements = QResourceRequirementsWidget(
            parent=self,
            cwl_version=self.cwl_version
        )
        self.resourcerequirements.editingFinished.connect(
            self.onResourceRequirementsChange)

        # create teh other requirements layout
        self.requirements = QRequirementsWidget(
            parent=self,
            cwl_version=self.cwl_version)
        self.requirements.editingFinished.connect(self.onRequirementsChange)
        # allow to give names for stderr and stdout
        self.stdout = QLabelLineEditWidget(
            label_text="Output stream",
            placeholder_text="Filename for standard output",
            objectName='stdout', parent=self, stacked=True)
        self.stdout.editingFinished.connect(self.onStdoutChange)
        
        
        self.stderr = QLabelLineEditWidget(
            label_text="Error stream",
            placeholder_text="Filename for standard error",
            objectName='stderr', parent=self, stacked=True)
        self.stderr.editingFinished.connect(self.onStderrChange)
        

        # create the initial working dir layout
        self.initial_workingdir = QInitialWorkDirGroup(
            cwl_tool=self.cwl_tool,
            parent=self,
            cwl_version=self.cwl_version)
        self.initial_workingdir.editingFinished.connect(
            self.onInitialWorkdirChange)

        

        # Add the sections to the layout as Composer form panels, in the
        # order of Composer's tool visual editor
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(theme.SECTION_SPACING)

        # Composer "Other" section: stream redirects and exit codes
        self.stdin = QLineEdit(self)
        self.stdin.editingFinished.connect(self.onStdinChange)
        self.success_codes = QLineEdit(self)
        self.success_codes.editingFinished.connect(lambda: self.onCodesChange('successCodes'))
        self.temporary_fail_codes = QLineEdit(self)
        self.temporary_fail_codes.editingFinished.connect(lambda: self.onCodesChange('temporaryFailCodes'))
        self.permanent_fail_codes = QLineEdit(self)
        self.permanent_fail_codes.editingFinished.connect(lambda: self.onCodesChange('permanentFailCodes'))
        for edit in (self.stdout.line_edit, self.stderr.line_edit):
            edit.setPlaceholderText("")

        self.streams_widget = QWidget(parent=self)
        other_layout = QGridLayout(self.streams_widget)
        other_layout.setContentsMargins(0, 0, 0, 0)
        other_layout.setHorizontalSpacing(26)
        other_layout.setVerticalSpacing(13)
        other_layout.setColumnStretch(0, 1)
        other_layout.setColumnStretch(1, 1)
        other_layout.addWidget(theme.FieldGroup(
            "Stdin redirect", self.stdin, parent=self,
            open_editor=lambda: self.editExpression(self.stdin),
            validator=self._validateExpression), 0, 0)
        other_layout.addWidget(theme.FieldGroup(
            "Stdout redirect", self.stdout.line_edit, parent=self,
            open_editor=lambda: self.editExpression(self.stdout.line_edit),
            validator=self._validateExpression), 0, 1)
        other_layout.addWidget(theme.FieldGroup(
            "Stderr redirect", self.stderr.line_edit, parent=self,
            open_editor=lambda: self.editExpression(self.stderr.line_edit),
            validator=self._validateExpression), 1, 0)
        separator = QFrame(self.streams_widget)
        separator.setObjectName('panelSeparator')
        separator.setFixedHeight(1)
        other_layout.addWidget(separator, 2, 0, 1, 2)
        other_layout.addWidget(theme.FieldGroup("Success Codes", self.success_codes, parent=self), 3, 0)
        other_layout.addWidget(theme.FieldGroup("Temporary Fail Codes", self.temporary_fail_codes, parent=self), 3, 1)
        other_layout.addWidget(theme.FieldGroup("Permanent Fail Codes", self.permanent_fail_codes, parent=self), 4, 0)
        # The labelled stdout/stderr widgets only keep their (moved) fields
        self._hidden_fields = QWidget(self)
        self._hidden_fields.hide()
        self.stdout.setParent(self._hidden_fields)
        self.stderr.setParent(self._hidden_fields)

        sections = [
            (self.docker_image, dict(title="Docker Image")),
            (self.basecommand, dict(title="Base Command", add_text="Add Base Command",
                                    stripe=theme.CODE_BASE_CMD)),
            (self.expression_widget, dict(title="Expression")),
            (self.argument, dict(title="Arguments", add_text="Add an Argument",
                                 stripe=theme.CODE_ARGS,
                                 columns=[("Value", 4), ("Prefix", 3), ("Separate", 3), ("#", 2)])),
            (self.input, dict(title="Input Ports", add_text="Add an Input",
                              stripe=theme.CODE_INPUTS,
                              columns=[("ID", 4), ("Type", 3), ("Binding", 4), ("", 1)])),
            (self.output, dict(title="Output Ports", add_text="Add an Output",
                               columns=[("ID", 4), ("Type", 3), ("Glob", 4), ("", 1)])),
            (self.resourcerequirements, dict(title="Computational Resources")),
            (self.requirements, dict(title="Requirements")),
            (self.initial_workingdir, dict(title="File Requirements", add_text="Add a File")),
            (self.envvar, dict(title="Environment Variables", add_text="Add an Environment Variable")),
            (self.streams_widget, dict(title="Other")),
        ]
        for section, options in sections:
            layout.addWidget(theme.FormSection(section, parent=self, **options))
        layout.addStretch(1)
        
        container_widget = QWidget(parent=self)
        container_widget.setLayout(layout)
        self.scroll_area = QScrollArea(self)
        # Add the container widget to the scroll area
        self.scroll_area.setWidget(container_widget)
        # Make the widget resizable within the scroll area
        self.scroll_area.setWidgetResizable(True)
        
        # Always show vertical scrollbar
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding)

        # Composer object inspector, docked on the right of the sections
        self.inspector = Inspector(root=container_widget, parent=self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName('inspectorSplitter')
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.scroll_area)
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([10000, Inspector.DEFAULT_WIDTH])

        # Main layout of the window
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.splitter)

        # Set the layout for the widget
        self.setLayout(main_layout)

    def setCWLTool(self, cwl_tool:Union[Any,None]=None):
        '''
        set the cwl tool to be edited
        it must be a CommandLineTool 
        '''

        type_of_cwl_tool = type(cwl_tool).__name__ if cwl_tool else 'None'
        if type_of_cwl_tool not in ['CommandLineTool','ExpressionTool']:
            self.logger_setcwl.error(f"Expected a CommandLineTool, but got {type_of_cwl_tool}")
            raise TypeError(f"Expected a CommandLineTool, but got {type_of_cwl_tool}")

        self.cwl_tool=cwl_tool
        self.setCWLVersion()
        self.logger_setcwl.debug(f"Received new cwl tool")
        self.logger_setcwl.debug(f"Class       : {self.cwl_tool.class_}")
        self.logger_setcwl.debug(f"CWL version : {self.cwl_tool.cwlVersion}")
        # self.updateSignal.emit('cwl_tool')


    def _findRequirementIndex(self, query_requirement:str, create=False) ->int:
        ''' 
        Find a requirement in the CWL document by its class name, creating it if necessary.
        
        This method searches through the requirements list for a requirement of the
        specified type. If not found and create=True, it will create a new requirement
        using the appropriate cwl-utils class based on the document's CWL version.
        
        Args:
            requirement (str): The class name of the requirement to find (e.g., 'DockerRequirement')
            create (bool, optional): Whether to create the requirement if not found. Defaults to True.
            
        Returns:
            int: The index of the requirement in the requirements list, or None if
                 not found and create=False
        '''
        # Only look: the requirements list is created when one is added, so
        # that opening a tool does not change it
        self.logger.debug(f"Finding requirements index for { type(self.cwl_tool) }")
        req_index = None
        for i, req in enumerate(getattr(self.cwl_tool, 'requirements', None) or []):
            self.logger.debug(f"Checking requirement {i}: {req}")
            self.logger.debug(f"\t{type(req)}")
            if req.class_ == query_requirement:
                req_index = i
                break
                                
        # If requirement not found and create flag is True, create a new one
        if req_index is None and create:
            # Get the CWL version from the document
            cwl_module = get_cwl_module(self.cwl_tool.cwlVersion)
            
            # Create an empty requirement dynamically based on the requirement type
            if query_requirement == 'DockerRequirement':
                new_req = cwl_module.DockerRequirement()
            elif query_requirement == 'ResourceRequirement':
                new_req = cwl_module.ResourceRequirement()
            elif query_requirement == 'InitialWorkDirRequirement':
                new_req = cwl_module.InitialWorkDirRequirement()
            else:
                # Generic requirement creation
                new_req = {'class_': query_requirement}
                
            # Add it to the requirements list
            if getattr(self.cwl_tool, 'requirements', None) is None:
                self.cwl_tool.requirements = []
            self.cwl_tool.requirements.append(new_req)
            # Return the index of the newly added requirement
            req_index = len(self.cwl_tool.requirements) - 1
            self.logger.debug(f"Created new requirement of type {query_requirement} at index {req_index}")
            
        return req_index

    def _validateExpression(self, code, report):
        """Evaluate a redirect expression as the Expression Editor would."""
        validateExpression(self, None, code, report)

    def inspectCommandLinePart(self, loc: str) -> bool:
        """
        Show where a part of the command line preview comes from: the input or
        argument opens in the side panel, other parts scroll to their section.
        ``loc`` is the part's location, e.g. "inputs.src", "arguments[1]".
        """
        row = None
        if loc.startswith('inputs.'):
            input_id = loc.split('.')[1]
            rows = [r for r in self.findChildren(QInputWidget)
                    if r.line_edit_ID.text() == input_id and r.parent() is not None
                    and not isinstance(r.parent().parent(), QInputWidget)]
            row = rows[-1] if rows else None
        elif loc.startswith('arguments['):
            try:
                target = save(self.cwl_tool.arguments[int(loc[len('arguments['):-1])])
            except (ValueError, IndexError, TypeError):
                target = None
            rows = [r for r in self.findChildren(QArgumentWidget)
                    if target is not None and r.getCWL() is not None and save(r.getCWL()) == target]
            row = rows[-1] if rows else None
        if row is not None and hasattr(row, 'row_bar'):
            row.row_bar.clicked.emit()
            self.scroll_area.ensureWidgetVisible(row, 0, 40)
            return True
        section = {'baseCommand': self.basecommand, 'stdin': self.streams_widget,
                   'stdout': self.streams_widget}.get(loc.split('[')[0])
        if section is not None:
            self.scroll_area.ensureWidgetVisible(section, 0, 40)
            return True
        return False

    def _addRequirement(self, requirement):
        """Append a requirement, creating the list if the tool has none yet."""
        if getattr(self.cwl_tool, 'requirements', None) is None:
            self.cwl_tool.requirements = []
        self.cwl_tool.requirements.append(requirement)
    
    def populateFromCWL(self):
        '''
        set the relevant fields from the cwl_tool
        This is a function that should be triggered and 
        result in reevaluating the contents of the window from scratch
        '''
        # Store original signal blocking state
        old_state = self.blockSignals(True)
        
        # Save scroll position
        v_scroll_value = 0
        if hasattr(self, 'scroll_area'):
            v_scroll_value = self.scroll_area.verticalScrollBar().value()

        if self.cwl_tool:
            self.setCWLVersion(self.cwl_tool.cwlVersion)
        try:
            self.logger.debug(f"Received a new tool of class {self.cwl_tool.class_}")
            self.logger.debug(f"CWL version of this new tool is {self.cwl_version}")
            # take care of the basecommand 
            self.logger.debug("Processing the basecommand array")
            if self.cwl_tool.class_ =='CommandLineTool':
                self.logger.debug(f"\tActivating basecommand input")
                if hasattr(self.cwl_tool, 'baseCommand'):
                    self.logger.debug(f"\tThe basecommand is {self.cwl_tool.baseCommand}")
                self.expression_widget.setVisible(False)
                self.basecommand.setVisible(True)
                self.basecommand.setCWLVersion( self.cwl_version)
                self.stderr.setVisible(True)
                self.stdout.setVisible(True)
                self.streams_widget.setVisible(True)
                self.argument.setVisible(True)
                self.basecommand.populateFromCWL( self.cwl_tool.baseCommand or [])
            # take care of the expression for ExpressionTool
            if self.cwl_tool.class_=='ExpressionTool' :
                self.logger.debug(f"\tActivating expression input")
                if hasattr(self.cwl_tool, 'expression'):
                    self.logger.debug(f"\tThe expression is {self.cwl_tool.expression}")
                self.expression_widget.setVisible(True)
                self.basecommand.setVisible(False)
                self.stderr.setVisible(False)
                self.stdout.setVisible(False)
                self.streams_widget.setVisible(False)
                self.argument.setVisible(False)
                
                # self.expression.setCWLVersion( self.cwl_version)
                self.expression.setText( self.cwl_tool.expression or '')

            # take care of the docker image
            # find which requirement is the docker requirement
            # and send it to the Widget
            if hasattr(self, 'docker_image'):
                self.logger.debug(f"Processing DockerRequirement")
                docker_req_index = self._findRequirementIndex('DockerRequirement')
                self.logger.debug(f"\tDockerRequirement is in the {docker_req_index} position of the requirements")  
                # Pass the docker requirement to the widget (null if not found)
                docker_req = None
                if docker_req_index is not None:
                    docker_req = self.cwl_tool.requirements[docker_req_index]
                    self.docker_image.setCWLVersion( self.cwl_version)
                    self.docker_image.populateFromCWL(docker_req)

            # add the stream redirects and exit codes (Other section)
            if hasattr(self, 'stdout') and hasattr(self.cwl_tool, 'stdout'):
                self.stdout.setText( self.cwl_tool.stdout or '' )
            if hasattr( self, 'stderr') and hasattr(self.cwl_tool, 'stderr'):
                self.stderr.setText( self.cwl_tool.stderr or '' )
            if hasattr(self, 'stdin') and hasattr(self.cwl_tool, 'stdin'):
                self.stdin.setText( self.cwl_tool.stdin or '' )
            for field, edit in (('successCodes', 'success_codes'),
                                ('temporaryFailCodes', 'temporary_fail_codes'),
                                ('permanentFailCodes', 'permanent_fail_codes')):
                if hasattr(self, edit) and hasattr(self.cwl_tool, field):
                    getattr(self, edit).setText(','.join(map(str, getattr(self.cwl_tool, field) or [])))
            
            # add the requirements
            if hasattr(self, 'resourcerequirements'):
                self.logger.debug(f"Processing ResourceRequirement")
                
                resreq_req_index=self._findRequirementIndex('ResourceRequirement')
                self.logger.debug(f"\tResourceRequirement is in the {resreq_req_index} position of the requirements")  
                if resreq_req_index:
                    self.resourcerequirements.setCWLVersion( self.cwl_version)
                    self.resourcerequirements.populateFromCWL(self.cwl_tool.requirements[resreq_req_index] )

            if hasattr(self, 'requirements'):
                self.logger_requirements.debug(f"Populating Requirements")
                self.requirements.setCWLVersion( self.cwl_version)
                self.requirements.populateFromCWL(self.cwl_tool.requirements or [])
            
            if hasattr(self, 'envvar'):
                self.logger_envvar.debug(f"Populating EnvVarRequirement")
                envvar_req_index=self._findRequirementIndex('EnvVarRequirement')
                self.logger_envvar.debug(f"\tEnvVarRequirement is in the {envvar_req_index} position of the requirements")  
                if envvar_req_index is not None:
                    self.envvar.setCWLVersion( self.cwl_version)
                    self.envvar.populateFromCWL(self.cwl_tool.requirements[envvar_req_index] )

            if hasattr(self, 'initial_workingdir'):
                self.logger_requirements.debug(f"Populating InitialWorkDirRequirement")
                initialdir_req_index=self._findRequirementIndex('InitialWorkDirRequirement')
                self.logger.debug(f"\tInitialWorkDirRequirement is in the {initialdir_req_index} position of the requirements")  
                if initialdir_req_index:
                    self.initial_workingdir.setCWLVersion( self.cwl_version)
                    self.initial_workingdir.populateFromCWL(self.cwl_tool.requirements[ initialdir_req_index])


            # add the arguments
            if hasattr( self, 'argument') and hasattr(self.cwl_tool, 'arguments'):
                self.argument.setCWLVersion( self.cwl_version)
                self.argument.populateFromCWL( self.cwl_tool.arguments or [])

            # add the inputs
            if hasattr( self, 'input'):
                self.logger_inputs.debug(f"Processing  Inputs")
                self.input.setCWLVersion( self.cwl_version)
                self.input.populateFromCWL( self.cwl_tool.inputs or [])

            # add the outputs
            if hasattr( self, 'output'):
                self.output.setCWLVersion( self.cwl_version)
                self.output.populateFromCWL( self.cwl_tool.outputs or  [])
        finally:
            # Restore original signal blocking state
            self.blockSignals(old_state)
            
            # Restore scroll position
            if hasattr(self, 'scroll_area'):
                self.scroll_area.verticalScrollBar().setValue(v_scroll_value)

            # The rows were rebuilt: keep the inspected entry marked, or close
            # the inspector if the entry is gone
            if hasattr(self, 'inspector'):
                QTimer.singleShot(0, self.inspector.entriesRefreshed)

     
    def onExpressionCodeClicked(self,widget_to_update=None):
        '''
        edit the expression that is used for the ExpressionTool
        '''
        # Show the dialog
        dialog = JavaScriptEditorDialog(parent=self)
        if self.expression.text():
            dialog.editor.setText( self.expression.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            code = dialog.get_javascript_code()
            # print("JavaScript code submitted:", code)
            if code:
                self.expression.setText( code)
                # Update the CWL tool with the new expression
                if hasattr(self.cwl_tool, 'expression'):
                    self.cwl_tool.expression = code
                self.codeUpdated.emit('Expression updated')        
    
    def onDockerImageChange(self):
        '''
        Handles updates to the Docker image requirement when the text field changes.
        
        This function is triggered when the user edits the Docker image field.
        It dynamically creates or updates a DockerRequirement in the CWL document
        using the appropriate class from cwl-utils based on the document's CWL version.
        
        Returns:
            None
        '''
        # Get the docker image value from the widget
        # the result value depends on the cwlVersion
        docker_req = self.docker_image.getData(self.cwl_tool.cwlVersion)
        self.logger.debug(f"Updating the DockerRequirement with {docker_req.dockerPull}")
        # Find the Docker requirement index
        docker_req_index = self._findRequirementIndex('DockerRequirement')
        # If empty, we might want to remove the requirement
        if not docker_req.dockerPull and docker_req_index is not None:
            # Remove the Docker requirement if it exists and the image is empty
            self.cwl_tool.requirements.pop(docker_req_index)
            self.codeUpdated.emit("CWL app updated")
            return

        # If Docker requirement exists, update it
        try:
            if docker_req_index is not None:
                self.cwl_tool.requirements[docker_req_index] = docker_req
            # If it doesn't exist, create a new one
            else:
                self._addRequirement(docker_req)
            
            # Emit the signal that the CWL code has been updated
            self.codeUpdated.emit("CWL app updated")
        except Exception as e:
            # Use QErrorMessage to show error and optionally raise the exception
            QErrorMessage.show_and_raise(
                parent=self,
                title="Docker Requirement Error",
                message="Failed to update Docker requirement",
                exception=e,
                logger=self.logger,
                raise_exception=True  # Don't raise the exception after showing dialog
            )
            
        self.logger.debug(f"DockerRequirement update complete")
        # No need for the nested_lookup/nested_update code, as we're directly 
        # manipulating the requirements object
    
    def onOutputsChange(self):
        '''
        update the arguments in the CWL 
        when the update is complete we update the editor 
        '''
        # retrive the data from the base command group
        self.logger.debug(f"We have new data for the outputs, we will receive them from the group")
        new_cwl= self.output.getData()
        # self.logger.debug(f"The new data we got is {save(new_cwl) }")
        new_cwl=self.sortCWL(new_cwl)
        new_cwl=[ {key: value for key, value in x.items() if key != 'entry_order'} for x in new_cwl]
        self.cwl_tool.outputs=[]
        
        for n in new_cwl:
            self.cwl_tool.outputs.append( n.get('argument') )
        #     print(f"output {n.get('argument')}")
        #     print(f"output {save( n.get('argument'),  )}")
        # sys.exit(123)
        self.codeUpdated.emit("CWL app updated")


    def editExpression(self, line_edit):
        """Edit a field's value in the expression editor."""
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.editor.setText(line_edit.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            line_edit.setText(dialog.get_javascript_code())
            line_edit.editingFinished.emit()

    def onStdinChange(self):
        """Update the stdin redirect of the tool."""
        if hasattr(self.cwl_tool, 'stdin'):
            self.cwl_tool.stdin = self.stdin.text() or None
            self.codeUpdated.emit("CWL app updated")

    def onCodesChange(self, field: str):
        """Update successCodes / temporaryFailCodes / permanentFailCodes (comma separated)."""
        if not hasattr(self.cwl_tool, field):
            return
        edit = {'successCodes': self.success_codes,
                'temporaryFailCodes': self.temporary_fail_codes,
                'permanentFailCodes': self.permanent_fail_codes}[field]
        codes = []
        for part in edit.text().split(','):
            part = part.strip()
            if part:
                try:
                    codes.append(int(part))
                except ValueError:
                    pass
        setattr(self.cwl_tool, field, codes or None)
        self.codeUpdated.emit("CWL app updated")

    def onStdoutChange(self):
        '''
        update the filename that holds the stdout
        ''' 
        try:
            self.cwl_tool.stdout=self.stdout.text() or None
            self.codeUpdated.emit("CWL app updated")
        except Exception as e:
            # Use QErrorMessage to show error and optionally raise the exception
            QErrorMessage.show_and_raise(
                parent=self,
                title="Standard Output Error",
                message="Failed to update stdout",
                exception=e,
                logger=self.logger,
                raise_exception=True  # Don't raise the exception after showing dialog
            )

    def onStderrChange(self):
        '''
        update the filename that holds the stderr
        ''' 
        try:
            self.cwl_tool.stderr=self.stderr.text() or None
            self.codeUpdated.emit("CWL app updated")
        except Exception as e:
            # Use QErrorMessage to show error and optionally raise the exception
            QErrorMessage.show_and_raise(
                parent=self,
                title="Standard Error Error",
                message="Failed to update stderr",
                exception=e,
                logger=self.logger,
                raise_exception=True  # Don't raise the exception after showing dialog
            )

    def onResourceRequirementsChange(self):
        '''
        Updates the ResourceRequirement in the CWL document when resource settings change.
        
        This method is triggered when resource requirement settings are modified in the UI.
        It gets a ResourceRequirement object from the UI widget and updates the CWL document.
        '''
        
        # Get the ResourceRequirement object from the widget
        resource_req = self.resourcerequirements.getData(self.cwl_tool.cwlVersion)
        self.logger.debug(f"Updating the ResourceRequirement with ramMin={getattr(resource_req, 'ramMin', None)}, coresMin={getattr(resource_req, 'coresMin', None)}")
        # If no resource requirements are specified, return early
        if resource_req is None:
            return
        
        # Find or create the ResourceRequirement index in the requirements list
        resreq_req_index = self._findRequirementIndex('ResourceRequirement')
        
        # If empty, we might want to remove the requirement
        if not resource_req and resreq_req_index is not None:
            # Remove the Resource requirement if it exists and the image is empty
            self.cwl_tool.requirements.pop(resreq_req_index)
            self.codeUpdated.emit("CWL app updated")
            return


        # Update the requirement in the requirements list
        try:
            if resreq_req_index is not None:
                self.cwl_tool.requirements[resreq_req_index] = resource_req
            else:
                self._addRequirement(resource_req)
            self.codeUpdated.emit("CWL app updated")
        except Exception as e:
            # Use QErrorMessage to show error and optionally raise the exception
            QErrorMessage.show_and_raise(
                parent=self,
                title="Resource Requirement Error",
                message="Failed to update Resource requirement",
                exception=e,
                logger=self.logger,
                raise_exception=True  # Don't raise the exception after showing dialog
            )


    def onRequirementsChange(self):
        
        
        # Get the CWL version from the document
        new_requirements = self.requirements.getData( self.cwl_tool.cwlVersion)
        self.logger_requirements.debug(f"Updating the Requirements with:")
        for x in new_requirements:
            self.logger_requirements.debug(f"\t{ x.class_}")
        try:
            # first we need to remove the old requirements by name
            # ShellCommandRequirement,InplaceUpdateRequirement,InlineJavascriptRequirement
            for x in ['ShellCommandRequirement','InplaceUpdateRequirement','InlineJavascriptRequirement']:
                idx=self._findRequirementIndex(x)
                if idx is not None:
                    self.logger_requirements.debug(f"\tRemoving {x} requirement")
                    self.cwl_tool.requirements.pop( idx )
                    
            for x in new_requirements:
                idx=self._findRequirementIndex(x.class_)
                self.logger_requirements.debug(f"\tAdding {x.class_} requirement")
                if idx is not None:
                    self.cwl_tool.requirements[idx]=x
                else:
                    self._addRequirement(x)
            
            self.codeUpdated.emit("CWL app updated")
        except Exception as e:
            # Use QErrorMessage to show error and optionally raise the exception
            QErrorMessage.show_and_raise(
                parent=self,
                title="Requirement Error",
                message="Failed to update Requirement",
                exception=e,
                logger=self.logger,
                raise_exception=True  # Don't raise the exception after showing dialog
            )


    def onInitialWorkdirChange(self):
        '''
        Updates the InitialWorkDirRequirement in the CWL document when settings change.
        
        This method is triggered when initial working directory settings are modified
        in the UI. It creates a version-specific InitialWorkDirRequirement object 
        using cwl-utils based on the document's CWL version, populates it with
        the listing data from the UI, and updates the CWL document.
        '''
        requirement = self.initial_workingdir.getData()
        
        
        class_req_index = self._findRequirementIndex('InitialWorkDirRequirement')
        
        
        # Update the requirement in the requirements list
        if class_req_index is not None:
            self.cwl_tool.requirements[class_req_index] = requirement
        else:
            self._addRequirement(requirement)
        
        self.codeUpdated.emit("CWL app updated")

    def onEnvVarChange(self):
        '''
        Updates the EnvVarRequirement in the CWL document when settings change.
        
        This method is triggered when initial working directory settings are modified
        in the UI. It creates a version-specific EnvVarRequirement object 
        using cwl-utils based on the document's CWL version, populates it with
        the listing data from the UI, and updates the CWL document.
        '''
        requirement = self.envvar.getData()
        
        self.logger_envvar.debug(f"Updating the EnvVarRequirement with {requirement}\n{json.dumps(save(requirement), indent=2,default=str)}")
        class_req_index = self._findRequirementIndex('EnvVarRequirement')
        self.logger_envvar.debug(f"\tEnvVarRequirement is in the {class_req_index} position of the requirements")
        
        # Update the requirement in the requirements list
        if class_req_index is not None:
            self.cwl_tool.requirements[class_req_index] = requirement
        else:
            self._addRequirement(requirement)
        self.logger_envvar.debug(f"Updated the EnvVarRequirement")
        self.codeUpdated.emit("CWL app updated")

    def manageRequirements(self, requirement:dict):
        '''
        manage the requirements section
        adds a new requirement or updates an existing one
        '''
        # Make sure requirements list exists
        if not hasattr(self.cwl_tool, 'requirements') or self.cwl_tool.requirements is None:
            self.cwl_tool.requirements = []
            
        req_class = requirement.get('class_')
        if not req_class:
            return
            
        # Find if this requirement already exists
        req_index = next((i for i, req in enumerate(self.cwl_tool.requirements) 
                          if req.get('class_') == req_class), None)
                                
        # Update or add the requirement
        if req_index is not None:
            # Update existing requirement with new values
            for key, value in requirement.items():
                self.cwl_tool.requirements[req_index][key] = value
        else:
            # Add new requirement
            self.cwl_tool.requirements.append(requirement)
            self.logger.debug(f"Added new requirement of type {req_class}")




    def onBaseCommandChange(self):
        
        '''
        update the basecommands of a in the CWL 
        when the update is complete we update the editor
        '''
        # retrive the data from the base command group
        self.logger_basecommand.debug("Updating the baseCommand")
        new_cwl= self.basecommand.getData()
        self.logger_basecommand.debug(f"\tThe new baseCommand we got is {json.dumps( new_cwl )}")
        new_cwl=self.sortCWL(new_cwl)

        base_commands=[ x['command'] for x in new_cwl]
        self.logger_basecommand.debug(f"\tThe new baseCommand is {json.dumps( base_commands)}")
        # Leave the document alone when nothing changed ("echo" and ["echo"]
        # are the same base command), e.g. while the list is being filled
        current = getattr(self.cwl_tool, 'baseCommand', None)
        current = [current] if isinstance(current, str) else list(current or [])
        if current == base_commands:
            return
        try:
            self.cwl_tool.baseCommand = base_commands
            self.codeUpdated.emit("CWL app updated")
        except Exception as e:
            self.logger.critical(f"Cannot update the baseCommand")
            raise Exception(f"Unable to update the baseCommand\n{e}")

    def onArgumentsChange(self):
        '''
        update the arguments in the CWL 
        when the update is complete we update the editor 
        '''
        # retrieve the data from the arguments group
        self.logger.debug(f"We have new data for the arguments, we will receive them from the group")
        new_cwl= self.argument.getData()
        self.logger.debug(f"The new data we got is {json.dumps( new_cwl , default=str)}")
        new_cwl=self.sortCWL(new_cwl)
        new_cwl=[ {key: value for key, value in x.items() if key != 'entry_order'} for x in new_cwl]
        self.cwl_tool.arguments=[]
        for n in new_cwl:
            self.cwl_tool.arguments.append( n.get('argument') )
        
        self.codeUpdated.emit("CWL app updated")

    def onInputsChange(self):
        '''
        update the inputs in the CWL 
        when the update is complete we update the editor 
        '''
        # retrive the data from the base command group
        self.logger_inputs.debug(f"We have new data for the inputs, we will receive them from the group")
        new_cwl= self.input.getData()
        self.logger_inputs.debug(f"The new data we got is {new_cwl }")
        new_cwl=self.sortCWL(new_cwl)
        new_cwl=[ {key: value for key, value in x.items() if key != 'entry_order'} for x in new_cwl]
        # new_cwl=self.arrangeExclusiveRecord(new_cwl)
        self.cwl_tool.inputs=[]
        for n in new_cwl:
            self.cwl_tool.inputs.append( n.get('argument') )
        # new_cwl=self.arrangeDependentRecord(new_cwl)
        self.codeUpdated.emit("CWL app updated")




    def sortCWL(self, array):
        '''
        sort an array of dict
        first by order and then by entry_order
        '''
        # order the elements by the order we have submitted 
        # remove any empty elements
        self.logger_sort.debug(f"The array before sorting is {json.dumps( array, indent=3, default=str)}")
        clean_array=[ x for x in array if x is not None]
        sorted_array = sorted(clean_array, key=lambda x: ( 
            x.get('order', float('inf')), 
            x.get('entry_order',float('inf')))) # sort by order and then entry_order 
        # self.logger.debug(f"The sorted array is {json.dumps( sorted_array), indent=3}")
        self.logger_sort.debug(f"The array after sorting is {json.dumps( sorted_array, indent=3, default=str)}")
        return sorted_array
        # add the basecommand to the cwl_dict
        #= [ x[0] for x in sorted_base_commands if x[0] is not None]
