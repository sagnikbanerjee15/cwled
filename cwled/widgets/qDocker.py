from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from .qLabelLineEditWidget import QLabelLineEditWidget
from cwl_utils_handler import get_cwl_module
from typing import Any, Optional
from widgets.QCWLedWidget import QCWLedWidget


class QDockerWidget(QCWLedWidget):
    '''
    Widget for managing Docker requirement information in CWL tools.
    
    This widget allows users to specify a Docker image URI for a CWL tool.
    It follows the pattern of other requirement widgets in the project.
    
    Inherits from QCWLedWidget to standardize CWL data handling.
    '''
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        cwl_tool: Optional[Any] = None,
        cwl_version: Optional[str] = None
    ):
        '''
        Initialize the Docker widget.
        
        Args:
            parent: The parent widget
            cwl_tool: Docker requirement object from cwl-utils
            cwl_version: Version of the CWL specification
        '''
        super().__init__(parent=parent, cwl_tool=cwl_tool, cwl_version=cwl_version)
        # Now inherits:
        # - self.cwl_tool (used instead of docker_requirement)
        # - self.logger (replaces logger setup)
        # - self.editingFinished signal
        # - initUI is called by super().__init__
        
        self.logger.debug("Docker widget initialized")
    
    def initUI(self):
        '''
        Initialize the user interface components.
        
        Creates a layout with a QLabelLineEditWidget for entering
        the Docker image URI.
        '''
        super().initUI()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create the Docker image input field (Composer: "Docker Repository")
        self.docker_image = QLabelLineEditWidget(
            "Docker Repository",
            "docker image URI",
            parent=self,
            stacked=True
        )
        self.docker_image.editingFinished.connect(self.onDockerImageChanged)
        
        # Add widget to layout
        layout.addWidget(self.docker_image)
        layout.addStretch(1)
        
        # Set layout for this widget
        self.setLayout(layout)
        
        # Populate fields if we have initial data
        if self.default_value:
            self.populateFields()
    
    def onDockerImageChanged(self):
        '''
        Handler for when the Docker image URI is changed by the user.
        
        Updates the internal cwl_tool object and emits the editingFinished
        signal.
        '''
        self.logger.debug(
            f"Docker image changed to: {self.docker_image.text()}"
        )
        
        # Use _emit_editing_finished from QCWLedWidget
        self._emit_editing_finished()
    
    def populateFromCWL(self, cwl_data: Optional[Any] = None):
        '''
        Populates the widget with data from a CWL DockerRequirement.
        
        Args:
            cwl_data: A DockerRequirement object from cwl-utils,
                     or None if no Docker requirement exists.
        '''
        self.logger.debug("Populating Docker widget from CWL")
        
        # Call superclass method to set self.cwl_tool
        super().populateFromCWL(cwl_data)
        
        # Update the UI fields
        self.populateFields()
    
    def populateFields(self):
        '''
        Update the UI fields from the current cwl_tool data.
        '''
        # Clear the field if no requirement is provided
        if not self.default_value:
            self.docker_image.setText("")
            return
        
        # Set the Docker image field from the dockerPull property
        if hasattr(self.default_value, 'dockerPull') and self.default_value.dockerPull:
            self.docker_image.setText(self.default_value.dockerPull)
            self.logger.debug(
                f"Set Docker image to: {self.default_value.dockerPull}"
            )
        else:
            self.docker_image.setText("")
    
    def clear(self):
        '''
        Clear the widget's data and UI fields.
        '''
        super().clear()  # Sets self.cwl_tool to None
        self.docker_image.setText("")
    
    def getData(self, cwlVersion: str):
        '''
        Creates and returns a DockerRequirement object based on the user input.
        
        This method uses the cwl_utils_handler to dynamically load the
        appropriate CWL module for the specified version and create a
        DockerRequirement object.
        
        Args:
            cwlVersion (str): The CWL version to use for creating the
                DockerRequirement
        
        Returns:
            DockerRequirement: A DockerRequirement object with the dockerPull
                property set to the Docker image URI entered by the user
                              
        Raises:
            Exception: If cwlVersion is not provided
        '''
        if not cwlVersion:
            raise ValueError(
                "cwlVersion is required to create the DockerRequirement"
            )
        
        # Only create a new object if the Docker image is not empty
        if not self.docker_image.text().strip():
            return None
            
        cwl_module = get_cwl_module(cwlVersion)
        docker_req = cwl_module.DockerRequirement(
            dockerPull=self.docker_image.text()
        )
        return docker_req
    
    def setCWL(self, cwl_tool: Optional[Any]):
        '''
        Sets the CWL DockerRequirement data and updates the UI.
        
        Args:
            cwl_tool: A DockerRequirement object
        '''
        super().setCWL(cwl_tool)
        self.populateFields()
