from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor,QFontMetrics
import json, sys
import builtins
import data
import logging
import os
from helperFunctions import addArrayItem
from nested_lookup import nested_lookup, nested_update
from widgets.qLabelLineEditWidget import QLabelLineEditWidget
from widgets.qBaseCommand import QBaseCommandGroupWidget
from widgets.qArguments import QArgumentsGroupWidget
from widgets.qInputs import QInputsGroupWidget
from widgets.qOutputs import QOutputsGroupWidget
from widgets.qButtons import QLineSeparator, QCodeButton
from widgets.qRequirements import QResourceRequirementsWidget, QRequirementsWidget
from NetworkGraph import CWLGraph
from pathlib import Path
from typing import Union, Optional
from CWLparser import is_optional, get_type, Parser
from typing import Any
from urllib.parse import urlparse
from cwl_utils_handler import get_cwl_module,get_cwl_version


class RequiredTableItem(QTableWidgetItem):
    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            self_sort = self.data(Qt.ItemDataRole.UserRole)
            other_sort = other.data(Qt.ItemDataRole.UserRole)
            if self_sort is not None and other_sort is not None:
                return int(self_sort) < int(other_sort)
        return super().__lt__(other)

class WorkflowSummary( QWidget ):
    '''
    Main tool editor window.

    This class provides a summary view of a tool, including its description,
    inputs, and outputs. It uses a QSplitter to allow the user to adjust the
    relative sizes of the description, input table, and output table.

    Attributes:
        updateSignal (pyqtSignal): Signal emitted when the tool is updated.
        cwl_tool (dict): Dictionary containing the CWL (Common Workflow Language) tool description.
        logger (logging.Logger): Logger for the class.
        box (QTextBrowser): Widget to display the tool description.
        input_table (QTableWidget): Table to display the tool inputs.
        output_table (QTableWidget): Table to display the tool outputs.
    '''
    
    file_location=None
    cwl_workflow: Any =None
    def __init__(self,
                 cwl_workflow:Any=None, 
                 parent=None,
                 file_location: Union[ str | Path ]=None):
        '''
        Initialize the ToolSummary widget.

        Args:
            cwl_workflow (dict): Dictionary containing the CWL tool description.
            parent (QWidget, optional): Parent widget. Defaults to None.
            file_location : the path with the CWL to project
        '''
        super().__init__(parent)

        self.logger=logging.getLogger(__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(__name__, 'DEBUG'))
        self.cwl_workflow=cwl_workflow
        if file_location:
            self.file_location=file_location

        self.initUI()

    def initUI(self):
        '''
        Initialize the user interface
        '''
        layout = QVBoxLayout(self)

        # Add a splitter to include the box and tables
        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Vertical)


        # Add the graph of the tool
        # self.graph = CWLGraph(workflow_file=self.file_location, 
        #                       parent=self,
        #                       cwl_workflow=self.cwl_tool)
        
        # splitter.addWidget(self.graph)

        # Add text with the description of the tool
        self.box = QTextBrowser(self)
        splitter.addWidget(self.box)
        
        # Add a table with the inputs
        label_inputs = QLabel('Workflow Inputs')
        self.input_table = QTableWidget(self)
        self.input_table.setRowCount(0)  # Start with no rows; rows can be added as needed
        self.input_table.setColumnCount(5)
        self.input_table.setHorizontalHeaderLabels(['Required', 'Type', 'ID', 'Label', 'Description'])
        self.input_table.setSortingEnabled(True)
        self.input_table.itemChanged.connect(self.onInputItemChanged)
        
        # Create a widget to hold the label and table for inputs
        input_widget = QWidget()
        input_layout = QVBoxLayout()
        input_layout.addWidget(label_inputs)
        input_layout.addWidget(self.input_table)
        input_widget.setLayout(input_layout)
        splitter.addWidget(input_widget)

        # Add a table with the outputs
        label_outputs = QLabel('Workflow Outputs')
        self.output_table = QTableWidget(self)
        self.output_table.setRowCount(0)  # Start with no rows; rows can be added as needed
        self.output_table.setColumnCount(5)
        self.output_table.setHorizontalHeaderLabels(['Required', 'Type', 'ID', 'Label', 'Description'])
        self.output_table.setSortingEnabled(True)
        self.output_table.itemChanged.connect(self.onOutputItemChanged)
        
        # Create a widget to hold the label and table for outputs
        output_widget = QWidget()
        output_layout = QVBoxLayout()
        output_layout.addWidget(label_outputs)
        output_layout.addWidget(self.output_table)
        output_widget.setLayout(output_layout)
        splitter.addWidget(output_widget)
        
        # Add a table for workflow steps (only visible for workflows)
        label_steps = QLabel('Workflow Steps')
        self.steps_table = QTableWidget(self)
        self.steps_table.setRowCount(0)  # Start with no rows; rows can be added as needed
        self.steps_table.setColumnCount(5)  # Added columns for Conditional and Edit button
        self.steps_table.setHorizontalHeaderLabels(['Conditional', 'ID', 'Label', 'File Location', 'Actions'])
        self.steps_table.setSortingEnabled(True)
        self.steps_table.itemChanged.connect(self.onStepsItemChanged)
        
        # Create a widget to hold the label and table for workflow steps
        steps_widget = QWidget()
        steps_layout = QVBoxLayout()
        steps_layout.addWidget(label_steps)
        steps_layout.addWidget(self.steps_table)
        steps_widget.setLayout(steps_layout)
        self.steps_widget = steps_widget  # Store reference to control visibility
        splitter.addWidget(steps_widget)
        steps_widget.setVisible(False)  # Hide by default, only show for workflows

        # Add a table with Docker images used by workflow steps
        label_docker = QLabel('Docker images')
        self.docker_table = QTableWidget(self)
        self.docker_table.setRowCount(0)
        self.docker_table.setColumnCount(2)
        self.docker_table.setHorizontalHeaderLabels(['Docker image', 'Step IDs'])
        self.docker_table.setSortingEnabled(True)
        self.docker_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        docker_widget = QWidget()
        docker_layout = QVBoxLayout()
        docker_layout.addWidget(label_docker)
        docker_layout.addWidget(self.docker_table)
        docker_widget.setLayout(docker_layout)
        self.docker_widget = docker_widget
        splitter.addWidget(docker_widget)
        docker_widget.setVisible(False)

        layout.addWidget(splitter)
        self.setLayout(layout)

    def makeReadonlyCheckItem(self, checked: bool) -> RequiredTableItem:
        item = RequiredTableItem()
        item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        item.setData(Qt.ItemDataRole.UserRole, 1 if checked else 0)
        item.setData(Qt.ItemDataRole.UserRole + 1, True)
        return item

    def enforceReadonlyCheckItem(self, table: QTableWidget, item: QTableWidgetItem):
        if item is None or item.column() != 0:
            return

        is_readonly_check = bool(item.data(Qt.ItemDataRole.UserRole + 1))
        if not is_readonly_check:
            return

        expected_checked = int(item.data(Qt.ItemDataRole.UserRole) or 0) == 1
        expected_state = (
            Qt.CheckState.Checked if expected_checked else Qt.CheckState.Unchecked
        )
        if item.checkState() != expected_state:
            table.blockSignals(True)
            item.setCheckState(expected_state)
            table.blockSignals(False)

    def onInputItemChanged(self, item: QTableWidgetItem):
        self.enforceReadonlyCheckItem(self.input_table, item)

    def onOutputItemChanged(self, item: QTableWidgetItem):
        self.enforceReadonlyCheckItem(self.output_table, item)

    def onStepsItemChanged(self, item: QTableWidgetItem):
        self.enforceReadonlyCheckItem(self.steps_table, item)


    def setCWLWorkflow(self, cwl_workflow:Union[Any,None]=None):
        '''
        set the cwl tool to be edited
        it must be a CommandLineTool 
        '''

        type_of_cwl_workflow = type(cwl_workflow).__name__ if cwl_workflow else 'None'
        if type_of_cwl_workflow not in ['Workflow']:
            self.logger.error(f"Expected a Workflow, but got {type_of_cwl_workflow}")
            raise TypeError(f"Expected a Workflow, but got {type_of_cwl_workflow}")

        self.cwl_workflow = cwl_workflow
        self.setCWLVersion()
        self.logger.debug(f"Received new cwl tool")
        self.logger.debug(f"Class       : {self.cwl_workflow.class_}")
        self.logger.debug(f"CWL version : {self.cwl_workflow.cwlVersion}")
        # self.updateSignal.emit('cwl_tool')


    def setCWLVersion(self, cwl_version:Optional[str]=None):
        '''
        set the CWL version for the tool editor
        '''
        self.cwl_version=get_cwl_version( self.cwl_workflow)
        # if cwl_version:
        #     if self.cwl_version:
        #         self.logger_setcwl.debug(f"Changing version of CWL from {self.cwl_version} to  {cwl_version}") 
        #     self.cwl_version = cwl_version
        self.logger.debug(f"CWL version for {self.__class__.__name__} is set: {cwl_version}")



    def populateFromCWL(self, file_location:Union[str|Path]=None):
        if file_location:
            self.file_location=file_location
        # updated the graph
        if hasattr(self, 'graph'):
            if self.cwl_workflow.class_ in ['Workflow']:
                self.graph.setVisible(True)
                self.graph.setCWL(self.cwl_workflow)
                self.graph.setFileLocation( self.file_location)
                self.graph.makeGraph( )
                self.graph.showGraph( )
            else:
                self.graph.setVisible(False)

        # show the description of the tool in markdown format
        self.box.setMarkdown( self.cwl_workflow.doc)
        self.box.setReadOnly(True)
        self.input_table.setSortingEnabled(False)
        self.input_table.setRowCount(0)  # Start with no rows; rows can be added as needed
        for idx, input in enumerate( self.cwl_workflow.inputs):
            self.input_table.insertRow(idx)
            label_text = input.label if hasattr(input, 'label') and input.label else ""
            self.input_table.setItem(idx, 3, QTableWidgetItem(label_text))
            self.input_table.setItem(idx, 2, QTableWidgetItem(input.id.split("#")[-1]))
            
            # Create checkable item for Required column
            is_required = not is_optional(input)  # Invert optional to get required
            required_item = self.makeReadonlyCheckItem(is_required)
            self.input_table.setItem(idx, 0, required_item)
            
            type_of_items=get_type( input )
            types='/'.join( type_of_items )
            self.input_table.setItem(idx, 1, QTableWidgetItem(types))                           
            self.input_table.setItem(idx, 4, QTableWidgetItem(input.doc))

        self.input_table.resizeColumnsToContents()
        self.input_table.setSortingEnabled(True)
        self.output_table.setSortingEnabled(False)
        self.output_table.setRowCount(0)  # Start with no rows; rows can be added as needed
        for idx,output in enumerate( self.cwl_workflow.outputs ):
            self.output_table.insertRow(idx)
            self.output_table.setItem(idx, 3, QTableWidgetItem(output.label if output.label else ''))
            self.output_table.setItem(idx, 2, QTableWidgetItem(output.id.split("#")[-1]))
            
            # Create checkable item for Required column
            is_required = not is_optional(output)  # Invert optional to get required
            required_item = self.makeReadonlyCheckItem(is_required)
            self.output_table.setItem(idx, 0, required_item)
            
            type_of_items=get_type( output )
            types='/'.join( type_of_items  )
            self.output_table.setItem(idx, 1, QTableWidgetItem(types))                           
            self.output_table.setItem(idx, 4, QTableWidgetItem(output.doc))
        
        if hasattr(self.cwl_workflow, 'stdout') and self.cwl_workflow.stdout:
            idx=self.output_table.rowCount()
            self.output_table.insertRow(idx)
            self.output_table.setItem(idx, 2, QTableWidgetItem('standard out'))
            self.output_table.setItem(idx, 3, QTableWidgetItem( 'File'))                           
            self.output_table.setItem(idx, 1, QTableWidgetItem( 'File'))
            
            # Add checkable required item for stdout (always mandatory)
            required_item = self.makeReadonlyCheckItem(True)
            self.output_table.setItem(idx, 0, required_item)
            
            self.output_table.setItem(idx, 4, QTableWidgetItem( 'Standard output of tool'))
        else:
            self.logger.debug("This tool does not have stdout")
        
        if hasattr(self.cwl_workflow, 'stderr') and self.cwl_workflow.stderr:
            idx=self.output_table.rowCount()
            self.output_table.insertRow(idx)
            self.output_table.setItem(idx, 2, QTableWidgetItem('standard error'))
            self.output_table.setItem(idx, 3, QTableWidgetItem( 'File'))                           
            self.output_table.setItem(idx, 1, QTableWidgetItem( 'File'))
            
            # Add checkable required item for stderr (always mandatory)
            required_item = self.makeReadonlyCheckItem(True)
            self.output_table.setItem(idx, 0, required_item)
            
            self.output_table.setItem(idx, 4, QTableWidgetItem( 'Standard error of tool'))
        self.output_table.resizeColumnsToContents()
        self.output_table.setSortingEnabled(True)
        
        # Handle workflow steps table visibility and population
        if self.cwl_workflow.class_ == 'Workflow':
            self.steps_widget.setVisible(True)
            self.populateWorkflowSteps()
            self.docker_widget.setVisible(True)
            self.populateDockerImages()
        else:
            self.steps_widget.setVisible(False)
            self.docker_widget.setVisible(False)

    def _extract_docker_images_from_requirements(self, requirements: Any) -> set[str]:
        docker_images: set[str] = set()
        if not requirements:
            return docker_images

        for req in requirements:
            req_class = getattr(req, 'class_', None)
            if req_class == 'DockerRequirement':
                docker_pull = getattr(req, 'dockerPull', None)
                if docker_pull:
                    docker_images.add(str(docker_pull))
        return docker_images

    def _resolve_step_run_path(self, step_run: str, base_dir: Path) -> str:
        file_location = step_run
        parsed_url = urlparse(step_run)
        if parsed_url.scheme in ('file',):
            file_location = parsed_url.path
        return os.path.abspath(os.path.join(base_dir, file_location))

    def _extract_step_docker_images(self, step: Any, base_dir: Path) -> set[str]:
        docker_images: set[str] = set()
        if not hasattr(step, 'run'):
            return docker_images

        # External tool reference
        if isinstance(step.run, str):
            if step.run.startswith('#'):
                return docker_images

            try:
                run_path = self._resolve_step_run_path(step.run, base_dir)
                parsed_step = Parser(run_path)
                cwl_step_tool = parsed_step.getCWL()
                step_requirements = getattr(cwl_step_tool, 'requirements', None)
                docker_images.update(
                    self._extract_docker_images_from_requirements(step_requirements)
                )
            except Exception as e:
                self.logger.debug(
                    f"Could not parse step tool for Docker images ({step.run}): {e}"
                )
            return docker_images

        # Embedded tool definition
        step_requirements = getattr(step.run, 'requirements', None)
        docker_images.update(
            self._extract_docker_images_from_requirements(step_requirements)
        )
        return docker_images

    def populateDockerImages(self):
        """Populate Docker images table with image -> step IDs mapping."""
        self.docker_table.setSortingEnabled(False)
        self.docker_table.setRowCount(0)

        if not self.cwl_workflow or self.cwl_workflow.class_ != 'Workflow':
            self.docker_table.setSortingEnabled(True)
            return

        base_dir = Path(self.file_location).parent if self.file_location else Path.cwd()
        image_to_steps: dict[str, set[str]] = {}

        for step in self.cwl_workflow.steps:
            step_id = step.id.split("#")[-1] if hasattr(step, 'id') else '<unknown-step>'
            for image in self._extract_step_docker_images(step, base_dir):
                image_to_steps.setdefault(image, set()).add(step_id)

        for idx, image in enumerate(sorted(image_to_steps.keys())):
            self.docker_table.insertRow(idx)
            step_ids = ", ".join(sorted(image_to_steps[image]))
            self.docker_table.setItem(idx, 0, QTableWidgetItem(image))
            self.docker_table.setItem(idx, 1, QTableWidgetItem(step_ids))

        self.docker_table.resizeColumnsToContents()
        self.docker_table.setSortingEnabled(True)
            
    def populateWorkflowSteps(self):
        """
        Populate the workflow steps table with information from the steps in the workflow.
        Only called for CWL documents with class='Workflow'.
        """
        self.steps_table.setSortingEnabled(False)
        self.steps_table.setRowCount(0)
        workflow_steps = self.cwl_workflow.steps
        
        base_dir = ""
        if self.file_location:
            base_dir = Path(self.file_location).parent
            
        for idx, step in enumerate(workflow_steps):
            self.steps_table.insertRow(idx)

            # Set conditional flag (checked when step.when exists and is defined)
            is_conditional = hasattr(step, 'when') and step.when is not None
            conditional_item = self.makeReadonlyCheckItem(is_conditional)
            self.steps_table.setItem(idx, 0, conditional_item)
            
            # Set step label (use id if label is not available)
            step_label = step.label if hasattr(step, 'label') and step.label else step.id.split("#")[-1]
            self.steps_table.setItem(idx, 2, QTableWidgetItem(step_label))
            
            # Set step ID
            step_id = step.id.split("#")[-1]
            self.steps_table.setItem(idx, 1, QTableWidgetItem(step_id))
            
            # Set step file location
            file_location = ''
            is_editable = False
            step_class = ''
            
            if hasattr(step, 'run'):
                # Handle string references to external files
                if isinstance(step.run, str):
                    if step.run.startswith('#'):
                        # Internal reference
                        file_location = "Internal reference"
                    else:
                        # External file reference
                        # file_location = os.path.abspath( Path(self.file_location) / Path(step.run))
                        file_location = step.run
                        parsed_url = urlparse(step.run)
                        if parsed_url.scheme in ('file'):
                            # print("file url detected")
                            file_location = parsed_url.path
                        file_location = os.path.abspath( os.path.join( base_dir, file_location))
                       
                        
                        # if base_dir:
                        #     # Show the absolute path if we have the base directory
                        #     file_location = str(Path(file_location).resolve())
                        is_editable = True
                            
                        #     # Try to determine the class from the file extension or assume CommandLineTool
                        #     step_class = 'CommandLineTool'  # Default assumption
                # Handle inline tool definition
                else:
                    step_class = step.run.class_
                    file_location = f"Embedded {step_class}"
                    is_editable = False  # We don't support editing embedded tools in this implementation
            
            self.steps_table.setItem(idx, 3, QTableWidgetItem(file_location))
            
            # Add Edit button for this step
            edit_button = QPushButton("Edit")
            edit_button.setEnabled(is_editable)
            
            # Store step info in button properties for later access
            edit_button.setProperty("step_id", step_id)
            edit_button.setProperty("file_location", file_location)
            edit_button.setProperty("step_class", step_class)
            
            # Connect button to handler function
            edit_button.clicked.connect(self.openStepEditor)
            
            # Add button to the table
            self.steps_table.setCellWidget(idx, 4, edit_button)
        
        self.steps_table.resizeColumnsToContents()
        self.steps_table.setSortingEnabled(True)

    def openStepEditor(self):
        """
        Open a new child window to edit the selected step file.
        This is called when an "Edit" button is clicked in the workflow steps table.
        It creates a new ChildWindow similar to what would happen when selecting
        File -> New -> CommandLineTool or File -> New -> Workflow from the menu.
        """
        # Get the button that was clicked
        button = self.sender()
        if not button:
            return
            
        # Get step properties from the button
        step_id = button.property("step_id")
        file_location = button.property("file_location")
        step_class = button.property("step_class") or "CommandLineTool"  # Default to CommandLineTool
        
        # Check if the file exists
        file_path = Path(file_location)
        if not file_path.exists():
            QMessageBox.warning(self, "Error", f"The file {file_location} does not exist.")
            return
        
        # Get the main window instance
        main_window = self.window()
        while main_window and not isinstance(main_window, QMainWindow):
            main_window = main_window.parent()
            
        if not main_window:
            QMessageBox.warning(self, "Error", "Could not find the main window.")
            return
            
        # Create a new child window for the step
        try:
            from MainWindow import ChildWindow
            
            # Find the window showing this document: the main window, or a
            # window that tabs were torn off into. The step opens next to the
            # workflow, in the same window; the main window owns the documents.
            from WorkbenchWindow import WorkbenchWindow
            host = None
            parent_window = None
            
            current = self
            while current:
                if isinstance(current, WorkbenchWindow):
                    host = current
                    parent_window = current.controller
                    break
                current = current.parent()
                
            if parent_window:
                # Use the MainWindow's add_window_to_menu method
                window_id = parent_window.add_window_to_menu(step_class, host=host)
                
                # Now open the file in the new window
                if window_id in parent_window.open_windows:
                    parent_window.open_windows[window_id].menuOpenFile.emit(file_location)
                    
                    # Set a title that indicates this is editing a workflow step
                    parent_window.open_windows[window_id].setWindowTitle(
                        f"Edit Workflow Step: {step_id} - {file_location}")
            else:
                # Fallback: Create a standalone ChildWindow
                child_window = ChildWindow(window_id=0, cwl_type=step_class)
                child_window.menuOpenFile.emit(file_location)
                child_window.setWindowTitle(f"Edit Workflow Step: {step_id} - {file_location}")
                child_window.show()
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open step file: {str(e)}")
            self.logger.error(f"Error opening step file: {str(e)}")