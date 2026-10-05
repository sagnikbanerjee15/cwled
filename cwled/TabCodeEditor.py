from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QFontMetrics, QKeySequence
from io import StringIO
import re
from PyQt6.Qsci import QsciScintilla, QsciLexerJavaScript,QsciLexerYAML
import json
import builtins
import data
import theme
import logging
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
from widgets.qtoogle import QToggle
import jinja2
from typing import Union, Any
from widgets.qButtons import ErrorDialog
from CWLparser import Parser
# Import just the save function from our utility module
from cwl_utils_handler import save,get_cwl_module
from qErrorMessage import QErrorMessage
import traceback

class CodeWindow( QWidget):
    '''
    show a code window with JS highlighting
    '''
    format="YAML" # the default format to present the code
    codeUpdated = pyqtSignal(str) # Signal emitted when code is updated via the Update button, passes a message
    title:str=None
    cwl_tool:Any =None
    cwl_version:str=None
    preferred_fileuri:str=None
    preferred_baseuri:str=None
    
    def __init__(self, 
                 title="Code editor", 
                 cwl_tool:Union[Any,None]=None,  # this is the CWL tool to be displayed
                 parent=None):
        """
        Initialize the CodeWindow widget.
        
        Args:
            title (str): The title of the code editor window
            cwl_dict (dict): Dictionary containing CWL data to display in the editor
            parent: Parent widget if any
        """
        super().__init__(parent)
        # set the logger level 
        self.logger=logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        self.title=title
        self._last_applied_text = ""
        # set the dictionary that holds the CWL code
        self.setCWLTool(cwl_tool)
        
        # Initialize dialog instances as None
        self.find_dialog = None
        self.replace_dialog = None
        self.initUI()

    def initUI(self):
        """
        Initialize the user interface of the code editor.
        
        Sets up the editor appearance, margins, highlighting style,
        and adds UI components like find/replace buttons and format toggle.
        """
        self.editor=QsciScintilla()
        self.editor.setWindowTitle(self.title)
        # Customize the editor appearance
        self.editor.setMarginsFont(theme.monospaceFont(12))
        self.editor.setMarginWidth(0, 50)  # Line numbers margin width
        self.editor.setMarginLineNumbers(0, True)
        # Highlighting style (21 is an arbitrary style number for highlight)
        self.highlight_style = 21
        self.editor.SendScintilla(self.editor.SCI_STYLESETBACK, self.highlight_style, 0xFFFF00)  # Yellow background
        self.editor.SendScintilla(self.editor.SCI_STYLESETFORE, self.highlight_style, 0x000000)  # Black text


        # Set up the editor
        self.editor.setUtf8(True)
        self.editor.setCaretLineVisible(True)
        self.editor.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
            
        # Enable folding
        self.editor.setFolding(QsciScintilla.FoldStyle.BoxedTreeFoldStyle)
        self.editor.setMarginWidth(2, 15)  # Margin 2 is used for folding markers
        self.editor.setMarginType(2, QsciScintilla.MarginType.SymbolMargin)
        self.editor.setMarginSensitivity(2, True)  # Make the margin sensitive to clicks
        theme.styleCodeEditor(self.editor)
        

        # add Find/Replace buttons

        # add a toggle switch to change YAML <-> JSON
        labelPre=QLabel( 'YAML')
        labelPre.setFixedWidth(80)
        labelPost=QLabel('JSON')
        labelPost.setFixedWidth(80)
        self.toggle=QToggle()
        self.find_button=QPushButton("Find")
        self.find_button.setShortcut(QKeySequence.StandardKey.Find)
        self.replace_button=QPushButton("Replace")
        self.replace_button.setShortcut(QKeySequence.StandardKey.Replace)
        self.update_button=QPushButton("Update")
        self.fold_button=QPushButton("Fold Code")
        self.unfold_button=QPushButton("Unfold Code")
        
        # Add navigation dropdown for high-level fields
        self.nav_label = QLabel("Jump to:")
        self.nav_combo = QComboBox()
        self.nav_combo.setMinimumWidth(150)
        self.nav_combo.setMaximumWidth(200)
        self.nav_combo.addItem("-- Select Field --")
        self.nav_combo.currentTextChanged.connect(self.jumpToField)
        
        # Add read-only label for displaying colorized fileuri
        self.fileuri_label = QLabel("File URI:")
        self.fileuri_text = QLabel("<Not set>")
        self.fileuri_text.setMinimumWidth(200)
        self.fileuri_text.setWordWrap(False)
        self.fileuri_text.setTextFormat(Qt.TextFormat.RichText)
        self.fileuri_text.setObjectName('fileUri')     # styled in theme.STYLE_SHEET
        # Set size policy to expand horizontally
        # (Ignored: a long URI must not set the minimum width of the window; the label stretches anyway)
        self.fileuri_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.fileuri_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        layoutToggle=QHBoxLayout()
        layoutToggle.addWidget(labelPre)
        layoutToggle.addWidget(self.toggle)
        layoutToggle.addWidget(labelPost)
        layoutToggle.addWidget(self.update_button)
        
        layoutNavigation=QHBoxLayout()
        layoutNavigation.setContentsMargins(0, 0, 0, 0)
        layoutNavigation.addWidget(self.nav_label)
        layoutNavigation.addWidget(self.nav_combo)
        layoutNavigation.addWidget(self.fileuri_label)
        layoutNavigation.addWidget(self.fileuri_text, 1)  # Stretch factor of 1 to expand
        layoutSearch=QHBoxLayout()
        layoutSearch.addWidget(self.find_button)
        layoutSearch.addWidget(self.replace_button)
        layoutSearch.addWidget(self.fold_button)
        layoutSearch.addWidget(self.unfold_button)
        self.toggle.stateChanged.connect( self.changeTextFormat)
        self.find_button.clicked.connect(self.openFindDialog)
        self.replace_button.clicked.connect(self.openReplaceDialog)
        self.update_button.clicked.connect(self.onTextChanged)
        self.fold_button.clicked.connect(self.foldAllCode)
        self.unfold_button.clicked.connect(self.unfoldAllCode)
        # Create a container widget to hold the horizontal layout
        container_widget = QWidget()
        container_widget.setLayout(layoutToggle)
        container_widget2=QWidget()
        container_widget2.setLayout(layoutSearch)
        container_widget3=QWidget()
        container_widget3.setLayout(layoutNavigation)

        # Create a layout and add the editor to it
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(container_widget, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(container_widget3)  # No alignment to allow stretching
        layout.addWidget(container_widget2, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.editor)
        self.setLayout(layout)

    def convert_multiline_strings(self, obj):
        """
        Recursively convert strings containing newlines to LiteralScalarString for YAML.
        
        Args:
            obj: Dictionary, list, or other object to process
            
        Returns:
            Processed object with multiline strings converted to LiteralScalarString
        """
        if isinstance(obj, dict):
            return {k: self.convert_multiline_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.convert_multiline_strings(item) for item in obj]
        elif isinstance(obj, str) and '\n' in obj:
            # Convert strings with newlines to literal block scalar style (|)
            return LiteralScalarString(obj)
        else:
            return obj

    def setCWLTool( self, cwl_tool:Union[Any,None]=None):
        '''
        set the cwl tool to be edited
        '''
        if cwl_tool:
            self.cwl_tool=cwl_tool
            self.setCWLVersion( self.cwl_tool.cwlVersion)
            self._rememberStableUrisFromTool(cwl_tool)

    def _normalize_uri_value(self, value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode('utf-8')
        if value is None:
            return ""
        return str(value)

    def _isTemporaryUri(self, uri: str) -> bool:
        """Return True when URI/path appears to point to a temporary location."""
        if not uri:
            return False
        try:
            from urllib.parse import urlparse
            from pathlib import Path
            import tempfile

            parsed = urlparse(uri)
            path_str = parsed.path if parsed.scheme else uri
            if not path_str:
                return False

            p = Path(path_str).expanduser()
            try:
                p = p.resolve()
            except Exception:
                pass

            tmp_dir = Path(tempfile.gettempdir())
            try:
                tmp_dir = tmp_dir.resolve()
            except Exception:
                pass

            return str(p).startswith(str(tmp_dir))
        except Exception:
            return False

    def _rememberStableUrisFromTool(self, cwl_tool: Any) -> None:
        """Persist non-temporary file/base URIs so Update can reuse stable context."""
        if not cwl_tool or not hasattr(cwl_tool, 'loadingOptions'):
            return

        fileuri = self._normalize_uri_value(getattr(cwl_tool.loadingOptions, 'fileuri', None))
        baseuri = self._normalize_uri_value(getattr(cwl_tool.loadingOptions, 'baseuri', None))

        if fileuri and not self._isTemporaryUri(fileuri):
            self.preferred_fileuri = fileuri
        if baseuri and not self._isTemporaryUri(baseuri):
            self.preferred_baseuri = baseuri

    def _effectiveUris(self) -> tuple[str, str]:
        fileuri = ""
        baseuri = ""
        if self.cwl_tool and hasattr(self.cwl_tool, 'loadingOptions'):
            fileuri = self._normalize_uri_value(getattr(self.cwl_tool.loadingOptions, 'fileuri', None))
            baseuri = self._normalize_uri_value(getattr(self.cwl_tool.loadingOptions, 'baseuri', None))

        if self.preferred_fileuri:
            fileuri = self.preferred_fileuri
        if self.preferred_baseuri:
            baseuri = self.preferred_baseuri

        return fileuri, baseuri
        
    def setCWLVersion(self, cwl_version:str):
        '''
        set the CWL version for the tool editor
        '''
        if cwl_version:
            if self.cwl_version:
                self.logger.debug(f"Changing version of CWL from {self.cwl_version} to  {cwl_version}") 
            self.cwl_version = cwl_version
        self.logger.debug(f"CWL version for {self.__class__.__name__} is set: {cwl_version}")


    def openFindDialog(self):
        """
        Open dialog for finding text in the editor.
        
        Creates a new FindReplaceDialog instance and displays it.
        """
        if self.find_dialog is None:
            self.find_dialog = FindReplaceDialog(self, is_replace=False)
    
        # Show the dialog and bring it to front
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()

    def openReplaceDialog(self):
        """
        Open dialog for finding and replacing text in the editor.
        
        Creates a new FindReplaceDialog instance with replace mode enabled and displays it.
        """
        if self.replace_dialog is None:
            self.replace_dialog = FindReplaceDialog(self, is_replace=True)
    
        # Show the dialog and bring it to front
        self.replace_dialog.show()
        self.replace_dialog.raise_()
        self.replace_dialog.activateWindow()

    def _markTextAsApplied(self, text: str) -> None:
        """Store the latest editor text known to be applied to the CWL model."""
        self._last_applied_text = text if text is not None else ""

    def hasUnappliedChanges(self) -> bool:
        """Return True when editor text differs from the last applied snapshot."""
        if not hasattr(self, 'editor'):
            return False
        return self.editor.text() != self._last_applied_text

    def applyEditorChanges(self, emit_signal: bool = True) -> bool:
        """Parse and apply editor content to the internal CWL model."""
        self.logger.debug("Text changed in the editor. Updating the CWL dictionary.")
        text = self.editor.text()

        try:
            if self.format == 'JSON':
                updated_cwl_dict = json.loads(text)
            elif self.format == 'YAML':
                yaml = YAML()

                updated_cwl_dict = yaml.load(text)
            else:
                self.logger.error(f"Unknown format: {self.format}")
                return False

            # Ensure main sections exist
            main_sections = ['label', 'id', 'inputs', 'outputs', 'requirements', 'hints']
            if updated_cwl_dict.get('class') == 'CommandLineTool':
                main_sections.extend(['baseCommand', 'arguments'])
            elif updated_cwl_dict.get('class') == 'ExpressionTool':
                main_sections.append('expression')

            for section in main_sections:
                if section not in updated_cwl_dict:
                    if section in ['inputs', 'outputs', 'requirements', 'hints', 'arguments']:
                        updated_cwl_dict[section] = []
                    elif section == 'baseCommand':
                        updated_cwl_dict[section] = []
                    else:
                        updated_cwl_dict[section] = ""

            fileuri, baseuri = self._effectiveUris()

            try:
                p=Parser(updated_cwl_dict,
                        fileuri= fileuri,
                        baseuri= baseuri)  # re parse the existing dictionary to correct formatting etc
                self.cwl_tool= p.getCWL()
                # Keep stable URI context and avoid parser-assigned temp URIs
                if self.cwl_tool and hasattr(self.cwl_tool, 'loadingOptions'):
                    if fileuri:
                        self.cwl_tool.loadingOptions.fileuri = fileuri
                    if baseuri:
                        self.cwl_tool.loadingOptions.baseuri = baseuri
                self._rememberStableUrisFromTool(self.cwl_tool)
                self._markTextAsApplied(text)
                self.logger.debug(f"Successfully updated CWL dictionary from {self.format} format")
                if emit_signal:
                    # Emit the codeUpdated signal with "CWL editor updated" message
                    self.codeUpdated.emit("CWL editor updated")
                return True

            except Exception as e:
                self.logger.error(f"Error parsing updated CWL dictionary: {e}")
                raise
        except Exception as e:
            QErrorMessage.show_and_raise(
                parent=self,
                title="Parsing Error",
                message=f"Failed to parse {self.format} content: {str(e)}",
                exception=e,
                logger=self.logger,
                raise_exception=True
            )

    def onTextChanged( self ):
        """
        Handle text changes in the editor.
        
        Updates the internal CWL dictionary with the new content from the editor.
       Content will be parsed based on the current format (JSON or YAML).
        """
        self.applyEditorChanges(emit_signal=True)

    def foldAllCode(self):
        """
        Fold all foldable sections in the editor.
        If the text format is JSON, skips folding the top level structure.
        """
        # Ensure folding is enabled
        if self.editor.folding() != QsciScintilla.FoldStyle.NoFoldStyle:
            # Get the total number of lines
            line_count = self.editor.lines()
            
            # Skip the top level fold if format is JSON
            start_line = 0
            if self.format == 'JSON':
                # Find the first line that has a top-level fold point
                for line in range(line_count):
                    if self.isFoldable(line):
                        # Skip this top-level fold point but start folding from the next line
                        start_line = line + 1
                        break
            
            # Fold all possible fold points (starting after the top level for JSON)
            for line in range(start_line, line_count):
                # Check if this line can be folded using Scintilla's API
                if self.isFoldable(line):
                    # Only fold lines that aren't already folded
                    if not self.isFolded(line):
                        self.editor.foldLine(line)

    def unfoldAllCode(self):
        """
        Unfold all folded sections in the editor.
        """
        # Ensure folding is enabled
        if self.editor.folding() != QsciScintilla.FoldStyle.NoFoldStyle:
            # Get the total number of lines
            line_count = self.editor.lines()
            
            # Unfold all possible fold points
            for line in range(line_count):
                # Check if this line is foldable (has children)
                if self.isFoldable(line):
                    # The QsciScintilla foldLine method toggles the fold state
                    # We want to make sure it's unfolded, so we check the fold status
                    if self.isFolded(line):
                        self.editor.foldLine(line)
    
    def isFolded(self, line):
        """
        Check if a line is folded.
        Uses internal Scintilla message to check fold status.
        
        Args:
            line (int): The line number to check
            
        Returns:
            bool: True if the line is folded, False otherwise
        """
        # Use SendScintilla to access the internal SCI_GETFOLDEXPANDED message
        # Returns non-zero if expanded, 0 if folded
        return not bool(self.editor.SendScintilla(self.editor.SCI_GETFOLDEXPANDED, line))
    
    def isFoldable(self, line):
        """
        Check if a line is foldable.
        Uses internal Scintilla message to check fold level.
        
        Args:
            line (int): The line number to check
            
        Returns:
            bool: True if the line is foldable, False otherwise
        """
        # Use SendScintilla to access the internal SCI_GETFOLDLEVEL message
        # The bits 15-11 of the fold level contain the fold level flags
        fold_level = self.editor.SendScintilla(self.editor.SCI_GETFOLDLEVEL, line)
        # Check if the line has the header flag set (can be folded)
        return bool(fold_level & self.editor.SC_FOLDLEVELHEADERFLAG)
        

    def populateFromCWL(self):
        """
        Populate the editor with content from the CWL dictionary.
        
        Logs the received CWL and calls setText() to display the content.

        """
        try:
            cwl_text=save( self.cwl_tool )
        except Exception as e:
            self.logger.error(f"Error generating the CWL tool: {e}")
            ErrorDialog(error_message="Unable to load CWL",
                        details=f"{e}\n{traceback.print_exc()}"
            )
            
        self.logger.debug(f"Received new CWL {json.dumps(cwl_text)}")
        # Get font settings from configuration, with sensible defaults
        editor_font_family = data.configuration.get('code_editor', {}).get('font_family', 'monospace')
        editor_font_size = data.configuration.get('code_editor', {}).get('font_size', 12)
        editor_font = QFont(editor_font_family, editor_font_size)
        # cwl_text is a dict. Let's order it by its keys so
        # we can visually know where to look for each element
        custom_order = ['cwlVersion', 'class','id','label','doc',
                        'baseCommand','arguments','inputs', 'outputs', 'steps',
                        'requirements','hints']
        sorted_dict = dict(sorted(
            cwl_text.items(),
            key=lambda item: custom_order.index(item[0]) if item[0] in custom_order else float('inf')
        ))
        
        # Sort fields within inputs, outputs, steps, and arguments
        field_order = ['id', 'label', 'doc', 'type', 'in', 'out']
        for key in ['inputs', 'outputs', 'steps', 'arguments']:
            if key in sorted_dict and isinstance(sorted_dict[key], list):
                sorted_items = []
                for item in sorted_dict[key]:
                    if isinstance(item, dict):
                        # Sort the fields within each item
                        sorted_item = dict(sorted(
                            item.items(),
                            key=lambda x: field_order.index(x[0]) if x[0] in field_order else float('inf')
                        ))
                        sorted_items.append(sorted_item)
                    else:
                        sorted_items.append(item)
                sorted_dict[key] = sorted_items
        
        cwl_text=sorted_dict

        self.logger.debug("Setting text projection")
        if cwl_text:
            self.logger.debug(f"for toggle we got {self.format}")
            if self.format == 'YAML':
                # Convert strings with newlines to literal block scalars
                cwl_text = self.convert_multiline_strings(cwl_text)
                
                # Create a YAML instance
                yaml = YAML()
                yaml.preserve_quotes = False 
                yaml.default_flow_style = False  # Use block style, not flow style
                yaml.default_style = None  # Use plain style (no quotes) when possible
                yaml.width = 4096
                # Use a StringIO object to capture the YAML output as a string
                yaml_string = StringIO()
                yaml.dump(cwl_text, yaml_string)
                # Get the YAML string from the StringIO object
                text = yaml_string.getvalue()

                lexer = QsciLexerYAML()
                # editor_font = QFont("Courier", 12)  # Choose your desired font size
                for style in range(0, 32):  # Set font for all possible style numbers
                    lexer.setFont(editor_font, style)
                # lexer.setDefaultFont(QFont("Courier", 16))
                self.editor.setLexer(lexer)
                theme.styleCodeEditor(self.editor, lexer)
            if self.format == 'JSON':
                lexer = QsciLexerJavaScript()
                # lexer.setDefaultFont(QFont("Courier", 16))
                # editor_font = QFont("Courier", 12)  # Choose your desired font size
                for style in range(0, 32):  # Set font for all possible style numbers
                    lexer.setFont(editor_font, style)
                self.editor.setLexer(lexer)
                theme.styleCodeEditor(self.editor, lexer)
                text= json.dumps(cwl_text, indent=3)
            self.logger.debug(f"Sending {text} to the editor")
            # Save scroll and cursor position before replacing text
            first_visible = self.editor.SendScintilla(self.editor.SCI_GETFIRSTVISIBLELINE)
            cursor_line, cursor_index = self.editor.getCursorPosition()
            self.editor.setText( text )
            # Restore cursor and scroll position
            max_line = self.editor.lines() - 1
            cursor_line = min(cursor_line, max_line)
            self.editor.setCursorPosition(cursor_line, cursor_index)
            self.editor.SendScintilla(self.editor.SCI_SETFIRSTVISIBLELINE, first_visible)
            # Update navigation dropdown with available fields
            self.updateNavigationDropdown(cwl_text)
            self._markTextAsApplied(self.editor.text())
            # elif self.cwl_dict.get('class'):
            #     QMessageBox.critical(self, "Format Error", 
            #         f"No parser available for {self.cwl_dict.get('class')} in the Code editor")


    def changeTextFormat(self):
        """
        Toggle between YAML and JSON text formats.
        
        Called when the format toggle switch is used, updates the format setting
        and refreshes the text display.
        """
        if self.toggle.isChecked():
            self.format="JSON"
        else:
            self.format="YAML"
        self.populateFromCWL()

    def getCWL(self) -> Union[Any,None]:
        """
        Get the current text from the editor.
        
        Returns:
            CWL: The current text content of the editor as a CWLobj
        """

        return self.cwl_tool

    def captureViewState(self) -> dict:
        """Capture editor cursor and viewport state for tab restoration."""
        if not hasattr(self, 'editor'):
            return {}
        return {
            'first_visible': self.editor.SendScintilla(self.editor.SCI_GETFIRSTVISIBLELINE),
            'cursor': self.editor.getCursorPosition(),
        }

    def restoreViewState(self, state: dict) -> None:
        """Restore editor cursor and viewport state after content refresh."""
        if not hasattr(self, 'editor') or not state:
            return

        first_visible = int(state.get('first_visible', 0))
        line, index = state.get('cursor', (0, 0))

        max_line = max(0, self.editor.lines() - 1)
        line = max(0, min(int(line), max_line))
        line_length = max(0, self.editor.lineLength(line) - 1) if self.editor.lines() > 0 else 0
        index = max(0, min(int(index), line_length))

        self.editor.setCursorPosition(line, index)
        self.editor.SendScintilla(self.editor.SCI_SETFIRSTVISIBLELINE, max(0, first_visible))
    
    def updateNavigationDropdown(self, cwl_dict):
        """
        Update the navigation dropdown with available high-level fields from the CWL dictionary.
        
        Args:
            cwl_dict (dict): The CWL dictionary to extract field names from
        """
        # Block signals to avoid triggering jumpToField during update
        self.nav_combo.blockSignals(True)
        self.nav_combo.clear()
        self.nav_combo.addItem("-- Select Field --")
        
        # Define the order of important fields to show
        important_fields = ['cwlVersion', 'class', 'id', 'label', 'doc', 
                          'baseCommand', 'arguments', 'inputs', 'outputs', 
                          'steps', 'requirements', 'hints', 'expression']
        
        # Add fields that exist in the CWL dictionary
        for field in important_fields:
            if field in cwl_dict:
                self.nav_combo.addItem(field)
        
        # Add any other fields not in the important_fields list
        for field in cwl_dict.keys():
            if field not in important_fields and field not in ['cwlVersion']:
                self.nav_combo.addItem(field)
        
        self.nav_combo.blockSignals(False)
        
        # Update the fileuri text box
        self.updateFileuriDisplay()
    
    def onThemeChanged(self):
        self.updateFileuriDisplay()

    def updateFileuriDisplay(self):
        """
        Update the fileuri display with colorized parts: scheme (orange), directory (blue), filename (red).
        Displays "<Not set>" if there is no value.
        """
        if self.cwl_tool and hasattr(self.cwl_tool, 'loadingOptions'):
            fileuri, _ = self._effectiveUris()
            if fileuri:
                # Parse the URI into scheme, directory, and filename
                colored_text = self._colorizeFileUri(fileuri)
                self.fileuri_text.setText(colored_text)
            else:
                self.fileuri_text.setText("<Not set>")
        else:
            self.fileuri_text.setText("<Not set>")
    
    def _colorizeFileUri(self, uri):
        """
        Split the file URI and colorize its parts:
        - Scheme (e.g., 'file://') in orange
        - Directory path in blue
        - Filename with extension in red
        
        Args:
            uri (str): The file URI to colorize
            
        Returns:
            str: HTML formatted string with colored parts
        """
        from pathlib import Path
        import os
        
        # Check if URI has a scheme
        if '://' in uri:
            scheme, path = uri.split('://', 1)
            scheme_part = f'<span style="color: {theme.ORANGE};">{scheme}://</span>'  # Orange
        else:
            scheme_part = ''
            path = uri
        
        # Split path into directory and filename
        if path:
            path_obj = Path(path)
            filename = path_obj.name
            directory = str(path_obj.parent)
            
            if directory and directory != '.':
                # Add trailing slash for clarity
                if not directory.endswith(os.sep):
                    directory += os.sep
                dir_part = f'<span style="color: {theme.SKY};">{directory}</span>'  # Blue
            else:
                dir_part = ''
            
            if filename:
                file_part = f'<span style="color: {theme.RED};">{filename}</span>'  # Red
            else:
                file_part = ''
            
            return scheme_part + dir_part + file_part
        
        return uri
    
    def showStep(self, step_id: str) -> bool:
        """
        Select the definition of a workflow step in the editor: the line of the
        step in the ``steps`` section (``echo:`` or ``- id: echo`` in YAML,
        ``"echo":`` or ``"id": "echo"`` in JSON).

        Returns:
            True if the step was found.
        """
        lines = self.editor.text().splitlines()
        name = re.escape(str(step_id))
        if self.format == 'JSON':
            section, patterns = r'^\s*"steps"\s*:', [rf'^\s*"{name}"\s*:', rf'^\s*"id"\s*:\s*"(?:[^"]*[#/])?{name}"']
        else:
            section = r'^steps\s*:'
            patterns = [rf'^\s+[\'"]?{name}[\'"]?\s*:\s*(#.*)?$',
                        rf'^\s*-\s*id\s*:\s*[\'"]?(?:[^\'"\s]*[#/])?{name}[\'"]?\s*(#.*)?$']
        start = next((number for number, text in enumerate(lines) if re.match(section, text)), None)
        if start is None:
            return False
        for number in range(start + 1, len(lines)):
            text = lines[number]
            if self.format != 'JSON' and text.strip() and not text[0].isspace() and not text.startswith('-'):
                break       # the next top level key: the steps are over
            if any(re.match(pattern, text) for pattern in patterns):
                self.editor.ensureLineVisible(number)
                self.editor.setCursorPosition(number, 0)
                self.editor.setSelection(number, 0, number, len(text))
                self.editor.setFocus()
                return True
        return False

    def jumpToField(self, field_name):
        """
        Jump to the specified field in the editor by searching for it and positioning the cursor.
        
        Args:
            field_name (str): The name of the field to jump to
        """
        if field_name == "-- Select Field --" or not field_name:
            return
        
        # Reset selection to start of document
        self.nav_combo.blockSignals(True)
        self.nav_combo.setCurrentIndex(0)
        self.nav_combo.blockSignals(False)
        
        # Search for the field based on current format
        if self.format == 'JSON':
            # In JSON, search for "fieldname":
            search_text = f'"{field_name}":'
        else:  # YAML
            # In YAML, search for fieldname: at the start of a line
            search_text = f'{field_name}:'
        
        # Find the text in the editor
        found = self.editor.findFirst(
            search_text,
            False,  # re (regular expression)
            True,   # cs (case sensitive)
            False,  # wo (whole word)
            False,  # wrap
            True    # forward
        )
        
        if found:
            # Get the current line
            line, index = self.editor.getCursorPosition()
            
            # Ensure the line is visible (unfold if needed)
            self.editor.ensureLineVisible(line)
            
            # Set cursor to the beginning of the line
            self.editor.setCursorPosition(line, 0)
            
            # Select the entire line for visual feedback
            line_length = self.editor.lineLength(line)
            self.editor.setSelection(line, 0, line, line_length - 1)
            
            self.logger.debug(f"Jumped to field '{field_name}' at line {line}")
    


class FindReplaceDialog(QDialog):
    def __init__(self, parent=None, is_replace=False):
        """
        Initialize the Find/Replace dialog.
        
        Args:
            parent: Parent widget, typically the CodeWindow
            is_replace (bool): If True, show replace functionality; if False, find only
        """
        super().__init__(parent)
        
        self.is_replace = is_replace
        self.setWindowTitle("Replace" if is_replace else "Find")
        
        # Make the dialog modeless (non-blocking)
        self.setModal(False)
        
        # Keep the dialog on top but allow interaction with parent
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        
        # Initialize UI
        self.initUI()
        
        # Connect to parent's destroyed signal to clean up
        if parent:
            parent.destroyed.connect(self.close)
    
    def initUI(self):
        """Initialize the dialog UI components."""
        # Find section
        self.find_label = QLabel("Find:")
        self.find_text = QLineEdit()
        self.find_button = QPushButton("Find Next")
        # Use QKeySequence.StandardKey.Find for platform-specific Find shortcut
        self.find_button.setShortcut(QKeySequence.StandardKey.FindNext)
        
        # Options
        self.case_sensitive_cb = QCheckBox("Match case")
        self.whole_words_cb = QCheckBox("Whole words")
        
        # Replace section (only if is_replace is True)
        if self.is_replace:
            self.replace_label = QLabel("Replace:")
            self.replace_text = QLineEdit()
            self.replace_button = QPushButton("Replace")
            # Use QKeySequence.StandardKey.Replace for platform-specific Replace shortcut
            self.replace_button.setShortcut(QKeySequence.StandardKey.Replace)
            self.replace_all_button = QPushButton("Replace All")
        
        # Control buttons
        self.close_button = QPushButton("Close")
        
        # Layout
        layout = QVBoxLayout()
        
        # Find section
        find_group = QGroupBox("Find")
        find_layout = QVBoxLayout()
        find_layout.addWidget(self.find_label)
        find_layout.addWidget(self.find_text)
        
        # Find buttons layout
        find_buttons_layout = QHBoxLayout()
        find_buttons_layout.addWidget(self.find_button)
        find_layout.addLayout(find_buttons_layout)
        
        # Options
        options_layout = QHBoxLayout()
        options_layout.addWidget(self.case_sensitive_cb)
        options_layout.addWidget(self.whole_words_cb)
        find_layout.addLayout(options_layout)
        
        find_group.setLayout(find_layout)
        layout.addWidget(find_group)
        
        # Replace section (conditional)
        if self.is_replace:
            replace_group = QGroupBox("Replace")
            replace_layout = QVBoxLayout()
            replace_layout.addWidget(self.replace_label)
            replace_layout.addWidget(self.replace_text)
            
            replace_buttons_layout = QHBoxLayout()
            replace_buttons_layout.addWidget(self.replace_button)
            replace_buttons_layout.addWidget(self.replace_all_button)
            replace_layout.addLayout(replace_buttons_layout)
            
            replace_group.setLayout(replace_layout)
            layout.addWidget(replace_group)
        
        # Close button
        layout.addWidget(self.close_button)
        
        self.setLayout(layout)
        
        # Connect signals
        self.find_button.clicked.connect(self.find_next)
        
        if self.is_replace:
            self.replace_button.clicked.connect(self.replace_current)
            self.replace_all_button.clicked.connect(self.replace_all)
        
        self.close_button.clicked.connect(self.close)
        
        # Enable Enter key to trigger find
        self.find_text.returnPressed.connect(self.find_next)
        if self.is_replace:
            self.replace_text.returnPressed.connect(self.replace_current)
    
    def find_next(self):
        """Find the next occurrence of the search text."""
        editor = self.parent().editor
        search_text = self.find_text.text()
        
        if not search_text:
            return
        
        # Get search options
        case_sensitive = self.case_sensitive_cb.isChecked()
        whole_words = self.whole_words_cb.isChecked()
        
        # Perform the search
        found = editor.findFirst(
            search_text,
            False,  # regex
            case_sensitive,
            whole_words,
            True,   # wrap
            True,   # forward
            -1, -1, # start from current position
            True    # show if found
        )
        
        if found:
            editor.ensureCursorVisible()
            # Optionally, you can add a status message
            self.setWindowTitle(f"{'Replace' if self.is_replace else 'Find'} - Found")
        else:
            self.setWindowTitle(f"{'Replace' if self.is_replace else 'Find'} - Not Found")
    

    
    def replace_current(self):
        """Replace the currently selected text if it matches the search text."""
        if not self.is_replace:
            return
            
        editor = self.parent().editor
        search_text = self.find_text.text()
        replace_text = self.replace_text.text()
        
        if not search_text:
            return
        
        # Check if current selection matches search text
        if editor.hasSelectedText():
            selected_text = editor.selectedText()
            case_sensitive = self.case_sensitive_cb.isChecked()
            
            if (case_sensitive and selected_text == search_text) or \
               (not case_sensitive and selected_text.lower() == search_text.lower()):
                # Replace the selected text
                editor.replaceSelectedText(replace_text)
                # Find next occurrence
                self.find_next()
                return
        
        # If no matching selection, just find the next occurrence
        self.find_next()
    
    def replace_all(self):
        """Replace all occurrences of the search text."""
        if not self.is_replace:
            return
            
        editor = self.parent().editor
        search_text = self.find_text.text()
        replace_text = self.replace_text.text()
        
        if not search_text:
            return
        
        # Get search options
        case_sensitive = self.case_sensitive_cb.isChecked()
        whole_words = self.whole_words_cb.isChecked()
        
        # Count replacements
        replacement_count = 0
        
        # Start from the beginning
        editor.setCursorPosition(0, 0)
        
        # Find and replace all occurrences
        while True:
            found = editor.findFirst(
                search_text,
                False,  # regex
                case_sensitive,
                whole_words,
                False,  # don't wrap for replace all
                True,   # forward
                -1, -1, # start from current position
                False   # don't show each find
            )
            
            if found:
                editor.replaceSelectedText(replace_text)
                replacement_count += 1
            else:
                break
        
        # Update title with replacement count
        self.setWindowTitle(f"Replace - {replacement_count} replacements made")
    
    def closeEvent(self, event):
        """Handle dialog close event."""
        # Clean up reference in parent
        if self.parent():
            if self.is_replace and hasattr(self.parent(), 'replace_dialog'):
                self.parent().replace_dialog = None
            elif not self.is_replace and hasattr(self.parent(), 'find_dialog'):
                self.parent().find_dialog = None
        
        event.accept()