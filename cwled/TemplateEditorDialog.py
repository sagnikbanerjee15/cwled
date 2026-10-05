from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QScrollArea, QWidget, QLabel, QLineEdit, 
    QTextEdit, QFormLayout, QMessageBox, QGroupBox
)
from ruamel.yaml import YAML
import json
from io import StringIO
import logging
import tempfile
import os
from pathlib import Path
import data

import theme
class TemplateEditorDialog(QDialog):
    """
    A dialog for editing CWL tool input templates.
    This dialog displays input fields for each parameter in the template
    and allows the user to provide values.
    """
    
    def __init__(self, template_yaml, parent=None):
        """
        Initialize the template editor dialog.
        
        Args:
            template_yaml (str): The YAML template content as string
            parent (QWidget, optional): Parent widget
        """
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'INFO'))
        self.setWindowTitle("Edit Template Values")
        self.template_yaml = template_yaml
        self.template_data = {}
        self.template_widgets = {}
        
        # Setup font settings from configuration
        self.font_family = data.configuration.get('main_window', {}).get('font_family', 'Arial')
        self.font_size = data.configuration.get('main_window', {}).get('font_size', 12)
        
        # If font size is too large for a dialog, scale it down
        if self.font_size > 14:
            self.font_size = 12
            
        self.setStyleSheet(f"font-family: {self.font_family}; font-size: {self.font_size}px;")
        
        try:
            yaml = YAML()
            self.template_data = yaml.load(template_yaml)
            if self.template_data is None:
                self.template_data = {}
        except Exception as e:
            self.logger.error(f"Error parsing template YAML: {e}")
            QMessageBox.critical(self, "Template Error", 
                                f"Failed to parse template YAML: {e}")
            self.template_data = {}
            
        self.setMinimumSize(800, 600)
        self.initUI()
        
    def initUI(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("Edit the template values below:")
        header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(header_label)
        
        # Create a scroll area for the template fields
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        # Create form layout for the template fields
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        
        # Process template data recursively
        self.create_input_widgets(self.template_data, "", form_layout)
        
        scroll_layout.addLayout(form_layout)
        scroll_content.setLayout(scroll_layout)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save Template")
        save_button.clicked.connect(self.on_save_template)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)
        main_layout.addLayout(button_layout)
    
    def create_input_widgets(self, data, path_prefix, layout):
        """
        Recursively create input widgets for each field in the template.
        
        Args:
            data: Template data dictionary or value
            path_prefix: Current path in the template hierarchy
            layout: Form layout to add widgets to
        """
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path_prefix}.{key}" if path_prefix else key
                
                if isinstance(value, dict):
                    # Create a collapsible group for nested dictionaries
                    group_box = QGroupBox(key)
                    group_layout = QFormLayout()
                    self.create_input_widgets(value, current_path, group_layout)
                    group_box.setLayout(group_layout)
                    layout.addRow(group_box)
                elif isinstance(value, list):
                    # For lists, create a text area with YAML formatting
                    label = QLabel(key)
                    text_edit = QTextEdit()
                    text_edit.setPlaceholderText(f"Enter {key} values (YAML format)")
                    
                    # Apply consistent font settings
                    self.apply_font_to_widget(text_edit)
                    
                    # Convert list to YAML string for display
                    yaml = YAML()
                    yaml_string = StringIO()
                    yaml.dump(value, yaml_string)
                    yaml_str = yaml_string.getvalue()
                    text_edit.setText(yaml_str)
                    
                    self.template_widgets[current_path] = text_edit
                    layout.addRow(label, text_edit)
                else:
                    # Simple key-value pairs get a line edit
                    label = QLabel(key)
                    line_edit = QLineEdit()
                    line_edit.setPlaceholderText(f"Enter value for {key}")
                    
                    # Apply consistent font settings
                    self.apply_font_to_widget(line_edit)
                    
                    # Set current value if not None
                    if value is not None:
                        line_edit.setText(str(value))
                    
                    # The 'class' field in CWL is a reserved field that defines the
                    # type of the object and should not be modified in a template
                    if key == 'class' or current_path.endswith('.class'):
                        line_edit.setReadOnly(True)
                        # Add some styling to indicate it's read-only
                        line_edit.setStyleSheet(f"background-color: {theme.INPUT_BG_DISABLED};")
                    
                    self.template_widgets[current_path] = line_edit
                    layout.addRow(label, line_edit)
        else:
            # Handle simple values at the root level
            if path_prefix:
                label = QLabel(path_prefix)
                line_edit = QLineEdit()
                line_edit.setPlaceholderText("Enter value")
                
                # Apply consistent font settings
                self.apply_font_to_widget(line_edit)
                
                if data is not None:
                    line_edit.setText(str(data))
                
                # The 'class' field in CWL is a reserved field that defines the
                # type of the object and should not be modified in a template
                if path_prefix == 'class':
                    line_edit.setReadOnly(True)
                    # Add some styling to indicate it's read-only
                    line_edit.setStyleSheet(f"background-color: {theme.INPUT_BG_DISABLED};")
                    
                self.template_widgets[path_prefix] = line_edit
                layout.addRow(label, line_edit)
    
    def get_template_values(self):
        """
        Collect the values from the widgets and create the updated template.
        
        Returns:
            dict: The template with updated values
        """
        result = {}
        
        for path, widget in self.template_widgets.items():
            path_parts = path.split('.')
            current = result
            
            # Navigate to the correct nested dictionary
            for part in path_parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            # Set the value based on widget type
            if isinstance(widget, QTextEdit):
                try:
                    # Parse YAML content from the text edit
                    yaml = YAML()
                    value = yaml.load(widget.toPlainText())
                    current[path_parts[-1]] = value
                except Exception as e:
                    self.logger.warning(f"Failed to parse YAML for {path}: {e}")
                    current[path_parts[-1]] = widget.toPlainText()
            else:
                # Handle QLineEdit
                value = widget.text()
                
                # Try to convert to appropriate type
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
                elif value.isdigit():
                    value = int(value)
                elif value and '.' in value and all(p.isdigit() for p in value.split('.')):
                    value = float(value)
                elif value == "":
                    value = None
                    
                current[path_parts[-1]] = value
        
        return result
    
    def get_template_yaml(self):
        """
        Get the template as YAML string.
        
        Returns:
            str: YAML representation of the template
        """
        template_values = self.get_template_values()
        yaml = YAML()
        yaml_string = StringIO()
        yaml.dump(template_values, yaml_string)
        return yaml_string.getvalue()
    
    def save_to_file(self, filename):
        """
        Save the template to a file.
        
        Args:
            filename (str): Path to save the template
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            with open(filename, 'w') as f:
                f.write(self.get_template_yaml())
            return True
        except Exception as e:
            self.logger.error(f"Failed to save template: {e}")
            return False
    
    def on_save_template(self):
        """
        Handle the Save Template button click.
        Opens a file dialog for the user to choose where to save the template.
        """
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        import os
        
        # Get the CWL file name to derive a sensible template name
        cwl_file_name = self.get_cwl_file_name()
        template_name = f"{os.path.splitext(cwl_file_name)[0]}-inputs.yaml" if cwl_file_name else "cwltool-inputs.yaml"
        
        # Determine the default directory for saving
        default_dir = self.get_default_save_directory()
        default_filename = os.path.join(default_dir, template_name)
        
        self.logger.debug(f"Opening save dialog with default path: {default_filename}")
        
        # Open file dialog
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Template",
            default_filename,
            "YAML files (*.yaml *.yml);;All files (*.*)"
        )
        
        if filename:
            # Ensure filename has .yaml extension if none provided
            if not filename.lower().endswith(('.yaml', '.yml')):
                filename += '.yaml'
            
            # Save the template to the selected file
            if self.save_to_file(filename):
                self.logger.info(f"Template saved to {filename}")
                QMessageBox.information(
                    self,
                    "Template Saved",
                    f"Template successfully saved to:\n{filename}"
                )
                self.accept()  # Close dialog with accept status
            else:
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Failed to save template to {filename}"
                )
                
    def get_default_save_directory(self):
        """
        Determine the default directory for saving templates.
        
        Returns:
            str: Path to the default save directory
        """
        # Try to get the CWL tool's directory from the parent window
        parent_window = self.parent()
        if parent_window:
            # Try to access file_path safely
            try:
                if hasattr(parent_window, 'file_path') and parent_window.file_path:
                    # Use the directory of the CWL file
                    return os.path.dirname(parent_window.file_path)
            except Exception as e:
                self.logger.warning(f"Error accessing parent file_path: {e}")
            
            # Try to access cwl_tool and then file_path
            try:
                if (hasattr(parent_window, 'cwl_tool') and 
                    hasattr(parent_window, 'file_path')):
                    if parent_window.file_path:
                        return os.path.dirname(parent_window.file_path)
            except Exception as e:
                self.logger.warning(f"Error accessing cwl_tool: {e}")
            
        # If that's not available, use the workspace root
        workspace_root = self.get_workspace_root()
        if workspace_root:
            return workspace_root
            
        # Fall back to temp directory if all else fails
        return tempfile.gettempdir()
        
    def get_workspace_root(self):
        """
        Get the root directory of the workspace.
        
        Returns:
            str: Path to the workspace root or None if not found
        """
        # Try to get workspace root from data configuration
        try:
            if hasattr(data, 'configuration'):
                config = data.configuration
                if isinstance(config, dict) and 'workspace_root' in config:
                    return config.get('workspace_root')
        except Exception as e:
            self.logger.warning(f"Error getting workspace root: {e}")
            
        # Try to find it from the current directory
        current_dir = os.getcwd()
        
        # Return the current directory
        return current_dir
        
    def get_cwl_file_name(self):
        """
        Get the filename of the CWL tool being edited.
        
        Returns:
            str: Filename of the CWL file or None if not found
        """
        parent_window = self.parent()
        if not parent_window:
            return None
            
        # Try to get the file path from parent window
        try:
            if hasattr(parent_window, 'file_path') and parent_window.file_path:
                return os.path.basename(parent_window.file_path)
        except Exception as e:
            self.logger.warning(f"Error getting file_path: {e}")
        
        # If there's no file path but we have a title that might contain the filename
        try:
            if hasattr(parent_window, 'windowTitle'):
                title = parent_window.windowTitle()
                # Many windows show "filename - application name"
                if ' - ' in title:
                    possible_filename = title.split(' - ')[0].strip()
                    if possible_filename.endswith(('.cwl', '.yaml', '.yml')):
                        return possible_filename
        except Exception as e:
            self.logger.warning(f"Error getting window title: {e}")
            
        return None
    
    def apply_font_to_widget(self, widget):
        """
        Apply consistent font settings to the given widget.
        
        Args:
            widget: The widget to apply font settings to
        """
        from PyQt6.QtGui import QFont
        
        font = QFont(self.font_family, self.font_size)
        widget.setFont(font)
