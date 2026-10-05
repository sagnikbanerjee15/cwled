from PyQt6.QtCore import *
from PyQt6.QtWidgets import *

import copy
import json
from configuration import Configuration
import builtins
import logging
from sanitizeName import sanitize
from widgets.qButtons import *
from JavascriptEditor import JavaScriptEditorDialog
import theme
from widgets.qSecondaryFiles import  QSecondaryFilesGroupWidget
from Tags import QTagWidget
import sys 
from copy import deepcopy
import logging
import data
from dataTypes import output
import jinja2
from pathlib import Path
from typing import Tuple, Any
from cwl_utils_handler import CWLTypeOutput, get_cwl_module
from widgets.qLabelLineEditWidget import QLabelLineEditWidget
from widgets.qSchema import QSchemaList
import re
import uuid
from cwl_utils.parser import save
from cwl_utils_handler import get_cwl_module, get_cwl_version
from CWLparser import get_type, Parser, is_optional, is_optional_array, is_array
from BaseDialog import BaseDialog
logger = logging.getLogger(__name__)

def _workingCopy(parameter):
    """A shallow copy of a parameter with its own type list, for the dialog
    to read (and trim) without changing the parameter of the tool."""
    duplicate = copy.copy(parameter)
    if isinstance(getattr(parameter, 'type_', None), list):
        duplicate.type_ = list(parameter.type_)
    return duplicate


class OutputDialog(BaseDialog):
    code=''
    codeUpdated = pyqtSignal() # emit this signal when the code is updated
    output_parameter=None
    output_parameter_type=None
    cwl_version=None
    def __init__(self, 
                 output_parameter:Any=None, 
                 output_parameter_type:str=None,
                 cwl_version:str=None,
                 parent=None):
        super().__init__(parent)
        self.logger=logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        
        if output_parameter is not None and cwl_version is None:
            self.setCWLVersion(output_parameter)
        elif cwl_version is not None:
            self.setCWLVersion(cwl_version)
        else:
            raise ValueError("Either output_parameter or cwl_version must be provided.")
        # Set the dialog title
        self.setWindowTitle(f"Outputs (cwl:{self.cwl_version})")
        self.initUI()
        if output_parameter is not None:
            # a working copy: loading must not change the tool (it strips 'null'...)
            self.output_parameter=_workingCopy(output_parameter)
            self.setDefaults()
        elif output_parameter_type is not None:
            logger.debug(f"Setting the object to {output_parameter_type} from the arguments")
            self.output_parameter_type = output_parameter_type  # Default to an empty CommandInputParameter
            self._offerStreamTypes()
            self.onDataTypeChanged()
        else:
            raise ValueError("Either output_parameter or output_parameter_type must be provided.")


    def initUI(self):

        # Main layout for the dialog
        self.layout = QVBoxLayout(self)

        # ID input
        self.id_label = QLabel("ID:")
        self.id_input = QLineEdit(self)
        self.id_input.setPlaceholderText("Enter ID")
        self.id_input.textChanged.connect(lambda:self.sanitizeID(self.id_input.text()))
        
        # Field name input
        self.field_name_label = QLabel("Field Name:")
        self.field_name_input = QLineEdit(self)
        self.field_name_input.setPlaceholderText("Enter Field Name")
        self.field_name_input.setText(f"name{ str(uuid.uuid4())[:4]}")
        self.field_name_input.textChanged.connect(lambda:self.sanitizeID(self.field_name_input.text()))
        # Initially hide the field name input (will be shown when enum type is selected)
        self.field_name_label.setVisible(False)
        self.field_name_input.setVisible(False)       
        # Required checkbox
        self.required_checkbox = QCheckBox("Required")

        # Data type ComboBox
        self.data_type_label = QLabel("Data Type:")
        self.data_type_combobox = QComboBox(self)
        # for outputs we should enable the type 'stdout'
        self.data_type_combobox.addItems(data.configuration.get('CWL_types'))
        self.data_type_combobox.currentTextChanged.connect(self.onDataTypeChanged)
        
        # pickValue combo box
        self.pick_value_label = QLabel("Pick value:")
        self.pick_value_combobox = QComboBox(self)
        self.pick_value_combobox.addItems(
            ['-- None --',
             'first_non_null',
             'the_only_non_null',
             'all_non_null']
        )
        
        # linkMerge combo box
        self.link_merge_label = QLabel("Link Merge:")
        self.link_merge_combobox = QComboBox(self)
        self.link_merge_combobox.addItems(
            ['-- None --',
             'merge_nested',
             'merge_flattened']
        )


        # Array Handling options (tri-state radio buttons)
        self.array_handling_layout=QHBoxLayout()
        self.array_combobox = QComboBox(self)
        self.array_combobox.addItems(
            ['Single Item',
             'Allow Array',
             'Array Only']
        )
        self.array_handling_layout.addWidget(self.array_combobox)
        
        # Value input
        
        self.glob_label = QLabel("Glob:")
        self.glob_input = QLineEdit(self)
        self.glob_input.setPlaceholderText("Enter Value")
        self.glob_code_button=QCodeButton()
        self.glob_code_button.clicked.connect( lambda:self.onCodeEditor(self.glob_input))
        self.glob_code_button.setVisible( not self.output_parameter_type == "WorkflowOutputParameter")
        self.glob_input.setVisible( not self.output_parameter_type == "WorkflowOutputParameter")
        self.glob_label.setVisible( not self.output_parameter_type == "WorkflowOutputParameter")
        # the </> buttons are attached to their fields (Composer input group)
        layout_glob=QHBoxLayout()
        layout_glob.addWidget(theme.InputGroup(self.glob_input, self.glob_code_button, parent=self))

        # Label input
        self.label_label = QLabel("Label:")
        self.label_input = QLineEdit(self)

        # Description input
        self.description_label = QLabel("Description:")
        self.description_input = QTextEdit(self)
        
        # Add Record Field checkbox
        self.record_field_checkbox = QCheckBox("Record Field")
        self.record_field_checkbox.stateChanged.connect(self.onRecordFieldChanged)
        
        # Record ID for record fields
        self.record_id = QLabelLineEditWidget(label_text="Record id", 
                                              placeholder_text="ID for this record to match fields", 
                                              parent=self)
        self.record_id.setVisible(False)  # Hide by default
        
        # Create record handling layout to hold the checkbox and record ID widget
        self.record_handling_layout = QHBoxLayout()
        self.record_handling_layout.addWidget(self.record_field_checkbox)
        self.record_handling_layout.addWidget(self.record_id)
        
        # Dynamic widgets that appear based on the data type
        self.enum_table_widget = None
        self.load_content_checkbox = None
        self.load_listing_combobox = None
        self.streamable_checkbox = None
        self.secondary_files_input = None
        self.output_eval_label=None
        self.output_eval= None
        self.output_eval_code= None
        self.file_type_list_widget = None
        self.file_type_table = None

        # Add widgets to the layout
        self.layout.addWidget(self.required_checkbox)
        self.layout.addWidget(self.id_label)
        self.layout.addWidget(self.id_input)
        
        # Add field_name widgets to layout
        self.layout.addWidget(self.field_name_label)
        self.layout.addWidget(self.field_name_input)
        # Add pick value if we have output of a workflow
        # Pick value
        self.layout.addWidget(self.pick_value_label)
        self.layout.addWidget(self.pick_value_combobox)
        self.pick_value_label.setVisible(self.output_parameter_type == 'WorkflowOutputParameter')   
        self.pick_value_combobox.setVisible(self.output_parameter_type == 'WorkflowOutputParameter')
        
        # Add link merge if we have output of a workflow
        self.layout.addWidget(self.link_merge_label)
        self.layout.addWidget(self.link_merge_combobox)
        self.link_merge_label.setVisible(self.output_parameter_type == 'WorkflowOutputParameter')   
        self.link_merge_combobox.setVisible(self.output_parameter_type == 'WorkflowOutputParameter')


        # Add Glob input - always visible
        self.layout.addWidget(self.glob_label)
        self.layout.addLayout(layout_glob)

        # Add Output Eval - always visible
        layout_output_eval = QHBoxLayout()
        self.output_eval_label = QLabel("OutputEval:")
        self.output_eval = QLineEdit(self)
        self.output_eval_code = QCodeButton(parent=self)
        self.output_eval_code.clicked.connect(lambda: self.onCodeEditor(self.output_eval))
        self.output_eval_label.setVisible(not self.output_parameter_type == 'WorkflowOutputParameter')
        self.output_eval.setVisible(not self.output_parameter_type == 'WorkflowOutputParameter')
        self.output_eval_code.setVisible(not self.output_parameter_type == 'WorkflowOutputParameter')

        layout_output_eval.addWidget(theme.InputGroup(self.output_eval, self.output_eval_code, parent=self))
        self.layout.addWidget(self.output_eval_label)
        self.layout.addLayout(layout_output_eval)

        # Add Label and Description
        self.layout.addWidget(self.label_label)
        self.layout.addWidget(self.label_input)
        self.layout.addWidget(self.description_label)
        self.layout.addWidget(self.description_input)
        # Add Data Type ComboBox
        self.layout.addWidget(self.data_type_label)
        self.layout.addWidget(self.data_type_combobox)
        # Add Array handling options
        self.layout.addLayout(self.array_handling_layout)
        # Add Record handling options
        self.layout.addLayout(self.record_handling_layout)
        # Dynamic area where new widgets will be added based on Data Type
        self.dynamic_area_layout = QVBoxLayout()
        self.layout.addLayout(self.dynamic_area_layout)



        # Dynamic area for file-related widgets (File Type and Table)
        self.file_related_layout = QVBoxLayout()
        self.layout.addLayout(self.file_related_layout)

        # Add OK/Cancel buttons
        self.button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.button_layout.addWidget(self.ok_button)
        self.button_layout.addWidget(self.cancel_button)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self.layout.addLayout(self.button_layout)

        # Initially hide prefix, value, separate prefix/value, and item separator widgets
        self.toggleLoadContentsOptions()

    def setCWLVersion(self, cwl_version: str):
        if not isinstance(cwl_version, str):
            self.cwl_version = get_cwl_version(cwl_version)
        else:
            self.cwl_version = cwl_version

    def sanitizeID(self,text):
        '''
        make sure the text in the ID field is sanitized
        dependig on the options in the configuration
        '''
        if data.configuration.get('sanitize_id') == 'underscore':
            new_text = sanitize(text).underscore().text
        elif data.configuration.get('sanitize_id') == 'camelCase':
            new_text = sanitize(text).camelCase().text
        elif data.configuration.get('sanitize_id') == 'UpperCamelCase':
            new_text = sanitize(text).UpperCamelCase().text
        elif data.configuration.get('sanitize_id') == 'lowerCamelCase':
            new_text = sanitize(text).lowerCamelCase().text
        elif data.configuration.get('sanitize_id') == 'dash':
            new_text = sanitize(text).dash().text
        elif data.configuration.get('sanitize_id') == 'keepAlphaNum':
            new_text = sanitize(text).keepAlphaNum().text
        else:
            new_text = text
        self.id_input.setText(new_text)
        self.id_input.setCursorPosition(len( new_text ))    


    def onDataTypeChanged(self):
        """
        Update the dialog UI when the data type changes.
        """
        data_type = self.data_type_combobox.currentText()
        self.logger.debug(f"Updating the ui for the type {data_type}")
        
        # Clear any previously added dynamic widgets
        for i in reversed(range(self.dynamic_area_layout.count())):
            widget_to_remove = self.dynamic_area_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)

        # Clear file-related layout
        for i in reversed(range(self.file_related_layout.count())):
            widget_to_remove = self.file_related_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)
                
        # Make sure outputEval is always enabled regardless of data type
        self.output_eval.setEnabled(True)
        self.output_eval_code.setEnabled(True)
        self.output_eval_label.setStyleSheet("")
        self.output_eval.setStyleSheet("")

        # add WorkflowOutputParameter-specific UI elements
        self.pick_value_combobox.setVisible(self.output_parameter_type == 'WorkflowOutputParameter')
        self.pick_value_label.setVisible(self.output_parameter_type == 'WorkflowOutputParameter')

        # Check for record dependent arguments or record mutually exclusive arguments data type
        is_special_record_type = data_type in ["record dependent arguments", "record mutually exclusive arguments"]
        
        # For record dependent or mutually exclusive arguments:
        # 1. Uncheck "Include in command line" checkbox
        # 2. Show record ID field
        if is_special_record_type:
            self.command_line_checkbox.setChecked(False)
            prefix = "dep-rec-0" if data_type == "record dependent arguments" else "mut-rec-0"
            self.record_id.setText(prefix)
            self.record_id.setVisible(True)
        else:
            # For non-record types, only show record name if checkbox is manually checked
            self.record_id.setVisible(self.record_field_checkbox.isChecked())
            
 

        # Add widgets based on the selected data type
        if data_type == "enum":
            # self.enum_table_widget = self.create_enum_table_widget()
            self.enum_table_label=QLabel("Enum Values:")
            self.enum_table_widget = QTagWidget(parent=self)
            layout=QVBoxLayout()
            layout.addWidget(self.enum_table_label)
            layout.addWidget(self.enum_table_widget)
            self.dynamic_area_layout.addLayout(layout)
        
        if data_type != "enum":
            if self.enum_table_widget:
                self.enum_table_widget.setParent(None)
                self.enum_table_widget = None



        if data_type=='Directory':
            self.load_listing_combobox = QComboBox(self)
            self.load_listing_combobox.addItems(["no_listing", "shallow_listing", "deep_listing"])
            self.load_listing_combobox.currentTextChanged.connect(self.toggleLoadContentsOptions)
            self.dynamic_area_layout.addWidget(self.load_listing_combobox)
        if data_type != "Directory":
            if self.load_listing_combobox:
                self.load_listing_combobox.setParent(None)
                self.load_listing_combobox = None
            

        if data_type == "File":
            self.load_content_checkbox = QCheckBox("Load Content")
            self.load_content_checkbox.stateChanged.connect(self.toggleLoadContentsOptions)
            self.streamable_checkbox = QCheckBox("Is streamable")
            self.secondary_files_input = QSecondaryFilesGroupWidget(parent=self)

            # self.secondary_files_input.setPlaceholderText("Secondary Files")
            self.dynamic_area_layout.addWidget(self.load_content_checkbox)
            self.dynamic_area_layout.addWidget(self.streamable_checkbox)    
            self.dynamic_area_layout.addWidget(self.secondary_files_input)

            # Add File format ListWidget for selecting multiple file types with search
            # self.file_type_list_widget = QTagWidget(max_tags=1,parent=self)
            self.file_type_list_widget = QSchemaList(self)
            self.dynamic_area_layout.addWidget(QLabel("File Format:"))
            self.dynamic_area_layout.addWidget(self.file_type_list_widget)


        if data_type != "File":
            if self.load_content_checkbox:
                self.load_content_checkbox.setParent(None)
                self.load_content_checkbox = None
        
            if self.streamable_checkbox:
                self.streamable_checkbox.setParent(None)
                self.streamable_checkbox = None
            if self.secondary_files_input:
                self.secondary_files_input.setParent(None)
                self.secondary_files_input = None
            if self.file_type_list_widget:
                self.file_type_list_widget.setParent(None)
                self.file_type_list_widget = None
            if self.file_type_table:
                self.file_type_table.setParent(None)
                self.file_type_table = None
        
        # show the name field if it is a record
        self.field_name_label.setVisible(data_type=='enum' or self.output_parameter_type == 'CommandOutputRecordField')
        self.field_name_input.setVisible(data_type=='enum' or self.output_parameter_type == 'CommandOutputRecordField')


    def toggleLoadContentsOptions(self):
        """
        Update the state of load-content related features.
        Note: OutputEval is now always enabled regardless of loadContents.
        """
        # OutputEval is now always active, no need to modify its state here
        # This method is kept for compatibility with existing connections
        # Ensure output_eval is always enabled
        self.output_eval.setEnabled(True)
        self.output_eval_code.setEnabled(True)
        self.output_eval_label.setStyleSheet("")
        self.output_eval.setStyleSheet("")
        pass


    def _offerStreamTypes(self):
        """A tool output can also capture the standard output / error."""
        if getattr(self, 'output_parameter_type', None) == 'WorkflowOutputParameter':
            return
        for stream in ('stdout', 'stderr'):
            if self.data_type_combobox.findText(stream) < 0:
                self.data_type_combobox.addItem(stream)

    def setDefaults(self):
        '''
        set the default values in the widgets
        The input follows the CommandOutputParameter
        # https://www.commonwl.org/v1.2/CommandLineTool.html#CommandOutputParameter
        it also needs the

        data: dict - the CommandOutputParameter to show
              Data can also be a CommandRecordField
        record_id: str - the name of the record to which the Record field belongs to.
        '''
        self.logger.debug(f"OutputDialog received {type(self.output_parameter)} {save(self.output_parameter)}")
        self.output_parameter_type= type(self.output_parameter).__name__ 
        if self.output_parameter_type not in [
                    'CommandOutputParameter',
                    'CommandOutputRecordField',
                    'WorkflowOutputParameter'
                ]:
            raise ValueError(f"Expected one of CommandOutputParameter, CommandOutputRecordField, WorkflowOutputParameter, got {type(self.input_parameter).__name__}")

        
        # set the values of the widgets
        if hasattr(self.output_parameter, 'id'):
            self.id_input.setText(self.output_parameter.id.split('#')[-1].split('/')[-1] )
        if hasattr(self.output_parameter, 'label'):
            self.label_input.setText(self.output_parameter.label)
        if hasattr( self.output_parameter, 'loadcontents' ):
            self.load_content_checkbox.setChecked( self.output_parameter.loadContents)
        if hasattr( self.output_parameter, 'doc'):
            self.description_input.setText(self.output_parameter.doc) 

        required=not  is_optional(self.output_parameter) 
        self.required_checkbox.setChecked(required)
        if not required:
            try:
                self.output_parameter.type_.remove('null')
            except ValueError:
                pass

        single_item=False
        array_optional=is_optional_array(self.output_parameter)
        array_item=is_array( self.output_parameter )


        if array_optional and not array_item:
            self.array_combobox.setCurrentText('Allow Array')
        elif array_item:
            self.array_combobox.setCurrentText('Array Only')
        else:
            self.array_combobox.setCurrentText('Single Item')
        
        
        output_type=get_type( self.output_parameter,result=[]) 
        try:
            output_type.remove('array')
        except ValueError:
            pass
        logger.debug(f"Setting data type '{output_type}'")
        
        # Check for record field and set checkbox and record_id if needed
        
        
        
        # get the tags for an enum
        if (isinstance(output_type, list) and 'enum' in output_type) or \
            output_type == 'enum':
            enum_fields = []
            field_name = ''
            if self.output_parameter.type_ == 'enum':
                enum_fields = self.output_parameter.symbols if hasattr(self.output_parameter, 'symbols') else []
                if hasattr(self.output_parameter, 'name'):
                    field_name = self.output_parameter.name
            elif hasattr(self.output_parameter.type_, 'type_') and self.output_parameter.type_.type_ == 'enum':
                enum_fields = self.output_parameter.type_.symbols if hasattr(self.output_parameter.type_, 'symbols') else []
                if hasattr(self.output_parameter.type_, 'name'):
                    field_name = self.output_parameter.type_.name
            elif isinstance(self.output_parameter , list):
                for e in self.output_parameter:
                    if hasattr(e, 'type_') and e.type_ == 'enum':
                        enum_fields = e.symbols if hasattr(e, 'symbols') else []
                        if hasattr(e, 'name'):
                            field_name = e.name
                        break
            elif isinstance(self.output_parameter.type_ , list):
                for e in self.output_parameter.type_:
                    if hasattr(e, 'type_') and e.type_ == 'enum':
                        enum_fields = e.symbols if hasattr(e, 'symbols') else []
                        if hasattr(e, 'name'):
                            field_name = e.name
                        break
            if field_name:
                self.field_name_input.setText(field_name.split('#')[-1].split('/')[-1])
            if enum_fields:
                enum_fields=[ y.split("/")[-1] for y in [ x.split('#')[-1] for x in enum_fields ] ]
            logger.debug(f"We have an enum type {output_type} with fields {enum_fields}")
        # get the information for a record
        if (isinstance(output_type, list) and 'record' in output_type) or \
            output_type == 'record':
            # dependent parameters (type = record with a list of fields)
            if hasattr( self.output_parameter.type_ , 'fields') and \
               isinstance(self.output_parameter.type_.fields, list) :
                output_type='record dependent arguments'
            
            if isinstance( self.output_parameter.type_ , list):
                output_type='record mutually exclusive arguments'
            
            logger.debug(f"Record type {output_type}")
            logger.debug(f"Record id { self.output_parameter.id.split('#')[-1]}")
        # set the necessary ui for a record field
        if re.search("CommandOutputRecordField", str(type(self.output_parameter))):
            self.record_field_checkbox.setChecked(True)
            

        if isinstance(output_type, list) and len(output_type)>1:
            raise Exception(f"input type {output_type} is a list with many elements {len(output_type)}")
        self._offerStreamTypes()
        self.data_type_combobox.setCurrentText( output_type[0] if isinstance(output_type, list) else output_type)
        
        self.onDataTypeChanged()
        # We need to add the enum_fields after the tag widget has been enabled
        try:
            if enum_fields:
                self.enum_table_widget.setTags( enum_fields )
        except UnboundLocalError: # we don't have enum
            pass
        # if the input is a rcord we define the record id.
        if hasattr(self , 'record_name') and self.data_type_combobox.currentText().startswith('record'):
            self.record_id.setText( self.output_parameter.id.split('#')[-1])
        # if the input is a CommandRecordField and the record_id is provided
        if hasattr(self, 'record_name') and record_id:
            self.record_id.setText( record_id)


        # need to find teh outputBinding
        # either from the data
        # or from the type_ if it exists
        # or from items of a list
        outputBindings=[] # we may have inputbinding in the data or in the type_
        if hasattr(self.output_parameter,'outputBinding') and self.output_parameter.outputBinding:
            logger.debug(f"Shallow outputBinding {self.output_parameter.outputBinding}")
            outputBindings.append(self.output_parameter.outputBinding)
        if hasattr(self.output_parameter.type_,'outputBinding') and self.output_parameter.type_.outputBinding:
            logger.debug(f"type outputBinding {self.output_parameter.type_.outputBinding}")
            outputBindings.append(self.output_parameter.type_.outputBinding)
        if isinstance(self.output_parameter, list):
            logger.debug(f"list of items ")
            for item in self.output_parameter:
                if hasattr(item, 'outputBinding') and item.outputBinding:
                    logger.debug(f"Item outputBinding {item.outputBinding}")
                    outputBindings.append(item.outputBinding)
                if hasattr(item, 'type_') and hasattr(item.type_, 'outputBinding') and item.type_.outputBinding:
                    logger.debug(f"Item type outputBinding {item.type_.outputBinding}")
                    outputBindings.append(item.type_.outputBinding)
        if isinstance(self.output_parameter.type_, list):
            logger.debug(f"list of items ")
            for item in self.output_parameter.type_:
                if hasattr(item, 'outputBinding') and item.outputBinding:
                    logger.debug(f"Item outputBinding {item.outputBinding}")
                    outputBindings.append(item.outputBinding)
                if hasattr(item, 'type_') and hasattr(item.type_, 'outputBinding') and item.type_.outputBinding:
                    logger.debug(f"Item type outputBinding {item.type_.outputBinding}")
                    outputBindings.append(item.type_.v)


        
        if len(outputBindings) > 0:
            for outputBinding in outputBindings:
                # print(f"OutputBinding {save(outputBinding)}")
                if hasattr(outputBinding,'glob') and outputBinding.glob:
                    self.glob_input.setText(outputBinding.glob)
                if hasattr(outputBinding,'loadContents') and outputBinding.loadContents and self.load_content_checkbox :
                    self.load_content_checkbox.setChecked(outputBinding.loadContents)
                if hasattr(outputBinding,'outputEval') and outputBinding.outputEval:
                    self.output_eval.setText(outputBinding.outputEval)
                    # Ensure the outputEval field is enabled if there's a value
                    self.output_eval.setEnabled(True)
                    self.output_eval_code.setEnabled(True)
                    self.output_eval_label.setStyleSheet("")
                    self.output_eval.setStyleSheet("")
        self.description_input.setText( self.output_parameter.doc  or '')
        # (type_of_item, list_of_items)=CWLdataType( self.data )
        # if  'enum' in type_of_item:
        #     idx=type_of_item.index('enum')
        #     self.enum_table_widget.setTags( list_of_items[idx] )
            
        if hasattr(self.output_parameter,'format') and self.output_parameter.format and hasattr(self,'file_type_list_widget'):
            self.file_type_list_widget.populateFromCWL( self.output_parameter.format)
        
        if hasattr(self.output_parameter,'secondaryFiles') and self.output_parameter.secondaryFiles:
            self.secondary_files_input.populateFromCWL( self.output_parameter.secondaryFiles)
        if hasattr(self.output_parameter,'streamable') and self.output_parameter.streamable:
            self.streamable_checkbox.setChecked( self.output_parameter.streamable or False)
        
        # Load pickValue and linkMerge for WorkflowOutputParameter
        if self.output_parameter_type == 'WorkflowOutputParameter':
            if hasattr(self.output_parameter, 'pickValue') and self.output_parameter.pickValue:
                self.pick_value_combobox.setCurrentText(self.output_parameter.pickValue)
            if hasattr(self.output_parameter, 'linkMerge') and self.output_parameter.linkMerge:
                self.link_merge_combobox.setCurrentText(self.output_parameter.linkMerge)

        # if self.data.get('record'):
        #     self.record_field_checkbox.setChecked(True)
        #     if self.data.get('record').get('record_type') == 'dependent':
        #         if hasattr(self, 'record_dependent'):
        #             self.record_dependent.setChecked(True)
        #     if self.data.get('record').get('record_type') == 'exclusive':
        #         if hasattr(self, 'record_mutually_exclusive'):
        #             self.record_mutually_exclusive.setChecked(True)
        #     self.record_name.setText(self.data.get('record').get('name'))
        #     self.record_name.setVisible(True)
            # Set data for inputs group widget if available

    def onCodeEditor(self, widget_to_update=None):

         # Show the dialog
        dialog = JavaScriptEditorDialog(parent=self)
        dialog.cwl_dict=self.output_parameter
        if self.glob_input.text():
            dialog.editor.setText( self.glob_input.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the JavaScript code when dialog is accepted
            self.code = dialog.get_javascript_code()
            # print("JavaScript code submitted:", code)
            if self.code:
                widget_to_update.setText( self.code)
                self.codeUpdated.emit()

    def onRecordFieldChanged(self, state):
        """
        Show or hide record name widget based on checkbox state
        """
        is_checked = self.record_field_checkbox.isChecked()
        self.record_id.setVisible(is_checked)
        
        # Make sure field_name_input is visible for enum or when record_field_checkbox is checked
        data_type = self.data_type_combobox.currentText()
        is_enum = data_type == "enum"
        self.field_name_label.setVisible(is_enum or is_checked)
        self.field_name_input.setVisible(is_enum or is_checked)

    # added this function here only for testing purposes.
    # This function should be a copy of the same function
    # in the qInputs.py
    def getData( self) -> Tuple[Any,str]:
        """
        Convert a dictionary to a CWL CommandOutputParameter object.
        
        Args:
            cwl_dict: Dictionary with argument properties
            
        Returns:
            A CWL CommandInputParameter object
            or a 
            tuple (CommandInputRecordSchema , record-name, record-type) where 
            the record_id corresponds to the record that the input will be added
            the record_type can be dependent or mutual 

        """

        # Get the appropriate CWL module
        module = get_cwl_module(self.cwl_version) 
        
        # position = 0
        # try:
        #     position = int(cwl_dict.get('outputBinding',{}).get('position', '0'))
        # except ValueError:
        #     self.logger.warning(
        #         f"Invalid position value: {cwl_dict.get('outputBinding').get('position')}, using 0"
        #     )
        # Create a CommandLineBinding object
        output_type=self.data_type_combobox.currentText()
        array_type=self.array_combobox.currentText()

        # for dict (includes null or enum)
        if output_type == 'enum':
            output_type=module.CommandOutputEnumSchema(
                symbols=self.enum_table_widget.getTags(),
                type_='enum',
                name=self.field_name_input.text()
            )
        # handle array
        if array_type == 'Array Only':
            output_type=module.CommandOutputArraySchema(
                items=output_type,
                type_='array'
            )
        if array_type == 'Allow Array':
            output_type=[
                output_type,
                module.CommandOutputArraySchema(
                    items=output_type,
                    type_='array'
                )
            ]

        # handle not required
        if self.required_checkbox.isChecked() is False:
            output_type=['null', output_type]
        # print(f"Output type is {output_type}")
        # print(f"Output contains { save(output_type)}")
        binding=None
        if self.glob_input.text() or self.output_eval.text():
            binding = module.CommandOutputBinding()
            # print("Preparing the outputBinding")
            binding_args={}
            if hasattr(binding, 'glob') and self.glob_input.text():
                binding_args['glob']= self.glob_input.text()
            if ( hasattr(binding, 'loadListing') and 
                self.load_listing_combobox and
                self.load_listing_combobox.currentText() ):
                binding_args['loadListing']=self.load_listing_combobox.currentText()
            

            
            # Always include outputEval if it has a value (it's always enabled now)
            if hasattr( binding, 'outputEval') and self.output_eval.text():
                binding_args['outputEval'] = self.output_eval.text()
                
            # loadContents only when set (or when it was set before)
            if hasattr(self, 'load_content_checkbox') and self.load_content_checkbox:
                original = getattr(getattr(getattr(self, 'output_parameter', None), 'outputBinding', None),
                                   'loadContents', None)
                if self.load_content_checkbox.isChecked() or original is not None:
                    binding_args['loadContents'] = self.load_content_checkbox.isChecked()
                
            binding = module.CommandOutputBinding(**binding_args)
            # print(f"Binding is {save(binding)}")
            # print(f"""id={self.id_input.text()}, \n
            #     label={self.label_input.text()},\n
            #     secondaryFiles={self.secondary_files_input.getData() if self.secondary_files_input else None} ,\n
            #     streamable={self.streamable_checkbox.isChecked() if self.streamable_checkbox else None}, \n
            #     doc={self.description_input.toPlainText()},\n
            #     outputBinding={save(binding)},\n
            #     type_={save(output_type)},\n
            #     format={self.file_type_list_widget.getTags() if self.file_type_list_widget else None}""")
            # create fields 
        
        # optional attributes are only written when set (no [] / false defaults)
        secondary_files = (self.secondary_files_input.getData() if self.secondary_files_input else None) or None
        streamable = None
        if self.streamable_checkbox is not None:
            streamable = True if self.streamable_checkbox.isChecked() else None
            if streamable is None and getattr(getattr(self, 'output_parameter', None), 'streamable', None) is False:
                streamable = False

        if self.output_parameter_type=='CommandOutputParameter':
            outputparameter=module.CommandOutputParameter(
                id=self.id_input.text(), # can be many input types
                label=self.label_input.text() or None,
                secondaryFiles=secondary_files,
                streamable=streamable, 
                doc=self.description_input.toPlainText() or None,
                outputBinding=binding,
                type_=output_type
            )
        elif self.output_parameter_type=='WorkflowOutputParameter':
            outputparameter=module.WorkflowOutputParameter(
                id=self.id_input.text(), # can be many input types
                label=self.label_input.text() or None,
                secondaryFiles=secondary_files,
                streamable=streamable, 
                doc=self.description_input.toPlainText() or None,
                type_=output_type
            )
            if self.pick_value_combobox.currentText() != '-- None --':
                outputparameter.pickValue=self.pick_value_combobox.currentText()
            if self.link_merge_combobox.currentText() != '-- None --':
                outputparameter.linkMerge=self.link_merge_combobox.currentText() 
        else:
            raise ValueError(f"Unknown parameter type.")
        format=self.file_type_list_widget.getData() if self.file_type_list_widget else None
        if isinstance(format, list) and format:
            format=format[0]
        if format:
            outputparameter.format=format

        
        # print(f"Final output parameter {save(outputparameter)}")
        return (outputparameter)



if __name__ == '__main__':

    from cwl_utils_handler import CWLType,get_cwl_module
    from cwl_utils.parser import save
    from CWLparser import Parser
   
    # load the configuration
    conf=Configuration()
    conf.loadConfiguration( "commandLineWindow.yaml")#,"dataStructures.yaml"] )
    data.configuration=conf.getConfiguration()
    datatypes=Configuration()
    datatypes.loadConfiguration("dataStructures.yaml")
    data.datatypes=datatypes.getConfiguration()
    app = QApplication(sys.argv)


    tests_dir=Path(__file__).resolve().parents[1] / "tests"
    cwl_dict=Parser( str(tests_dir / "10-outputs.cwl")).getCWL()
    
    
    dialog = OutputDialog( parent=app.activeWindow())
    input=cwl_dict.outputs[0]
    
    print(f"Field {save(input)}")
    # dialog.setDefaults( input , rec_id)
    dialog.setDefaults(input)
    if dialog.exec():
        cwl_dict=dialog.getData()
        print("Accepted")
        
        (inputparameter, record_name, record_type)=convertDictToCWL( cwl_dict )
        print(f"The inputparameters is {json.dumps( save(inputparameter), indent=3)}")
        
        print(f"Record {record_name}, of type {record_type}")
        sys.exit(0)
    else:
        print("Rejected")
        run=False
        sys.exit(0)




    run=True
    while run:


        dialog = OutputDialog( parent=app.activeWindow()) 
        if dialog.exec():
            cwl_dict=dialog.getData()
            print("Accepted")
        else:
            print("Rejected")
            sys.exit(0)

        print(f"===\n{json.dumps(cwl_dict,indent=3)}\n===")

        outputparameter=convertDictToCWL( cwl_dict )

        print(f"The outputparameters is {json.dumps( save(outputparameter), indent=3)}")
        

    sys.exit(0)

    sys.exit(app.exec())