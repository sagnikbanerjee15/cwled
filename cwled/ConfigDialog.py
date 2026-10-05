from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import *
import data
import logging
import json
from copy import deepcopy
from widgets.qLabelLineEditWidget import QLabelLineEditWidget
from configuration import Configuration
import theme

class ConfigDialog(QDialog):
    """
    Dialog for editing application configuration settings.
    
    This dialog allows users to modify the configuration details stored in 
    the data.configuration dictionary.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Settings")
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        
        # Create a deep copy of the configuration to work with
        self.config = deepcopy(data.configuration)
        
        self.initUI()
        
    def initUI(self):
        """Initialize the user interface."""
        # Main layout
        main_layout = QVBoxLayout(self)
        
        # Create a tab widget to organize different configuration sections
        self.tab_widget = QTabWidget()
        
        # Create tabs for different configuration categories
        self.createGeneralTab()
        self.createLoggingTab()
        # self.createCWLVersionsTab()
        self.createPathsTab()
        self.createFormatTab()
        self.createAIAssistantTab()
        
        main_layout.addWidget(self.tab_widget)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        
        # Set a fixed dialog size (slightly larger to accommodate more settings)
        self.setFixedSize(620, 480)
        
    def createGeneralTab(self):
        """Create the General tab with basic configuration options."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # App name
        self.app_name_edit = QLabelLineEditWidget(
            label_text="Application Name",
            placeholder_text="Name of the application",
            parent=self
        )
        self.app_name_edit.setText(self.config.get('title', ''))
        layout.addWidget(self.app_name_edit)
        
        # Default CWL version
        default_cwl_version_layout = QHBoxLayout()
        label = QLabel("Default CWL Version")
        label.setFixedWidth(150)
        self.default_cwl_version = QComboBox()
        
        # Populate with available CWL versions
        for version in self.config.get('cwl_version', []):
            self.default_cwl_version.addItem(version.get('name', ''))
        
        # Set current default
        current_default = self.config.get('default_cwl_version', '')
        if current_default:
            index = self.default_cwl_version.findText(current_default)
            if index >= 0:
                self.default_cwl_version.setCurrentIndex(index)
        
        default_cwl_version_layout.addWidget(label)
        default_cwl_version_layout.addWidget(self.default_cwl_version)
        layout.addLayout(default_cwl_version_layout)
        
        # Theme (applied at once when the dialog is accepted)
        theme_layout = QHBoxLayout()
        theme_label = QLabel("Theme")
        theme_label.setFixedWidth(150)
        self.theme_combo = QComboBox()
        for name in theme.themeNames():
            self.theme_combo.addItem(name)
            self.theme_combo.setItemData(self.theme_combo.count() - 1, theme.THEMES[name]['description'],
                                         Qt.ItemDataRole.ToolTipRole)
        self.theme_combo.setCurrentText(theme.currentTheme())
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        layout.addLayout(theme_layout)

        # Reopen the last session
        self.restore_session_check = QCheckBox("Reopen the documents and windows of the last session at start")
        self.restore_session_check.setChecked(bool(self.config.get('restore_session', True)))
        layout.addWidget(self.restore_session_check)
        
        # Window size settings
        window_size_group = QGroupBox("Window Size")
        window_size_layout = QGridLayout()
        
        # Width
        width_label = QLabel("Initial Width:")
        self.initial_width_spin = QSpinBox()
        self.initial_width_spin.setRange(500, 3000)
        self.initial_width_spin.setValue(self.config.get('main_window', {}).get('initial_width', 800))
        
        # Height
        height_label = QLabel("Initial Height:")
        self.initial_height_spin = QSpinBox()
        self.initial_height_spin.setRange(400, 2000)
        self.initial_height_spin.setValue(self.config.get('main_window', {}).get('initial_height', 600))
        
        window_size_layout.addWidget(width_label, 0, 0)
        window_size_layout.addWidget(self.initial_width_spin, 0, 1)
        window_size_layout.addWidget(height_label, 1, 0)
        window_size_layout.addWidget(self.initial_height_spin, 1, 1)
        
        window_size_group.setLayout(window_size_layout)
        layout.addWidget(window_size_group)
        
        # Add some spacing and stretching
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "General")
        
    def createLoggingTab(self):
        """Create the Logging tab for log level configuration."""
        tab = QWidget()
        
        # Create a scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        # Create a container widget for the scroll area
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        
        # Get all loggers from the config
        log_levels = self.config.get('logLevel', {})
        
        for logger_name, current_level in sorted(log_levels.items()):
            log_level_layout = QHBoxLayout()
            
            label = QLabel(logger_name)
            label.setFixedWidth(200)
            
            combo = QComboBox()
            combo.addItems(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
            
            combo.setCurrentText(current_level)
            
            combo.currentTextChanged.connect(
                lambda text, logger_name=logger_name: self.updateLogLevel(logger_name, text)
            )
            
            log_level_layout.addWidget(label)
            log_level_layout.addWidget(combo)
            
            layout.addLayout(log_level_layout)
            
        layout.addStretch()

        # Set the container widget for the scroll area
        scroll_area.setWidget(scroll_content)
        
        # Create the main layout for the tab and add the scroll area
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "Logging")
        
    def createCWLVersionsTab(self):
        """Create the CWL Versions tab for managing supported CWL versions."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Create a list widget for CWL versions
        self.cwl_versions_list = QListWidget()
        
        # Populate the list with current CWL versions
        self.updateCWLVersionsList()
        
        layout.addWidget(QLabel("Supported CWL Versions:"))
        layout.addWidget(self.cwl_versions_list)
        
        # Add buttons for adding/editing/removing CWL versions
        buttons_layout = QHBoxLayout()
        
        add_button = QPushButton("Add")
        edit_button = QPushButton("Edit")
        remove_button = QPushButton("Remove")
        
        add_button.clicked.connect(self.addCWLVersion)
        edit_button.clicked.connect(self.editCWLVersion)
        remove_button.clicked.connect(self.removeCWLVersion)
        
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(edit_button)
        buttons_layout.addWidget(remove_button)
        buttons_layout.addStretch()
        
        layout.addLayout(buttons_layout)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "CWL Versions")
        
    def createPathsTab(self):
        """Create the Paths tab for configuring file and directory paths."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Default workspace
        workspace_layout = QHBoxLayout()
        workspace_label = QLabel("Workspace:")
        workspace_label.setFixedWidth(150)
        self.workspace_edit = QLineEdit()
        self.workspace_edit.setToolTip("The first workspace folder. More folders can be added with "
                                       "File > Add Folder to Workspace...")
        
        # Get the workspace directory from configuration or use default
        workspace_dir = self.config.get('workspace', '')
        self.workspace_edit.setText(workspace_dir)
        
        browse_workspace_button = QPushButton("Browse...")
        browse_workspace_button.clicked.connect(lambda: self.browseDirectory(self.workspace_edit))
        
        workspace_layout.addWidget(workspace_label)
        workspace_layout.addWidget(self.workspace_edit)
        workspace_layout.addWidget(browse_workspace_button)
        
        # Add to layout
        layout.addLayout(workspace_layout)

        # PATH directories
        paths_layout = QVBoxLayout()
        paths_label = QLabel("Additional PATH directories (colon-separated):")
        paths_label.setToolTip("Directories to add to PATH environment variable. Separate multiple paths with ':' character.")
        
        self.paths_edit = QLineEdit()
        # Get the paths list from configuration and join with colon
        paths_list = self.config.get('paths', [])
        paths_str = ':'.join(paths_list)
        self.paths_edit.setText(paths_str)
        self.paths_edit.setPlaceholderText("e.g. /opt/homebrew/bin:/usr/local/bin")
        
        paths_layout.addWidget(paths_label)
        paths_layout.addWidget(self.paths_edit)
        layout.addLayout(paths_layout)

        # CWL runner settings
        cwl_runner_group = QGroupBox("CWL Runner")
        
        # Create a scroll area for cwl_runner settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        self.command_edits = {}
        if 'cwl_runner' in self.config:
            for key, value in self.config.get('cwl_runner', {}).items():
                widget = QLabelLineEditWidget(
                    label_text=f"{key}",
                    placeholder_text=f"Command for {key}",
                    parent=self
                )
                widget.setText(value)
                scroll_layout.addWidget(widget)
                self.command_edits[key] = widget

        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        
        cwl_runner_layout = QVBoxLayout()
        cwl_runner_layout.addWidget(scroll_area)
        cwl_runner_group.setLayout(cwl_runner_layout)

        layout.addWidget(cwl_runner_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Paths")
    
    def createFormatTab(self):
        """Create the Format tab for id formatting options."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Format id section
        format_id_group = QGroupBox("Format id")
        format_id_layout = QHBoxLayout()

        label = QLabel("Sanitize ID Format:")
        label.setFixedWidth(150)
        self.sanitize_id_combo = QComboBox()
        
        formats = ['camelCase', 'UpperCamelCase', 'lowerCamelCase', 'dash', 'keeAlphaNum', 'underscore']
        self.sanitize_id_combo.addItems(formats)
        
        current_format = self.config.get('sanitize_id', 'camelCase')
        if current_format in formats:
            index = self.sanitize_id_combo.findText(current_format)
            if index >= 0:
                self.sanitize_id_combo.setCurrentIndex(index)

        format_id_layout.addWidget(label)
        format_id_layout.addWidget(self.sanitize_id_combo)
        
        format_id_group.setLayout(format_id_layout)
        layout.addWidget(format_id_group)
        
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Format")
        
    def createAIAssistantTab(self):
        """Create the AI Assistant tab for LLM configurations."""
        import os
        from platformdirs import user_config_path
        from dotenv import dotenv_values

        tab = QWidget()
        # Use a scroll area in case the settings dialog is small
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)

        # Get current LLM config
        llm_config = self.config.get('llm', {})
        provider = llm_config.get('provider', 'google_genai')
        model = llm_config.get('LLMModel', 'gemini-2.5-flash')
        base_url = llm_config.get('base_url', '') or ''
        temp = float(llm_config.get('temperature', 0.1))
        max_tokens = int(llm_config.get('max_tokens', 4096))
        api_key_env = llm_config.get('api_key_env', 'GOOGLE_API_KEY') or ''

        # Load API key value securely
        api_key_value = ""
        if api_key_env:
            api_key_value = os.environ.get(api_key_env, "")
            user_directory = user_config_path(appname='cwled', ensure_exists=True)
            env_file = user_directory / 'cwled.env'
            if not api_key_value and env_file.exists():
                try:
                    config_env = dotenv_values(env_file)
                    api_key_value = config_env.get(api_key_env, "")
                except Exception:
                    pass

        # 1. Provider
        provider_layout = QHBoxLayout()
        provider_label = QLabel("LLM Provider:")
        provider_label.setFixedWidth(150)
        self.llm_provider_combo = QComboBox()
        self.llm_provider_combo.addItems(['google_genai', 'openai', 'anthropic', 'ollama'])
        self.llm_provider_combo.setCurrentText(provider)
        provider_layout.addWidget(provider_label)
        provider_layout.addWidget(self.llm_provider_combo)
        layout.addLayout(provider_layout)

        # 2. Model
        model_layout = QHBoxLayout()
        model_label = QLabel("Model Name:")
        model_label.setFixedWidth(150)
        self.llm_model_edit = QLineEdit()
        self.llm_model_edit.setText(model)
        self.llm_model_edit.setPlaceholderText("e.g., gemini-2.5-flash, gpt-4o-mini, llama3.1")
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.llm_model_edit)
        layout.addLayout(model_layout)

        # 3. Base URL
        url_layout = QHBoxLayout()
        url_label = QLabel("Base URL (Local/Custom):")
        url_label.setFixedWidth(150)
        self.llm_base_url_edit = QLineEdit()
        self.llm_base_url_edit.setText(base_url)
        self.llm_base_url_edit.setPlaceholderText("e.g., http://localhost:11434 (Optional)")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.llm_base_url_edit)
        layout.addLayout(url_layout)

        # 4. Temperature
        temp_layout = QHBoxLayout()
        temp_label = QLabel("Temperature (0.0 - 2.0):")
        temp_label.setFixedWidth(150)
        self.llm_temp_spin = QDoubleSpinBox()
        self.llm_temp_spin.setRange(0.0, 2.0)
        self.llm_temp_spin.setSingleStep(0.1)
        self.llm_temp_spin.setValue(temp)
        temp_layout.addWidget(temp_label)
        temp_layout.addWidget(self.llm_temp_spin)
        layout.addLayout(temp_layout)

        # 5. Max Tokens
        tokens_layout = QHBoxLayout()
        tokens_label = QLabel("Max Tokens:")
        tokens_label.setFixedWidth(150)
        self.llm_max_tokens_spin = QSpinBox()
        self.llm_max_tokens_spin.setRange(1, 32768)
        self.llm_max_tokens_spin.setSingleStep(128)
        self.llm_max_tokens_spin.setValue(max_tokens)
        tokens_layout.addWidget(tokens_label)
        tokens_layout.addWidget(self.llm_max_tokens_spin)
        layout.addLayout(tokens_layout)

        # 6. Key Env Var
        env_layout = QHBoxLayout()
        env_label = QLabel("API Key Env Name:")
        env_label.setFixedWidth(150)
        self.llm_key_env_edit = QLineEdit()
        self.llm_key_env_edit.setText(api_key_env)
        self.llm_key_env_edit.setPlaceholderText("e.g., GOOGLE_API_KEY, OPENAI_API_KEY (Optional)")
        env_layout.addWidget(env_label)
        env_layout.addWidget(self.llm_key_env_edit)
        layout.addLayout(env_layout)

        # 7. Key Value Input
        val_layout = QHBoxLayout()
        val_label = QLabel("API Key Value:")
        val_label.setFixedWidth(150)
        self.llm_key_val_edit = QLineEdit()
        self.llm_key_val_edit.setText(api_key_value)
        self.llm_key_val_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_key_val_edit.setPlaceholderText("Enter API Key value (kept secure)")
        val_layout.addWidget(val_label)
        val_layout.addWidget(self.llm_key_val_edit)
        layout.addLayout(val_layout)

        layout.addStretch()
        
        scroll_content.setLayout(layout)
        scroll_area.setWidget(scroll_content)
        
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "AI Assistant")
    
    def updateCWLVersionsList(self):
        """Update the CWL versions list widget with current config data."""
        self.cwl_versions_list.clear()
        for version in self.config.get('cwl_version', []):
            item = QListWidgetItem(f"{version.get('name')} - {version.get('description', '')}")
            item.setData(Qt.ItemDataRole.UserRole, version)
            self.cwl_versions_list.addItem(item)
    
    def addCWLVersion(self):
        """Add a new CWL version to the configuration."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Add CWL Version")
        
        layout = QVBoxLayout(dialog)
        
        name_edit = QLabelLineEditWidget(
            label_text="Version Name",
            placeholder_text="e.g., v1.0",
            parent=dialog
        )
        
        description_edit = QLabelLineEditWidget(
            label_text="Description",
            placeholder_text="Description of this CWL version",
            parent=dialog
        )
        
        layout.addWidget(name_edit)
        layout.addWidget(description_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text()
            description = description_edit.text()
            
            if name:
                new_version = {
                    'name': name,
                    'description': description
                }
                
                # Add to our config copy
                if 'cwl_version' not in self.config:
                    self.config['cwl_version'] = []
                    
                self.config['cwl_version'].append(new_version)
                
                # Update the list
                self.updateCWLVersionsList()
                
                # Update the default CWL version combo box
                self.default_cwl_version.addItem(name)
    
    def editCWLVersion(self):
        """Edit a selected CWL version."""
        current_item = self.cwl_versions_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a CWL version to edit.")
            return
            
        current_version = current_item.data(Qt.ItemDataRole.UserRole)
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit CWL Version")
        
        layout = QVBoxLayout(dialog)
        
        name_edit = QLabelLineEditWidget(
            label_text="Version Name",
            placeholder_text="e.g., v1.0",
            parent=dialog
        )
        name_edit.setText(current_version.get('name', ''))
        
        description_edit = QLabelLineEditWidget(
            label_text="Description",
            placeholder_text="Description of this CWL version",
            parent=dialog
        )
        description_edit.setText(current_version.get('description', ''))
        
        layout.addWidget(name_edit)
        layout.addWidget(description_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text()
            description = description_edit.text()
            
            if name:
                # Find the version in our config copy
                for i, version in enumerate(self.config.get('cwl_version', [])):
                    if version == current_version:
                        # Update the version
                        self.config['cwl_version'][i] = {
                            'name': name,
                            'description': description
                        }
                        break
                
                # Update the list
                self.updateCWLVersionsList()
                
                # Update the default CWL version combo box
                old_name = current_version.get('name', '')
                if old_name != name:
                    index = self.default_cwl_version.findText(old_name)
                    if index >= 0:
                        self.default_cwl_version.setItemText(index, name)
    
    def removeCWLVersion(self):
        """Remove a selected CWL version."""
        current_item = self.cwl_versions_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a CWL version to remove.")
            return
            
        current_version = current_item.data(Qt.ItemDataRole.UserRole)
        
        # Confirm deletion
        reply = QMessageBox.question(
            self, 
            "Confirm Deletion",
            f"Are you sure you want to remove the CWL version '{current_version.get('name')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Remove from our config copy
            self.config['cwl_version'] = [v for v in self.config.get('cwl_version', []) if v != current_version]
            
            # Update the list
            self.updateCWLVersionsList()
            
            # Update the default CWL version combo box
            name = current_version.get('name', '')
            index = self.default_cwl_version.findText(name)
            if index >= 0:
                self.default_cwl_version.removeItem(index)
    
    def browseDirectory(self, line_edit):
        """Open a directory browser dialog and update the line edit with the selected path."""
        current_dir = line_edit.text() or QDir.homePath()
        directory = QFileDialog.getExistingDirectory(
            self, 
            "Select Directory",
            current_dir,
            QFileDialog.Option.ShowDirsOnly
        )
        
        if directory:
            line_edit.setText(directory)
    
    def accept(self):
        """Save the configuration when the OK button is clicked."""
        import os
        from platformdirs import user_config_path

        # Update the configuration with the values from the UI
        
        # General tab
        self.config['title'] = self.app_name_edit.text()
        if hasattr(self, 'default_cwl_version'):
            self.config['default_cwl_version'] = self.default_cwl_version.currentText()
        
        self.config['restore_session'] = self.restore_session_check.isChecked()
        self.config['theme'] = self.theme_combo.currentText()
        
        # Make sure main_window dictionary exists
        if 'main_window' not in self.config:
            self.config['main_window'] = {}
            
        # Window size
        self.config['main_window']['initial_width'] = self.initial_width_spin.value()
        self.config['main_window']['initial_height'] = self.initial_height_spin.value()
        
        # Logging tab
        if hasattr(self, 'log_level_combos'):
            log_levels = {}
            for component, combo in self.log_level_combos.items():
                log_levels[component] = combo.currentText()
            self.config['logLevel'] = log_levels
        
        # Format tab
        if hasattr(self, 'sanitize_id_combo'):
            self.config['sanitize_id'] = self.sanitize_id_combo.currentText()
        
        # AI Assistant tab saving
        if hasattr(self, 'llm_provider_combo'):
            if 'llm' not in self.config:
                self.config['llm'] = {}
            self.config['llm']['provider'] = self.llm_provider_combo.currentText()
            self.config['llm']['LLMModel'] = self.llm_model_edit.text().strip()
            
            base_url = self.llm_base_url_edit.text().strip()
            self.config['llm']['base_url'] = base_url if base_url else None
            
            self.config['llm']['temperature'] = self.llm_temp_spin.value()
            self.config['llm']['max_tokens'] = self.llm_max_tokens_spin.value()
            
            api_key_env = self.llm_key_env_edit.text().strip()
            self.config['llm']['api_key_env'] = api_key_env if api_key_env else None
            
            # Save API Key value securely to cwled.env if provided
            api_key_val = self.llm_key_val_edit.text().strip()
            if api_key_env and api_key_val:
                try:
                    user_directory = user_config_path(appname='cwled', ensure_exists=True)
                    env_file = user_directory / 'cwled.env'
                    
                    # Read existing environment values to preserve other keys
                    from dotenv import dotenv_values
                    existing_values = {}
                    if env_file.exists():
                        try:
                            existing_values = dict(dotenv_values(env_file))
                        except Exception:
                            pass
                    
                    existing_values[api_key_env] = api_key_val
                    
                    # Write back to cwled.env
                    with open(env_file, 'w') as f:
                        for k, v in existing_values.items():
                            if k and v:
                                f.write(f"{k}={v}\n")
                    
                    # Set in current os.environ as well so it's active immediately
                    os.environ[api_key_env] = api_key_val
                    self.logger.info(f"Saved API key to {env_file} and activated in os.environ")
                except Exception as e:
                    self.logger.error(f"Error saving API key to cwled.env: {e}")

        # Paths tab
        if hasattr(self, 'workspace_edit'):
            self.config['workspace'] = self.workspace_edit.text()
        if hasattr(self, 'paths_edit'):
            # Split the colon-separated string into a list
            paths_str = self.paths_edit.text().strip()
            if paths_str:
                # Split by colon and filter out empty strings
                self.config['paths'] = [p.strip() for p in paths_str.split(':') if p.strip()]
            else:
                self.config['paths'] = []
        if hasattr(self, 'command_edits'):
            if 'cwl_runner' not in self.config:
                self.config['cwl_runner'] = {}
            for key, widget in self.command_edits.items():
                self.config['cwl_runner'][key] = widget.text()

        # Update the global configuration
        data.configuration.clear()
        data.configuration.update(self.config)
        if self.config['theme'] != theme.currentTheme():
            theme.setTheme(self.config['theme'], save=False)    # saved below with the rest
        
        # Save configuration to file if needed
        try:
            # Try to save the configuration
            configuration=Configuration(configuration_directory=data.config_directory)
            configuration.setConfiguration(data.configuration)
            conf_file=configuration.saveConfiguration()
            self.logger.info("Configuration saved to file")
            self.logger.info(f"New configuration saved in: '{conf_file}'")
            QMessageBox.information(
                self,
                "New configuration Saved ",
                f"New configuration saved to file: '{conf_file}'"
            )
        except Exception as e:
            self.logger.error(f"Error saving configuration: {str(e)}")
            QMessageBox.warning(
                self,
                "Configuration Save Error",
                f"Could not save configuration to file: {str(e)}"
            )
        
        self.logger.info("Configuration updated")
        super().accept()