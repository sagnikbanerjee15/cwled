from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QFont
import logging
import sys
import data
from typing import Optional, Dict
import json
from datetime import datetime
import jinja2
from pathlib import Path
from dotenv import load_dotenv
import data
import getpass
import os
from urllib.parse import urlparse
from helperFunctions import uriToPath
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Union, Optional, Any
from cwl_utils.parser import save
from CWLtoolFactory import CWLRunner
import tempfile
import data

from platformdirs import user_config_path

class BaseLLM:
    """
    Base class for LLM-based tools providing common functionality
    for model setup, system prompt preparation, and prompt invocation.
    Supports standard cloud models as well as local endpoints (Ollama/LM Studio).
    """
    model = None
    model_name: str = None
    system_prompt: str = None
    
    # Kept for backward compatibility but no longer limits model selection
    MODEL_PROVIDERS = {
        "gpt-4o-mini": ("openai", "OPENAI_API_KEY"),
        "gpt-4": ("openai", "OPENAI_API_KEY"),
        "gemini-2.5-flash": ("google_genai", "GOOGLE_API_KEY"),
    }
    
    def __init__(self, model: Optional[str] = None):
        """Initialize the BaseLLM with logging and model setup."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(
            data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG')
        )
        
        # Load from configuration
        llm_config = data.configuration.get('llm', {})
        
        # Read parameters from config
        self.provider = llm_config.get('provider', 'google_genai')
        self.base_url = llm_config.get('base_url', None)
        self.temperature = float(llm_config.get('temperature', 0.1))
        self.max_tokens = int(llm_config.get('max_tokens', 4096))
        self.api_key_env = llm_config.get('api_key_env', 'GOOGLE_API_KEY')
        
        # Determine model name
        if model:
            self.model_name = model
            # For backward compatibility, if a model matches a legacy provider, override provider and env key
            if model in self.MODEL_PROVIDERS:
                self.provider, self.api_key_env = self.MODEL_PROVIDERS[model]
                self.base_url = None
        else:
            self.model_name = llm_config.get('LLMModel', 'gemini-2.5-flash')
            
        self.setModel(self.model_name)
    
    def setModel(self, model: str):
        """
        Set and initialize the Chat Model based on configuration.

        Args:
            model (str): The name of the LLM model to use.
        """
        self.model_name = model
        
        # Resolve api key if needed
        api_key = None
        if self.api_key_env:
            # Try to get from environment first
            api_key = os.environ.get(self.api_key_env)
            
            if not api_key:
                # Load from cwled.env config file
                user_directory = user_config_path( 
                    appname='cwled',
                    ensure_exists=True
                )
                env_file = user_directory / 'cwled.env'
                
                if env_file.exists():
                    self.logger.info(f"API key '{self.api_key_env}' not in environment, loading from {env_file}")
                    load_dotenv(env_file, override=True)
                    api_key = os.environ.get(self.api_key_env)
            
            # Check if key is required (e.g. not local like Ollama, or local openai base_url)
            # If provider is Ollama, no key is needed. If provider is OpenAI with a local base_url, we don't enforce key.
            is_local = self.provider == "ollama" or (self.provider == "openai" and self.base_url and ("localhost" in self.base_url or "127.0.0.1" in self.base_url))
            if not api_key and not is_local:
                self.logger.warning(f"API key '{self.api_key_env}' not found.")
                QMessageBox.critical(
                    None,
                    "API Key Missing",
                    f"API key '{self.api_key_env}' is missing for provider '{self.provider}'.\n\n"
                    f"Please set the environment variable or create your cwled.env file with:\n"
                    f"{self.api_key_env}=your_api_key_here",
                )
                raise ValueError(f"API key '{self.api_key_env}' not found.")
        
        # Build keyword arguments for init_chat_model
        kwargs = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        
        if self.base_url:
            kwargs["base_url"] = self.base_url
            
        if api_key:
            kwargs["api_key"] = api_key
            
        self.logger.info(f"Initializing Chat Model '{model}' with provider '{self.provider}' and parameters: {list(kwargs.keys())}")
        
        try:
            self.model = init_chat_model(model, model_provider=self.provider, **kwargs)
            self.logger.debug(f"Model '{model}' initialized successfully with provider '{self.provider}'")
        except Exception as e:
            self.logger.exception(f"Error initializing Chat Model '{model}' with provider '{self.provider}'")
            QMessageBox.critical(
                None,
                "Model Initialization Error",
                f"Failed to initialize Chat Model '{model}' with provider '{self.provider}':\n{str(e)}"
            )
            raise
    
    def loadTemplate(self, template_name: str, **template_vars) -> str:
        """
        Load and render a Jinja2 template from the config directory.

        Args:
            template_name (str): Name of the template file.
            **template_vars: Variables to pass to the template.

        Returns:
            str: The rendered template content.
        """
        template_path = data.config_directory / template_name
        
        if not template_path.exists():
            self.logger.error(f"Template file not found: {template_path}")
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        try:
            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(data.config_directory),
                autoescape=jinja2.select_autoescape(['html', 'xml'])
            )
            template = env.get_template(template_name)
            rendered = template.render(**template_vars)
            self.logger.debug(f"Template '{template_name}' rendered successfully")
            return rendered
        except jinja2.TemplateError as e:
            self.logger.error(f"Jinja2 template error: {e}")
            raise Exception(f"Template rendering error: {e}")
    
    def invokeModel(self, user_content: str, parent_widget=None, 
                    progress_message: str = "Processing...") -> str:
        """
        Invoke the LLM model with the system prompt and user content.

        Args:
            user_content (str): The user message content.
            parent_widget: Optional parent widget for progress dialog.
            progress_message (str): Message to show in progress dialog.

        Returns:
            str: The model's response content.
        """
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_content),
        ]
        
        self.logger.debug(f"Invoking model: {self.model_name}")
        
        # Show progress dialog if parent widget provided
        progress_dialog = None
        if parent_widget:
            progress_dialog = QProgressDialog(progress_message, None, 0, 0, parent_widget)
            progress_dialog.setWindowTitle("Processing")
            progress_dialog.setModal(True)
            progress_dialog.show()
        
        try:
            response = self.model.invoke(messages)
        finally:
            if progress_dialog:
                progress_dialog.close()
        
        self.logger.debug("Model invocation complete")
        return response.content


class DocumentationToolLLM(BaseLLM):
    """
    Create an LLM to generate CWL tool documentation from 
    the provided CWL document.
    """
    cwl_tool: Any = None
    
    def __init__(self, model: Optional[str] = "gemini-2.5-flash", cwl_tool: Any = None, additional_documentation: str = ""):
        """Initialize the DocumentationToolLLM."""
        super().__init__(model)
        self.cwl_tool = cwl_tool
        self.additional_documentation = additional_documentation
        self.system_prompt = self.prepareSystemPrompt()
    
    def prepareSystemPrompt(self) -> str:
        """Prepare the system prompt based on CWL tool class."""
        if self.cwl_tool.class_ == 'CommandLineTool':
            template_name = "systemPrompt-tooldoc.jinja2"
        elif self.cwl_tool.class_ == 'Workflow':
            template_name = "systemPrompt-wflowdoc.jinja2"
        else:
            raise ValueError(f"Unsupported CWL class: {self.cwl_tool.class_}")
        
        return self.loadTemplate(template_name)
    
    def preparePrompt(self, parent_widget=None) -> str:
        """Generate documentation for the CWL tool."""
        user_content = f"""
The cwl workflow is 
```
{json.dumps(save(self.cwl_tool), indent=3)}
```
"""
        
        if self.additional_documentation:
            user_content += f"""
Additional documentation to consider for the Materials and Methods section
```
{json.dumps}
```
"""

        return self.invokeModel(
            user_content,
            parent_widget=parent_widget,
            progress_message="Contacting LLM service to build the documentation..."
        )



class TroubleshootDialog(QDialog):
    """
    Dialog for getting troubleshooting issue description from the user.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Troubleshoot CWL Issue")
        self.initUI()
        
    def initUI(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Add instruction label
        instruction_label = QLabel("Please describe the issue you're experiencing:")
        layout.addWidget(instruction_label)
        
        # Add text edit for issue description
        self.issue_description_input = QTextEdit(self)
        self.issue_description_input.setPlaceholderText("Describe the problem you're having with your CWL document...")
        self.issue_description_input.setMinimumHeight(200)
        layout.addWidget(self.issue_description_input)
        
        # Add OK/Cancel buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setFixedSize(500, 350)
    
    def getIssueDescription(self) -> str:
        """Return the issue description entered by the user."""
        return self.issue_description_input.toPlainText()


class TroubleshootResponseDialog(QDialog):
    """
    Dialog for displaying troubleshooting guidance from the LLM.
    """
    
    def __init__(self, guidance_text: str, issue_description: str = "", file_path: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Troubleshooting Guidance")
        self.guidance_text = guidance_text
        self.issue_description = issue_description
        self.file_path = file_path
        self.initUI()
        
    def initUI(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Add issue description at the top if provided
        if self.issue_description:
            issue_label = QLabel("<b>Your Issue:</b>")
            layout.addWidget(issue_label)
            
            issue_text = QTextEdit(self)
            issue_text.setPlainText(self.issue_description)
            issue_text.setReadOnly(True)
            issue_text.setMaximumHeight(100)
            layout.addWidget(issue_text)
            
            # Add separator
            separator = QLabel("<b>Troubleshooting Guidance:</b>")
            separator.setStyleSheet("margin-top: 10px;")
            layout.addWidget(separator)
        
        # Add a text browser for displaying the guidance
        self.text_browser = QTextBrowser(self)
        self.text_browser.setOpenExternalLinks(True)
        # Render markdown formatting from LLM response
        self.text_browser.setMarkdown(self.guidance_text)
        layout.addWidget(self.text_browser)
        
        # Add OK and Save Response buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        save_button = QPushButton("Save Response")
        save_button.clicked.connect(self.saveResponse)
        button_box.addButton(save_button, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)
        
        self.setMinimumSize(700, 500)
    
    def saveResponse(self):
        """Save the troubleshooting response to a markdown file."""
        # Open save dialog
        fn=Path(self.file_path).stem if self.file_path else ""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Troubleshooting Response",
            f"{fn}_troubleshooting_response.md" if fn else "troubleshooting_response.md",
            "Markdown Files (*.md);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Prepare markdown content
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            content = "# Troubleshooting Report\n\n"
            
            if self.issue_description:
                content += "## Troubleshoot Issue:\n\n"
                content += f"{self.issue_description}\n\n"
            
            content += "## Response\n\n"
            content += f"{self.guidance_text}\n\n"
            
            content += "---\n\n"
            content += f"**Date and Time:** {current_time}\n\n"
            
            if self.file_path:
                content += f"**CWL File Path:** {self.file_path}\n"
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            QMessageBox.information(
                self,
                "Success",
                f"Troubleshooting response saved to:\n{file_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Saving File",
                f"Failed to save file:\n{str(e)}"
            )


class Troubleshoot(BaseLLM):
    """
    Create an LLM to troubleshoot CWL documents based on user-reported issues.
    """
    cwl_tool: Any = None
    issue_description: str = None
    
    def __init__(self, model: Optional[str] = "gemini-2.5-flash", cwl_tool: Any = None, issue_description: str = ""):
        """Initialize the Troubleshoot LLM."""
        super().__init__(model)
        self.cwl_tool = cwl_tool
        self.issue_description = issue_description
        self.system_prompt = self.prepareSystemPrompt()
    
    def prepareSystemPrompt(self) -> str:
        """Prepare the system prompt for troubleshooting."""
        cwltype = self.cwl_tool.class_ if self.cwl_tool else "unknown"

        if cwltype == 'Workflow':
            # pack the workflow with the CWLtoolFactory packworkflow
            # and then load the packed workflow as a string to pass to the LLM
            f=CWLRunner()
            workflow_uri=self.cwl_tool.loadingOptions.fileuri
            workflow_path=uriToPath(workflow_uri)
            with tempfile.NamedTemporaryFile(delete=True, suffix=".cwl") as tmp:
                f.packWorkflow(existing_filename=workflow_path,
                                filename=tmp.name)
                with open(tmp.name, 'r') as packed_file:
                    cwl_yaml = packed_file.read()
        else:
            cwl_yaml = json.dumps(save(self.cwl_tool), indent=3) if self.cwl_tool else ""
        
        return self.loadTemplate(
            "systemPrompt-troubleshoot.jinja2",
            issue_description=self.issue_description,
            cwltype=cwltype,
            cwl=cwl_yaml,
            version=self.cwl_tool.cwlVersion
        )
    
    def preparePrompt(self, parent_widget=None) -> str:
        """Generate troubleshooting suggestions for the CWL issue."""
        # The prompt is already prepared in the system prompt
        # Just need to invoke the model
        user_content = "Please analyze the issue and provide troubleshooting guidance."
        
        return self.invokeModel(
            user_content,
            parent_widget=parent_widget,
            progress_message="Analyzing the issue and generating troubleshooting guidance..."
        )
    
    @staticmethod
    def runTroubleshooting(cwl_tool: Any, parent_widget=None, model: str = "gemini-2.5-flash") -> Optional[Dict[str, str]]:
        """
        Static method to run the full troubleshooting workflow:
        1. Show dialog to get issue description
        2. Create Troubleshoot instance
        3. Generate and return troubleshooting guidance
        
        Args:
            cwl_tool: The CWL tool or workflow to troubleshoot
            parent_widget: Optional parent widget for dialogs
            model: The LLM model to use
            
        Returns:
            dict: Dictionary with 'issue_description' and 'guidance' keys, or None if cancelled
        """
        # Show dialog to get issue description
        dialog = TroubleshootDialog(parent=parent_widget)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            issue_description = dialog.getIssueDescription()
            
            if not issue_description.strip():
                QMessageBox.warning(
                    parent_widget,
                    "No Description",
                    "Please provide a description of the issue."
                )
                return None
            
            # Create Troubleshoot instance and generate guidance
            troubleshoot = Troubleshoot(
                model=model,
                cwl_tool=cwl_tool,
                issue_description=issue_description
            )
            
            guidance = troubleshoot.preparePrompt(parent_widget=parent_widget)
            
            return {
                'issue_description': issue_description,
                'guidance': guidance
            }
        
        return None


class DraftToolLLM(BaseLLM):
    """
    Create an LLM to generate a CWL tool from 
    the provided help text or documentation.
    """
    
    def __init__(self,
                 model: Optional[str] = "gpt-4o-mini",
                 tool_name: str = "unknown",
                 tool_version: str = "latest"):
        """Initialize the DraftToolLLM."""
        super().__init__(model)
        self.system_prompt = self.prepareSystemPrompt(
            tool_name=tool_name,
            tool_version=tool_version
        )
    
    def prepareSystemPrompt(self, 
                            cwl_version: str = "v1.2",
                            tool_name: str = "unknown", 
                            tool_version: str = "latest") -> str:
        """Prepare the system prompt for drafting a CWL tool."""
        return self.loadTemplate(
            "systemPrompt.jinja2",
            cwlVersion=cwl_version,
            argumentFormat=data.configuration.get('sanitize_id'),
            tool_name=tool_name,
            tool_version=tool_version
        )
    
    def preparePrompt(self, help_text: str) -> str:
        """Generate a CWL tool definition from help text."""
        return self.invokeModel(help_text)

# class DocumentationToolLLM:
#     """
#     Create an LLM to generate a CWL tool documentation from 
#     the provided CWL document
#     """
#     model=None # the LLM model to use
#     cwl_tool:Any
#     system_prompt = None  # the system prompt to use for the LLM
#     def __init__(self,
#                  model: Optional[str] =  "gemini-2.5-flash",
#                  cwl_tool: Any = None
#                  ):
#         """Initialize the DocumentToolLLM."""
#         self.logger = logging.getLogger(self.__class__.__name__)
#         self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        
#         self.setModel(model)
#         if cwl_tool:
#             self.cwl_tool=cwl_tool
#         self.system_prompt = self.prepareSystemPrompt( 
#         )  # the system prompt to use for the LLM


#     def setModel(self, model: str):
#         """
#         Set the LLM model to use for generating the CWL tool.

#         Args:
#             model (str): The name of the LLM model to use.
#             e.g. "gpt-4o-mini"
#         """
#         model_provider=None
#         if model in ["gpt-4o-mini", "gpt-4"]:
#             if not os.environ.get("OPENAI_API_KEY"):
#                 load_dotenv()  # Load environment variables from .env file if present
#                 if not os.environ.get("OPENAI_API_KEY"):
#                     print("OpenAI API key not found in environment variables.")
#                     print("You can set it in a .env file or enter it now.")
#                     os.environ["OPENAI_API_KEY"] = getpass.getpass("Enter API key for OpenAI: ")
#             if os.environ.get('OPENAI_API_KEY'):
#                 model_provider="openai"
#         elif model in ["gemini-2.5-flash"]:
#             if not os.environ.get("GOOGLE_API_KEY"):
#                 load_dotenv()
#                 if not os.environ.get("GOOGLE_API_KEY"):
#                     print("Google API key not found in environment variables.")
#                     print("You can set it in a .env file or enter it now.")
#                     os.environ["GOOGLE_API_KEY"] = getpass.getpass("Enter API key for Google: ")
#             if os.environ.get('GOOGLE_API_KEY'): 
#                 model_provider="google_genai"
#         else:
#             QMessageBox.critical(
#                 None,
#                 "Model Error",
#                 f"The specified model '{model}' is not supported.",
#             )
#             raise ValueError(f"The specified model '{model}' is not supported.")
#         if not model_provider:
#             QMessageBox.critical(
#                 None,
#                 "Model Provider Error",
#                 f"Could not find the proper API key in the .env file for {model}'.",
#             )
#             raise ValueError(f"Could not find the proper API key in the .env file for {model}'.")
        

#         self.model = init_chat_model(model, model_provider=model_provider)
                    


#     def prepareSystemPrompt(self):
#         """
#         Prepare the system prompt for the LLM by reading and rendering the Jinja2 template.
        
#         Args:
            
            
#         Returns:
#             str: The rendered system prompt.
#         """
#         try:
#             # Get the config directory path (relative to the current file)
        
#             template_tool_path = data.config_directory / "systemPrompt-tooldoc.jinja2"
#             template_workflow_path = data.config_directory / "systemPrompt-wflowdoc.jinja2"
            
#             # Check if template file exists
#             if not template_tool_path.exists():
#                 self.logger.error(f"Template file not found: {template_tool_path}")
#                 raise FileNotFoundError( "Template file not found.")
            
#             # Set up Jinja2 environment
#             env = jinja2.Environment(
#                 loader=jinja2.FileSystemLoader(data.config_directory),
#                 autoescape=jinja2.select_autoescape(['html', 'xml'])
#             )
            
#             # Load the template
#             if self.cwl_tool.class_ == 'CommandLineTool':
#                 template = env.get_template(template_tool_path.name)
#             if self.cwl_tool.class_ == 'Workflow':
#                 template = env.get_template(template_workflow_path.name)
            
#             # Render the template with provided variables
#             rendered_prompt = template.render(
                
#             )
            
#             self.logger.debug(f"System prompt rendered successfully for tool")
#             self.system_prompt = rendered_prompt
#             return rendered_prompt
            
#         except jinja2.TemplateError as e:
#             self.logger.error(f"Jinja2 template error: {e}")
#             raise Exception( f"Template rendering error: {e}")
#         except Exception as e:
#             self.logger.error(f"Error preparing system prompt: {e}")
#             raise Exception( f"Error preparing system prompt: {e}")
        


#     def preparePrompt(self) -> str:
#         """
#         Prepare the prompt for the LLM based on the provided help text.

#         Args:
#             cwl_tool (str): The cwl document to prepare the documentation.            
#         Returns:
#             str: The generated CWL content from the LLM.
#         """

        
#         messages = [
#             SystemMessage(content=self.system_prompt),
#             HumanMessage(content=json.dumps(save(self.cwl_tool), indent=3)),
#         ]
        
#         self.logger.debug(f"Running with model: {self.model_name}")
        
#         # Show a progress dialog while the model is running
#         progress_dialog = QProgressDialog("Contacting LLM service to build the documentation...", None, 0, 0, self)
#         progress_dialog.setWindowTitle("Processing")
#         progress_dialog.setModal(True)
#         progress_dialog.show()

#         try:
#             # Invoke the model
#             response = self.model.invoke(messages)
#         finally:
#             # Ensure the dialog is closed even if an error occurs
#             progress_dialog.close()

#         self.logger.debug(f"Model finished running")
#         # self.update_response_view()
#         self.logger.debug(f"Response view updated")
        
#         return response.content

