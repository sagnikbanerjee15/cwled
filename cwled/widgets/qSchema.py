from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, 
    QApplication, QCompleter, QPushButton, QHBoxLayout, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QIcon
import csv
from pathlib import Path
import re
from typing import List, Optional,Any
from widgets.QCWLedWidget import QCWLedWidget
from widgets.QCWLedGroupWidget  import QCWLedGroupWidget
from helperFunctions import getResourcePath
import data

import theme
import logging
logger = logging.getLogger(__name__)
class QSchemaListGroupWidget(QCWLedGroupWidget):
    """
    A widget that manages a collection of QSchemaList instances representing
    different file formats.
    """
    widget_counter = 0

    def __init__(
            self, 
            cwl_tool: Optional[List[str]] = None, 
            parent=None, 
            cwl_version: Optional[str] = None
    ):
        
        super().__init__(
            parent=parent,
            cwl_tool=cwl_tool,
            cwl_version=cwl_version,
            widget_class=QSchemaList,
            label="File Formats")
        # logger and initUI are called in QCWLedWidget's __init__

   

    @pyqtSlot()
    def addWidget(self, 
                  cwl_data: Optional[Any] = None):
        """
        Add a new QSchemaList widget to the container.
        
        Args:
            working_directory: Optional dictionary with initial values
        """
        super().addWidget(
            cwl_data=cwl_data,
            parent=self,
            cwl_version=self.cwl_version
        )
        self.widget_counter += 1  # Increment counter when adding a widget

    def getData(self, *args: Any, **kwargs: Any) -> List[str]:
        """
        Returns the data from all QSchemaList widgets as
        a string.
        
        Returns:
            List of strings
        """
        contents = super().getData()

        
        return contents         
    
    def populateFromCWL(self, 
                        cwl_data: Optional[List[str]] = None):
        """
        Populates the widget with data from a CWL InitialWorkDirRequirement.
        
        Args:
            cwl_data: List of strings
        """
        super().populateFromCWL(cwl_data)  # Call base class method
        
        # # If we didn't get data, nothing to do
        # if cwl_data is None:
        #     return
            
        # self.logger.debug(f"Received file formats {cwl_data} to add to the layout")
        # self.widget_counter = 0
        # self.clear()

        # for ff in cwl_data:
        #     self.logger.debug(f"Adding file format {ff}")
        #     self.addSchemaWidget(format=ff)

    def clear(self, layout=None):
        """
        Clears all QSchemaList widgets from the container.
        
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
        self.widget_counter = 0  # Reset counter when clearing




class QSchemaList(QCWLedWidget):
    """
    A widget that displays a label and a dropdown list for schema selection.
    """
    _schema_data = None

    def __init__(self, 
                 parent=None,
                 cwl_tool=None,
                 cwl_version: Optional[str] = None):
        """
        Initializes the SchemaList widget.
        """
        self._load_schemas()  # Load schemas before initUI is called
        super().__init__(
            parent=parent,
            cwl_tool=cwl_tool,
            cwl_version=cwl_version)

    def initUI(self):
        # Create a layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        # Create a horizontal layout for the combo box and the info button
        combo_layout = QHBoxLayout()
        combo_layout.setContentsMargins(0, 0, 0, 0)

        # Create a searchable dropdown list
        self.combo_box = QComboBox()
        self.combo_box.setEditable(True)
        self.combo_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        if self._schema_data:
            items = ['-- None --']
            for i, row in enumerate(self._schema_data):
                label = row[1]
                items.append(label)
                self.combo_box.addItem(label)

            # Setup the completer
            completer = QCompleter(items, self)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.combo_box.setCompleter(completer)
        
        combo_layout.addWidget(self.combo_box)

        

        # Create an info button
        self.info_button = QPushButton()
        self.info_button.setIcon(theme.icon('info'))
        self.info_button.setFixedSize(24, 24)
        self.info_button.setFlat(True)
        combo_layout.addWidget(self.info_button)


        self.combo_box.setCurrentText('-- None --')
        layout.addLayout(combo_layout)

        # Set the layout for the widget
        self.setLayout(layout)

        # Connect signals and set initial tooltip
        self.combo_box.currentTextChanged.connect(self.update_info_tooltip)
        self.update_info_tooltip(self.combo_box.currentText())

    def update_info_tooltip(self, text: str):
        """
        Updates the tooltip of the info button with the description
        of the currently selected schema.
        """
        tooltip = "No description available."
        if self._schema_data:
            for row in self._schema_data:
                if row[1] == text:
                    if len(row) > 3 and row[3]:
                        tooltip = row[3]
                    break
        self.info_button.setToolTip(tooltip)


    def populateFromCWL(self, cwl_data: str):
        """
        Populates the combo box based on a string from a CWL file.

        It tries to find a matching schema in the loaded data using the
        following logic:
        1. Match the input string against the second column (Preferred Label).
        2. Match the input string against the first column (Class ID).
        3. Match the part of the input string before ' #' against the first
           column.

        If a match is found, the combo box is set to the corresponding label.
        Otherwise, it's set to the original input string.

        Args:
            schema_str (str): The schema string from the CWL file.
        """
        if not self._schema_data:
            self.combo_box.setCurrentText(schema_str)
            return

        # Try to find a match and get the corresponding label (row[1])
        match_label = None
        schema_str=cwl_data # for clarity
        # 1. Match against the second column
        for row in self._schema_data:
            if row[1] == schema_str or row[0] == schema_str:
                match_label = row[1]
                break

        # 3. If still no match, try the "id #" pattern
        if not match_label and " #" in schema_str:
            base_id = schema_str.split(" #")[0]
            for row in self._schema_data:
                if row[0] == base_id:
                    match_label = row[1]
                    break

        # Set the combo box text
        if match_label:
            self.combo_box.setCurrentText(match_label)
        else:
            self.combo_box.setCurrentText(schema_str + " !")

    def getTags(self):
        """
        Docstring for getTags
        
        alias for getData
        """
        return self.getData()
    def getData(self):
        """
        Returns the ID (first column) from the schema data that corresponds
        to the currently selected text in the combo box.
        """
        selected_text = self.combo_box.currentText()
        if selected_text  == '-- None --':
            return None
        if self._schema_data:
            for row in self._schema_data:
                if row[1] == selected_text:
                    return f"{row[0]} #{row[1]}"  
        # Return the text itself if no match is found, or if data is not loaded
        return selected_text

    @staticmethod
    def _load_schemas():
        """
        Loads schema information from the EDAM.tsv file.
        This method is static and loads the data only once.
        """
        if QSchemaList._schema_data is not None:
            return

        QSchemaList._schema_data = []
        # Path is relative to this file's location
        file_path = (
            getResourcePath() / "ontologies" / "EDAM.tsv"
        )

        try:
            with open(file_path, mode='r', encoding='utf-8') as tsvfile:
                reader = csv.reader(tsvfile, delimiter='\t')
                next(reader)  # Skip header row
                for row in reader:
                    if not re.search('format', row[0]):
                        continue
                    if row:
                        QSchemaList._schema_data.append(row[:4])
        except FileNotFoundError:
            logger.debug(f"Error: The file {file_path} was not found.")
            QSchemaList._schema_data = []
        except Exception as e:
            logger.debug(f"An error occurred: {e}")
            QSchemaList._schema_data = []


# Application setup
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    tag_widget = QSchemaListGroupWidget()
    tag_widget.show()
    mod=get_cwl_module( 'v1.2')

    
    test_data = ['BAM','PNG']
    tag_widget.populateFromCWL(test_data)
    

    # schema_list_widget = QSchemaList()
    # schema_list_widget.show()
    sys.exit(app.exec())
