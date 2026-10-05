"""
This module contains the QCWLedGroupWidget class.
"""
from typing import Any, Dict, List, Optional, Type

from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QDialog,
    QHBoxLayout
)

import logging
import theme
from .qHeader import HeaderWithAddButton
from widgets.QCWLedWidget import QCWLedWidget
from .qButtons import QRemoveButton
from JavascriptEditor import JavaScriptEditorDialog
from cwl_utils.parser import save


class QCWLedGroupWidget(QCWLedWidget):
    """
    A generic group widget that manages a list of other widgets.

    When this class is used:
    makeList() should be overridden to return the proper list from the CWL data.
    getData() returns a list of results from each child widget's getData().
    populateFromCWL() accepts a list of objects to populate each child widget.

    A child widget class must be provided that implements QCWLedWidget.
    codeUpdated = pyqtSignal() # emit it when JS code is updated
    initUI(): to setup the widget's UI.
    getData(): return the proper CWL type
    populatedFromCWL(): populates the UI from the input data
    setCWL(): overrides in order to check type of object.
    codeText(): returns the text that should be shown in the code editor.
    setCodeText(): sets the text from the code editor.
    clear(): overrides and clears the widget's data.
    
    addWidget(): overrides to add the proper child widget args (parent and cwl_version are added by default).
    """

    # widgets: List[QCWLedWidget] = []  # list of child widgets
    # label: str  # default label for the header

    def __init__(self,
                 parent: Optional[QWidget] = None,
                 cwl_tool: Optional[List[Dict[str, Any]]] = None,
                 cwl_version: str = "v1.0",
                 widget_class: Type[QCWLedWidget] = QCWLedWidget,
                 label: str = "Items"):
        """
        Initializes the QCWLedGroupWidget.

        Args:
            parent: The parent widget.
            cwl_tool: A list of dictionaries to populate the widgets.
            cwl_version: The CWL version string.
            widget_class: The class of the widget to be managed in the list.
            label: The label for the header.
        """
        self.widget_class = widget_class
        self.widget_rows: Dict[QCWLedWidget, QWidget] = {}
        self.label = label
        self.widgets=[]
        super().__init__(parent,
                         cwl_tool=cwl_tool,
                         cwl_version=cwl_version)
        # if self.cwl_tool:
        #     self.populateFromCWL(self.cwl_tool)

    # override the parent initUI method
    def initUI(self):
        """
        Initializes the user interface of the widget.
        """
        super().initUI()
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Header
        self.header = HeaderWithAddButton(self.label, parent=self)
        self.header.addButtonClicked.connect(self.addWidget)
        self.main_layout.addWidget(self.header)

        # Container for widgets
        self.container_widget = QWidget()
        self.container_layout = QVBoxLayout()
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)
        self.container_widget.setLayout(self.container_layout)

        self.main_layout.addWidget(self.container_widget)
        self.setLayout(self.main_layout)



    def setCWL(self,
               cwl_tool: Optional[Any] = None):
        
        super().setCWL(cwl_tool)



    # override the parent setCWLVersion method
    def setCWLVersion(self,
                      cwl_version: Optional[str]=None):
        """
        Sets the CWL version for all child widgets.
        """

        super().setCWLVersion(cwl_version)
        for widget in self.widgets:
            if hasattr(widget, 'setCWLVersion'):
                widget.setCWLVersion(self.cwl_version)
        self.logger.debug(f"CWL version set to {cwl_version}")

    @pyqtSlot()
    def addWidget(self,
                  cwl_data: Optional[Dict[str, Any]] = None,
                  **widget_kwargs):
        """
        Adds a new widget to the list, along with Remove and Code buttons.

        Args:
            cwl_data: Optional dictionary with CWL data to populate the widget.
            **widget_kwargs: Arbitrary keyword arguments passed to the widget's
                             constructor. This provides flexibility for
                             initializing different types of widgets.
        """
        # Add default arguments, allowing them to be overridden by widget_kwargs
        if 'cwl_version' not in widget_kwargs:
            widget_kwargs['cwl_version'] = self.cwl_version
        if 'parent' not in widget_kwargs:
            widget_kwargs['parent'] = self
        widget = self.widget_class(**widget_kwargs)
        widget.editingFinished.connect(self._emit_editing_finished)

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(theme.ROW_ACTION_SPACING)
        row_layout.addWidget(widget, 1)

        remove_button = QRemoveButton(parent=self)
        remove_button.clicked.connect(lambda: self.removeWidget(widget))
        row_layout.addWidget(remove_button)

        if cwl_data:
            widget.populateFromCWL(cwl_data)

        self.container_layout.addWidget(row_widget)
        self.widgets.append(widget)
        self.widget_rows[widget] = row_widget
        self.logger.debug(f"Added a new {self.widget_class.__name__} widget.")
        self._emit_editing_finished()

    @pyqtSlot()

    @pyqtSlot(object)
    def removeWidget(self, widget: QCWLedWidget):
        """
        Removes a widget from the list.
        """
        if widget in self.widgets:
            row_widget = self.widget_rows.pop(widget)
            # Hide the widget before removing to prevent focus issues
            # when the widget becomes a top-level window temporarily
            row_widget.hide()
            self.container_layout.removeWidget(row_widget)
            row_widget.setParent(None)
            row_widget.deleteLater()
            self.widgets.remove(widget)
            self.logger.debug(
                f"Removed a {self.widget_class.__name__} widget."
            )
            self._emit_editing_finished()

    def getData(self) -> List[Any]:
        """
        Retrieves data from all child widgets.
        This method needs to overriden so that
        the list of values that are returned is
        appropriate for the specific widget type.
        """
        return [widget.getData() for widget in self.widgets if widget.getData()]

    # override the parent populateFromCWL method
    def populateFromCWL(self, 
                        cwl_data: List[Dict[str, Any]]=None):
        """
        Populates the group with widgets based on the provided CWL data.
        """
        super().populateFromCWL(cwl_data)
        # Clear existing widgets first
        for widget in self.widgets[:]:
            self.removeWidget(widget)

        self.setCWL( cwl_data )
        if self.getCWL():
            elementsList=self.makeList()
            if not isinstance(elementsList, list):
                self.addWidget(cwl_data=elementsList)
            else: 
                for item_data in elementsList:
                  self.addWidget(cwl_data=item_data)
        self.logger.debug("Populated widgets from CWL data.")

    def makeList(self) -> List[Any]:
        """
        Converts the input data to a list 
        if it is not already a list.
        This is useful for a CWL type that includes multiple entries (e.g., EnvVarRequirement).
        """
        return self.getCWL() 
    
    def clear(self):
        """
        Clears all child widgets and resets the group widget.
        """
        super().clear()
        # Create a copy of the list to iterate over, as removeWidget modifies it
        for widget in self.widgets[:]:
            self.removeWidget(widget)
        self.logger.debug("Cleared all widgets in the group.")


# class QEnvVar(QCWLedWidget):
#     """
#     Class to handle a row of input for an environment variable.
#     """
#     codeUpdated = pyqtSignal()

#     def __init__(self,
#                  parent: Optional[QWidget] = None,
#                  cwl_version: str = "v1.0"):
#         super().__init__(parent=parent, cwl_version=cwl_version)

#     def initUI(self):
#         """
#         Initializes the user interface of the widget.
#         """
#         self.main_layout = QHBoxLayout()
#         self.main_layout.setContentsMargins(0, 0, 0, 0)

#         self.envName_edit_box = QLineEdit()
#         self.envName_edit_box.setPlaceholderText("Name")
#         self.main_layout.addWidget(self.envName_edit_box)

#         self.envValue_edit_box = QLineEdit()
#         self.envValue_edit_box.setPlaceholderText("Value")
#         self.main_layout.addWidget(self.envValue_edit_box)

#         self.setLayout(self.main_layout)

#         # Connect signals
#         self.envName_edit_box.editingFinished.connect(self._emit_editing_finished)
#         self.envValue_edit_box.editingFinished.connect(self._emit_editing_finished)

  

#     def getData(self) -> Dict[str, Any]:
#         """
#         Retrieves data from the widget.
#         """
#         name = self.envName_edit_box.text()
#         value = self.envValue_edit_box.text()
#         if name and value:
#             # This part might need adjustment based on how cwl_utils handles EnvironmentDef
#             # For now, returning a dictionary.
#             return {"envName": name, "envValue": value}
#         return {}

#     def populateFromCWL(self, cwl_data: Dict[str, Any]):
#         """
#         Populates the widget with data from a CWL environment definition.
#         """
#         if "envName" in cwl_data:
#             self.envName_edit_box.setText(cwl_data["envName"])
#         if "envValue" in cwl_data:
#             self.envValue_edit_box.setText(cwl_data["envValue"])


# # Main stub for testing
# if __name__ == "__main__":
#     import sys
#     from pathlib import Path
#     # Add the project root to the Python path to allow absolute imports
#     project_root = Path(__file__).resolve().parent.parent.parent
#     sys.path.insert(0, str(project_root))

#     from PyQt6.QtWidgets import QApplication
#     # Now that the path is set, we can use absolute imports
#     from cwled.widgets.QCWLedGroupWidget import QCWLedGroupWidget, QEnvVar

#     app = QApplication(sys.argv)

#     # Example CWL data for environment variables
#     cwl_env_vars = [
#         {"envName": "HOME", "envValue": "/root"},
#         {"envName": "PATH", "envValue": "/usr/local/bin:/usr/bin:/bin"}
#     ]

#     # Create and show the group widget
#     group_widget = QCWLedGroupWidget(
#         cwl_tool=cwl_env_vars,
#         widget_class=QEnvVar,
#         label="Environment Variables"
#     )
#     group_widget.show()

#     sys.exit(app.exec())
