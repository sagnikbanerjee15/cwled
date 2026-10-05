import os
import sys

from ruamel.yaml import YAML
import ruamel.yaml
from ruamel.yaml.scalarstring import LiteralScalarString
from pathlib import Path,PosixPath
import json
import logging
import data
import workspaceFolders
from itertools import chain
from typing import Union,Any,List
import copy
from copy import deepcopy
import io
# Change the import statement to only include confirmed available functions
from cwl_utils.parser import LoadingOptions, load_document_by_uri, save, load_document_by_string
from schema_salad.exceptions import ValidationException
from cwl_utils_handler import get_cwl_module
from cwl_fetcher import getFetcher
from urllib.parse import urlparse
from helperFunctions import uriToPath
import inspect
import uuid
import re
from ports import PortSplitter

class Parser(object):
    """
    A parser for Common Workflow Language (CWL) documents.

    This class handles reading, creating, manipulating, and saving CWL documents.
    It can load from files (YAML or JSON), Python dictionaries, or existing
    `cwl_utils` objects. It provides methods to create empty documents,
    save them in different formats, and perform normalization tasks like
    adjusting file paths and stripping identifiers.

    Attributes:
        cwl_tool (Any): The `cwl_utils` object representing the CWL document.
        path (Path): The file path of the loaded or saved document.
        is_file (bool): True if the parser was initialized from a file.
        is_dict (bool): True if the parser was initialized from a dictionary.
    """

    cwl_tool = None
    defaults = {}
    is_file = False
    is_dict = False
    yaml = ruamel.yaml.YAML(typ=['rt', 'string'])  # for printing yaml

    def __init__(self,
                 input: Union[str, Path, dict, Any] = None,
                 baseuri: str = None,
                 fileuri: str = None,
                 cwlVersion: str = 'v1.2'):
        """
        Initializes the Parser with a CWL document source.

        The input can be a file path (string or Path object), a dictionary
        representing a CWL document, a `cwl_utils` object, or a string
        specifying a CWL type to create a new, empty document.

        Args:
            input (Union[str, Path, dict, Any], optional): The source of the CWL
                document. Can be a path, dict, cwl_utils object, or type string.
                Defaults to None.
            baseuri (str, optional): The base URI for resolving relative paths,
                used when processing a dictionary. Defaults to None.
            fileuri (str, optional): The file URI for the document, used when
                processing a dictionary. Defaults to None.
            cwlVersion (str, optional): The CWL version to use when creating a
                new document. Defaults to 'v1.2'.
        
        Raises:
            FileNotFoundError: If the input is a path that does not exist.
            Exception: If the input type is not supported.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        # Get the frame of the caller
        caller_frame = inspect.stack()[1]
        # Get the name of the calling function
        caller_function = caller_frame.function
        # Try to get the 'self' object from the caller's local variables
        caller_self = caller_frame.frame.f_locals.get('self', None)
        if caller_self:
            # If 'self' exists, get the class name from it
            caller_class = caller_self.__class__.__name__
            calling_stack=f"Called from: {caller_class}.{caller_function}"
        else:
            # Otherwise, just print the function name
            calling_stack=f"Called from: {caller_function}"
        self.path = None # Initialize self.path


        # Try to convert input to PosixPath if it's a string
        # The input can be a cwl type in which case we create a new one.
        if isinstance(input, str):
            if input in ['CommandLineTool','ExpressionTool','Workflow']:
                pass
            else:
                try:
                    pp=urlparse(input)
                    if bool(pp.scheme) :
                        # print(f"This is a URI, {pp.scheme} for file {pp.path}")
                        input=Path(uriToPath(input))
                    # Check if the file exists
                    potential_path = PosixPath(input)
                    if (potential_path.exists()):
                        input = potential_path
                        self.logger.debug(f"Converted string input to Path: {input}")
                    else:
                        self.logger.warning(f"Input file path does not exist: {input}")
                        raise FileNotFoundError(f"File does not exist: {input}")
                except Exception as e:
                    self.logger.debug(f"Could not convert input string to Path: {e}")
                    raise FileNotFoundError(f"File does not exist: {input}")
                    # Keep it as string if conversion fails
        if re.search('cwl_utils.parser', str(type(input))):
            # input is already a cwl_utils object
            # print("Received a cwl_utils object.")
            self.logger.debug(f"Received a cwl_utils object. {calling_stack}")
            self.cwl_tool = deepcopy(input)
            self.is_dict=False
        elif isinstance(input, PosixPath) or isinstance(input, Path):
            # Double-check file existence before loading
            # print(f"Loading from file {input}")
            self.logger.debug(f"Loading CWL from file {input}. {calling_stack}")
            # print(f"Loading CWL from file {input}.")
            self.loadFile(input) # self.path is set here
            self.is_file=True
        elif isinstance(input,dict):
            # cwl_dict=input # No, pass 'input' directly to setCWL
            # print("Parsing dictionary")
            self.logger.debug(f"Parsing dict as a new object. {calling_stack}")
            self.setCWL( input , fileuri=fileuri, baseuri=baseuri )
            self.is_dict=True
        elif isinstance( input,str) or input is None:
            # print("Creating empty object")
            self.logger.debug(f"Creating empty object {input}, version {cwlVersion}. {calling_stack}")
            self.createEmpty( input , cwlVersion=cwlVersion)
            self.is_dict=True
        else:
            raise Exception(f"CWLparser has not received a file or a dict to process, instead it got {type( input )}")
        
        
    def saveFile(self, 
                 filename:Union[str,PosixPath,Path], 
                 format:str='YAML',
                 inside_workspace=True):
        """
        Saves the CWL document to a file in YAML or JSON format.

        Before saving, it performs several normalization steps, such as
        stripping workflow IDs from sources, converting documentation to HTML,
        and making run paths relative.

        Args:
            filename (Union[str, PosixPath, Path]): The path to save the file to.
            format (str, optional): The output format, either 'YAML' or 'JSON'.
                Defaults to 'YAML'.
            inside_workspace (bool, optional): If True, enforces that the file
                is saved within one of the workspace folders. Defaults to True.
        
        Raises:
            Exception: If `inside_workspace` is True and the path is outside
                the workspace folders.
        """
        if isinstance(filename, str):
            self.path=Path(filename)
        else:
            self.path=filename
        # check that the filename is inside the workspace
        if inside_workspace:
            
            if not workspaceFolders.isInsideWorkspace(self.path):
                folders = ", ".join(workspaceFolders.folders()) or "<none>"
                self.logger.warning(f"Trying to save file {self.path} outside of the workspace folders {folders}")
                raise Exception(f"Cannot save file {self.path} outside of the workspace folders ({folders}). "
                                "Add its folder to the workspace first.")
        if not self.path.parent.is_dir():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # print(f"Saving file: [{self.path.absolute()}] ({type(self.path)}) ")
        
        # we want to remove the id of the workflow from the source and outputSource of the
        # steps and the outputs
        # note that both source and outputSource can be a list of strings or a single string
        if self.cwl_tool.class_ == 'Workflow':
            self._strip_ids()
            self._strip_workflow_id()
            self._strip_source()
            self._strip_scatter()
            self._strip_outputSource()
            self._relative_path()
        self._toHTML()

        # remove empty envVars
        for req in list(self.cwl_tool.requirements or []):
            if req.class_ == 'EnvVarRequirement' and hasattr(req, 'envDef'):
                for env in req.envDef:
                    if env.envValue is None or env.envValue == "":
                        req.envDef.remove(env)
                if len(req.envDef) == 0:
                    self.cwl_tool.requirements.remove(req)  

        cwl_dict=save(self.cwl_tool,relative_uris=True)
        
        # Remove empty baseCommand if present
        if 'baseCommand' in cwl_dict and (not cwl_dict['baseCommand'] or not cwl_dict['baseCommand'][0]) :
            del cwl_dict['baseCommand']
            self.logger.debug("Removed empty baseCommand from CWL")
         
        # Convert multiline strings to literal block scalars for YAML
        if not format.startswith('JSON'):
            cwl_dict = self._convert_multiline_strings(cwl_dict)
        
        with open(self.path, 'w', encoding='utf-8') as output:
            if format.startswith('JSON'):
                json.dump(cwl_dict, output, indent=3)
            else:
                # then dump it using ruamel.yaml
                self.yaml.preserve_quotes = False 
                self.yaml.default_flow_style = False  # Use block style, not flow style
                self.yaml.default_style = None  # Use plain style (no quotes) when possible
                self.yaml.width = 4096  # Prevent line wrapping
                self.yaml.dump( cwl_dict , output)
        self.logger.info(f"✅ Saved file {self.path}")

    def _convert_multiline_strings(self, obj):
        """
        Recursively convert strings containing newlines to LiteralScalarString for YAML.
        
        This ensures that multiline strings (like documentation) are saved using
        YAML literal block scalar style (|) instead of escaped newlines.
        
        Args:
            obj: Dictionary, list, or other object to process
            
        Returns:
            Processed object with multiline strings converted to LiteralScalarString
        """
        if isinstance(obj, dict):
            return {k: self._convert_multiline_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_multiline_strings(item) for item in obj]
        elif isinstance(obj, str) and '\n' in obj:
            # Convert strings with newlines to literal block scalar style (|)
            return LiteralScalarString(obj)
        else:
            return obj

    def _strip_outputSource(self):
        """
        Removes the workflow ID prefix from the `outputSource` fields of
        workflow outputs. This simplifies the source URIs to be relative
        to the workflow itself.
        """
        if not hasattr(self.cwl_tool, 'outputs'):
            return
        
        for idx,outp in enumerate(self.cwl_tool.outputs):
            if hasattr(outp, 'outputSource') and outp.outputSource:
                if isinstance( outp.outputSource, list):
                    new_sources=[]
                    for s in outp.outputSource:
                        ps=PortSplitter(s, workflow_id=self.cwl_tool.id)
                        new_source= f"{ps.stepport}" if ps.stepport else ps.port_id
                        new_sources.append( new_source )
                    outp.outputSource=new_sources
                else:
                    ps=PortSplitter(outp.outputSource, workflow_id=self.cwl_tool.id)
                    outp.outputSource= f"{ps.stepport}" if ps.stepport else ps.port_id

    def _toHTML(self):
        """
        Convert the cwl tool documentation to HTML format.
        
        If the `doc` field exists in the `cwl_tool` object, this method
        converts its content from Markdown to HTML and updates the `doc`
        field with the HTML content.
        """
        if hasattr(self.cwl_tool, 'doc') and self.cwl_tool.doc:
            import markdown
            html = markdown.markdown(self.cwl_tool.doc, extensions=['extra'])
            self.cwl_tool.doc = html

    def _toMarkdown(self):
        """
        Convert the cwl tool documentation from HTML to Markdown format.
        
        If the `doc` field exists and appears to be HTML, this method
        converts its content to Markdown and updates the `doc` field.
        """
        if hasattr(self.cwl_tool, 'doc') and self.cwl_tool.doc:
            # A simple check to see if the doc string contains HTML tags
            is_html = bool(re.search(r'<[a-z][\s\S]*>', self.cwl_tool.doc, re.IGNORECASE))
            if is_html:
                from markdownify import markdownify as md
                markdown_text = md(self.cwl_tool.doc, bullets='-')
                self.cwl_tool.doc = markdown_text

    def _strip_workflow_id(self):
        """
        Recursively removes the workflow ID prefix from all port identifiers
        (`id` and `name` fields) within a workflow definition, including
        inputs, outputs, and steps.
        """
        if not self.cwl_tool: return
        # if not self.cwl_tool.class_  == "Workflow": return

        def clean_port(obj):
            if hasattr(obj, 'id') and isinstance(obj.id, str):
                ps=PortSplitter(obj.id, workflow_id=self.cwl_tool.id)
                if type(obj).__name__ in ['WorkflowStepInput',
                                          'WorkflowStepOutput',
                                          'CommandInputParameter',
                                          'CommandOutputParameter']:
                    obj.id=ps.port_id
                else:
                    obj.id= ps.stepport if ps.stepport else ps.port_id
            if hasattr(obj, 'name') and isinstance(obj.name, str):
                ps=PortSplitter(obj.name, workflow_id=self.cwl_tool.id)
                obj.name=ps.port_id
                

            # Recurse into inputs, outputs, steps, etc.
            if hasattr(obj, 'inputs') and obj.inputs:
                for item in obj.inputs:
                    clean_port(item)
            if hasattr(obj, 'outputs') and obj.outputs:
                for item in obj.outputs:
                    clean_port(item)
            if hasattr(obj, 'steps') and obj.steps:
                for item in obj.steps:
                    clean_port(item)
            if hasattr(obj, 'in_') and obj.in_:
                for item in obj.in_:
                    clean_port(item)
            if hasattr(obj, 'out') and obj.in_:
                for item in obj.out:
                    clean_port(item)
            if hasattr(obj, 'type_') and obj.type_:
                if isinstance( obj.type_, list):
                    for t in obj.type_:
                        clean_port(t)
                else:
                    clean_port( obj.type_ )
            if hasattr(obj, 'symbols') and obj.symbols:
                for idx,item in enumerate(obj.symbols):
                    ps=PortSplitter(item, workflow_id=self.cwl_tool.id)
                    obj.symbols[idx] = ps.port_id
            if hasattr(obj, 'fields') and obj.fields:
                logger.debug(f"====== having fields in object {obj} of type {type(obj)}")
                for item in obj.fields:
                    clean_port(item)
        clean_port(self.cwl_tool)

    def _strip_ids(self):
        """
        Recursively removes the URI prefix (e.g., 'file://...#') from `id`
        and `name` attributes throughout the CWL document, leaving only the
        fragment identifier.
        """
        
        if not self.cwl_tool: return

        def clean_id(obj):
            
            if hasattr(obj, 'id') and isinstance(obj.id, str) :
                obj.id = obj.id.split('#')[-1]
            if hasattr(obj, 'name') and isinstance(obj.name, str):
                obj.name = obj.name.split('#')[-1]

            # Recurse into inputs, outputs, steps, etc.
            if hasattr(obj, 'inputs') and obj.inputs:
                for item in obj.inputs:
                    clean_id(item)
            if hasattr(obj, 'outputs') and obj.outputs:
                for item in obj.outputs:
                    clean_id(item)
            if hasattr(obj, 'steps') and obj.steps:
                for item in obj.steps:
                    clean_id(item)
            if hasattr(obj, 'in_') and obj.in_:
                for item in obj.in_:
                    clean_id(item)
            if hasattr(obj, 'out') and obj.in_:
                for item in obj.out:
                    clean_id(item)
            if hasattr(obj, 'type_') and obj.type_:
                if isinstance( obj.type_, list):
                    for t in obj.type_:
                        clean_id(t)
                else:
                    clean_id( obj.type_ )
            if hasattr(obj, 'symbols') and obj.symbols:
                for idx,item in enumerate(obj.symbols):
                    obj.symbols[idx] = item.split('#')[-1]


        clean_id(self.cwl_tool)
        

    def _strip_source(self):
        """
        Removes the workflow ID prefix from the `source` fields of workflow
        step inputs. This simplifies the source URIs to be relative to the
        workflow's scope.
        """
        if not hasattr(self.cwl_tool, 'steps'): return
        for step in self.cwl_tool.steps:
            for idx,inp in enumerate(step.in_):
                if hasattr(inp, 'source') and inp.source:
                    if isinstance( inp.source, list):
                        new_sources=[]
                        for s in inp.source:
                            ps=PortSplitter(s, workflow_id=self.cwl_tool.id)
                            new_source= f"{ps.stepport}" if ps.stepport else ps.port_id
                            new_sources.append( new_source )
                        inp.source=new_sources
                    else:
                        ps=PortSplitter(inp.source, workflow_id=self.cwl_tool.id)
                        inp.source= f"{ps.stepport}" if ps.stepport else ps.port_id
                    # return inp

    def _strip_scatter(self):
        """
        Removes the workflow ID prefix from the `scatter` fields of workflow
        step inputs. This simplifies the scatter URIs to be relative to the
        workflow's scope.
        """
        if not hasattr(self.cwl_tool, 'steps'): return
        for step in self.cwl_tool.steps:
            if hasattr(step, 'scatter') and step.scatter:
                if isinstance(step.scatter, list):
                    new_scatters = []
                    for s in step.scatter:
                        ps = PortSplitter(s, workflow_id=self.cwl_tool.id)
                        new_scatter = ps.port_id
                        new_scatters.append(new_scatter)
                    step.scatter = new_scatters
                else:
                    ps = PortSplitter(step.scatter, workflow_id=self.cwl_tool.id)
                    step.scatter = ps.port_id

    def _normalizeLoaded(self):
        """The changes made to a document that was just loaded, so that it is shown the way it is edited."""
        self._strip_ids()
        self._strip_workflow_id()
        self._strip_source()
        self._strip_scatter()
        self._strip_outputSource()
        self._relative_path()
        self._toMarkdown( )

    def loadString(self, text:str, filename:Union[str,PosixPath,Path]):
        """
        Loads a CWL document from its text, as if it was the content of the file
        ``filename`` (which is used to resolve the paths the document refers to,
        and need not hold this text): for example an earlier revision of a file.
        The document is normalized as in ``loadFile``.
        """
        self.path = Path(filename)
        self.cwl_tool = load_document_by_string(
            text,
            uri=self.path.absolute().as_uri(),
            loadingOptions=LoadingOptions(fetcher=getFetcher())
        )
        self._normalizeLoaded()
        self.is_file = True

    def loadFile(self, filename:Union[str,PosixPath,Path]):
        """
        Loads a CWL document from a file.

        It uses `cwl_utils` to parse the document, then performs normalization
        steps like stripping IDs and sources, converting paths, and converting
        documentation from HTML to Markdown.

        Args:
            filename (Union[str, PosixPath, Path]): The path to the CWL file.

        Raises:
            FileNotFoundError: If the file does not exist.
            Exception: If the path is not a file.
            ValidationException: If the CWL document is invalid.
        """
        if isinstance(filename, str):
            self.path=Path(filename)
        else:
            self.path=filename
        # print(f"Loading file: [{self.path.absolute()}] ({type(self.path)}) {self.path.is_file()}")
        if not self.path.exists():
            raise FileNotFoundError(f"File {filename} does not exist. Current directory {os.getcwd()}")
        if self.path.is_file() is False:
            raise Exception(f"File {filename} was not found")
        # print(f"File {self.path} exists, loaded...")
        
        # use the cwl_utils parser instead of parsing directly
        # the YAML/JSON file
        try:

            self.cwl_tool = load_document_by_uri(
                self.path,
                loadingOptions=LoadingOptions(fetcher=getFetcher())
            )
            self._normalizeLoaded()
            self.logger.info(f"✅ Loaded file {self.path}")
        except ValidationException as ve:
            # self.logger.error(f"Could not load file {self.path} due to validation error: {ve}")
            raise ve
        
        # change a few things to ensure consistent formatting.
        # if self.cwl_tool.class_ == 'Workflow':
        #     for step in self.cwl_tool.steps:
            
        #             if hasattr(inp, 'run'):
        #                 original_path=Path(inp.run).absolute()
        #                 relative_path=original_path.relative_to( self.path.parent.absolute() )
        #                 inp.run=str(relative_path)
        #     for outp in self.cwl_tool.outputs:
        #         self._simplifyOutputSource( outp )
        # self.cwl_tool.id=self.cwl_tool.id.split('#')[-1]


        # 2. Check the cwlVersion from the loaded object
        # This will usually reflect the version specified in the CWL file itself.
        if hasattr(self.cwl_tool, 'cwlVersion'):
            self.logger.info(f"Original cwlVersion from loaded object: {self.cwl_tool.cwlVersion}")
        else:
            self.logger.info("cwlVersion attribute not found on the loaded object.")
        # print(f"Loaded file {filename} -> {self.path}")

        # print(f"Loaded {json.dumps(save(self.cwl_tool))[0:50]}..{json.dumps(save(self.cwl_tool))[-50:]}")
        # print(f"Version {self.cwl_tool.cwlVersion}")

    def _relative_path(self):
        """
        Converts the `run` field of workflow steps to be relative to the
        workflow file's parent directory. This improves portability of the
        workflow.
        
        Note: This only applies to steps where run is a string (file path).
        If run is already an embedded object (e.g., after flattenWorkflow),
        it will be skipped.
        """
        if not hasattr( self.cwl_tool, 'steps'):
            return
        for step in self.cwl_tool.steps:
            if hasattr(step, 'run'):
                # Skip if run is already an embedded object (not a string path)
                if not isinstance(step.run, str):
                    continue
                    
                path=uriToPath(step.run)      # (a folder with a space in its name is in the URI as %20)
                if os.path.isabs( path ):
                    original_path=Path(path) # this is the abs path of the tool the workflow runs
                else:
                    original_path=  os.path.abspath(os.path.join( self.path.parent.absolute(), path))
                relative_path= os.path.relpath( original_path,  str(self.path.parent.absolute()) )
                # print(f"Run path               : {path}")
                # print(f"Original absolute path : {original_path}")
                # print(f"Relative path          : {relative_path}  (to {self.path.parent.absolute()})")
                step.run=str(relative_path)

    def createEmpty(self, cwl_type:str, cwlVersion:str):
        """
        Create an empty CWL object of the specified type using cwl_utils.
        
        The cwl_utils library provides classes that properly implement the
        CWL specification with all required attributes and methods.
        
        Args:
            cwl_type (str): The type of CWL object to create ('CommandLineTool',
                'ExpressionTool', or 'Workflow').
            cwlVersion (str): The CWL version for the new document (e.g., 'v1.2').
        
        Raises:
            ValueError: If the `cwl_type` is unknown.
        """

        self.logger.debug(f"Create an empty object {cwl_type} version {cwlVersion}")
        self.cwl_type = cwl_type

        module=get_cwl_module( cwlVersion )
        # Import necessary classes from cwl_utils.parser.cwl_v1_2
        
        id=f"{cwl_type}_{ str(uuid.uuid4())[:4]}"
        # Create an empty CWL object of the appropriate type
        if cwl_type == 'CommandLineTool':
            self.cwl_tool = module.CommandLineTool(
                id=id,
                inputs=[],
                outputs=[],
                cwlVersion=cwlVersion,
                baseCommand=[],
                # Additional fields with default values
                requirements=[],
                hints=[],
                label="",
                doc="",
                arguments=[]

            )
        elif cwl_type == 'ExpressionTool':
            self.cwl_tool = module.ExpressionTool(
                id=id,
                inputs=[],
                outputs=[],
                cwlVersion=cwlVersion,
                expression="${}",  # Empty expression
                # Additional fields with default values
                requirements=[],
                hints=[],
                label="",
                doc=""

            )
        elif cwl_type == 'Workflow':
            self.cwl_tool = module.Workflow(
                id=id,
                inputs=[],
                outputs=[],
                cwlVersion=cwlVersion,
                steps=[],
                # Additional fields with default values
                requirements=[],
                hints=[],
                label="",
                doc=""
            )
        else:
            self.logger.error(f"Unknown CWL type: {cwl_type}")
            raise ValueError(f"Unknown CWL type: {cwl_type}")
            
        self.logger.info(f"An empty {cwl_type} object has been created of version {cwlVersion}")


    def setCWL(self, 
               cwl_dict:dict,
               fileuri:str = None,
               baseuri:str = None):
        """
        Create a CWL object from a dictionary.
        
        This method converts a Python dictionary into the appropriate cwl_utils
        object based on the 'class' field in the dictionary.
        
        Args:
            cwl_dict (dict): A dictionary containing the CWL data.
        """
        self.logger.info(f"Loading CWL from existing dict")
        self.logger.info(f"{json.dumps( cwl_dict, indent=3)}")
        self.path=Path(uriToPath(fileuri))
        # convert the object to a string and
        # then load it using the cwl_utils parser
        # need to make sure that the ids and the paths are correctly set
        if not cwl_dict.get('id'):
            self.logger.warning(f"This dict does not contain the id key")
            cwl_dict['id']=f"{cwl_dict.get('class')}_{ str(uuid.uuid4())[:4]}"
        # print("Parsing dictionary")
        # for s in cwl_dict.get('steps'):
            # print(f"Step {s.get('id')} => {s.get('run')}")

        version=cwl_dict.get('cwlVersion')
        # print(f"Found version {version} in document")
        module=get_cwl_module( version )
        lo=module.LoadingOptions(
            fileuri=fileuri,
            baseuri=baseuri,
            fetcher=getFetcher()
        )
        self.cwl_tool = load_document_by_string(
            json.dumps(cwl_dict),uri=fileuri if fileuri else cwl_dict.get('id'),
            loadingOptions=lo,
            
        )
        
        self._strip_ids()
        self._strip_workflow_id()
        self._strip_source()
        self._strip_scatter()
        self._strip_outputSource()
        self._relative_path()
        self._toMarkdown( )
        


    def getCWL(self) -> Union[Any, None]:
            """
            Returns the raw `cwl_utils` object representing the document.

            Returns:
                Union[Any, None]: The `cwl_tool` object, or None if not loaded.
            """
            return( self.cwl_tool )


    def getDict(self) -> dict:
        """
        Converts the `cwl_tool` object to a Python dictionary.

        Returns:
            dict: A dictionary representation of the CWL document.
        """
        return( save(self.cwl_tool) )
        
    def gatherWorkflowDocumentation(self, parent_step_id:str = None, doc:List = None) -> None:
        """
        Extracts all the documentation of a workflow by recursively checking the documentation
        in each step's 'run' references (file paths or embedded objects).
        If a step's run file is itself a workflow, recursively gathers that workflow's 
        documentation as well.
        
        The method builds a list of documentation entries, each containing:
        - step_id: The hierarchical identifier for the step (e.g., "parent.child.grandchild")
        - documentation: The doc string from the CWL tool/workflow
        
        Only works on Workflow class documents. Has no effect on CommandLineTool
        or ExpressionTool documents.
        
        Args:
            parent_step_id (str, optional): The hierarchical ID of the parent step. 
                Defaults to None for top-level workflows.
            doc (List, optional): The list to append documentation entries to.
                If None, uses self.documentation_summary.
        """
        # Only process workflows
        if not hasattr(self.cwl_tool, 'class_') or self.cwl_tool.class_ != 'Workflow':
            self.logger.warning(f"gatherWorkflowDocumentation can only be applied to Workflow documents, not {getattr(self.cwl_tool, 'class_', 'unknown')}")
            return
        
        if not hasattr(self.cwl_tool, 'steps') or not self.cwl_tool.steps:
            self.logger.debug("Workflow has no steps to gather documentation from")
            return
        
        self.logger.info(f"Gathering documentation from workflow with {len(self.cwl_tool.steps)} steps")
        
        # Initialize documentation_summary if this is the top-level call
        if doc is None:
            self.documentation_summary = []
            doc = self.documentation_summary

        # Process each step
        for step_idx, step in enumerate(self.cwl_tool.steps):
            step_id = step.id if hasattr(step, 'id') else f"step_{step_idx}"
            
            # Construct the full hierarchical step ID
            full_step_id = f"{parent_step_id}.{step_id}" if parent_step_id else step_id
            
            if not hasattr(step, 'run'):
                self.logger.warning(f"Step {full_step_id} has no 'run' attribute")
                continue
            
            # If run is already an object (not a string), it's already embedded
            if not isinstance(step.run, str):
                self.logger.debug(f"Step {full_step_id} already has embedded run content")
                
                # Extract documentation from the embedded run object
                if hasattr(step.run, 'doc') and step.run.doc:
                    doc.append({
                        'step_id': full_step_id,
                        'documentation': step.run.doc
                    })
                
                # If it's a workflow object, recursively gather its documentation
                if hasattr(step.run, 'class_') and step.run.class_ == 'Workflow':
                    self.logger.debug(f"Recursively gathering documentation from embedded workflow in step {full_step_id}")
                    temp_parser = Parser(step.run)
                    temp_parser.gatherWorkflowDocumentation(full_step_id, doc)
                continue
            
            # Step.run is a string (file path or URI)
            try:
                self_fn = uriToPath(self.cwl_tool.loadingOptions.fileuri)
                self_dir = Path(self_fn).parent
                run_path = self_dir / step.run
                absolute_path = run_path.resolve()
                
                if not absolute_path.exists():
                    self.logger.warning(f"Step file does not exist: {absolute_path}")
                    continue
                    
                self.logger.debug(f"Processing step {full_step_id} with run: {run_path}")
                
                # Load the step file
                self.logger.debug(f"Loading step file: {absolute_path}")
                step_parser = Parser(absolute_path)
                
                # Extract the documentation from the loaded tool/workflow
                if hasattr(step_parser.cwl_tool, 'doc') and step_parser.cwl_tool.doc:
                    doc.append({
                        'step_id': full_step_id,
                        'documentation': step_parser.cwl_tool.doc
                    })
                
                # If the loaded file is a workflow, recursively gather its documentation
                if hasattr(step_parser.cwl_tool, 'class_') and step_parser.cwl_tool.class_ == 'Workflow':
                    self.logger.debug(f"Step file is a workflow, recursively gathering documentation: {absolute_path}")
                    step_parser.gatherWorkflowDocumentation(full_step_id, doc)
                
                self.logger.info(f"✅ Gathered documentation from step {full_step_id}: {run_path}")
                
            except FileNotFoundError as e:
                self.logger.error(f"Could not find step file {absolute_path}: {e}")
                # Don't raise - continue with other steps
                continue
            except Exception as e:
                self.logger.error(f"Error loading step file for {full_step_id}: {e}")
                # Don't raise - continue with other steps
                continue
        
        # Only log at top level
        if parent_step_id is None:
            self.logger.info(f"✅ Successfully gathered documentation from {len(doc)} steps")
            self.logger.debug(f"Documentation summary: {json.dumps([{'step_id': d['step_id'], 'doc_length': len(d['documentation'])} for d in doc], indent=2)}")

# GENERIC FUNCTIONS FOR CWL
logger=logging.getLogger(__name__)
logger.setLevel(data.configuration.get('logLevel',{}).get(__name__, 'WARNING'))

def is_array(parameter:Any )-> bool:
    """
    Determine if a CommandInputParameter is an array type.
    
    Args:
        parameter: A CommandInputParameter object
        
    Returns:
        bool: True if the parameter is an array, False otherwise
    """
    # If type_ is a CommandInputArraySchema object
    if hasattr(parameter.type_, 'type_') and parameter.type_.type_ == 'array':
        return True
        
    # If type_ is a list (union type), check if any element is an array
    if isinstance(parameter.type_, list):
        for t in parameter.type_:
            if (isinstance(t, str) and t == 'array') or \
            (hasattr(t, 'type_') and t.type_ == 'array'):
                return True
                
    # If type_ is the string 'array'
    if parameter.type_ == 'array':
        return True
        
    return False


def is_optional_array(parameter:Any) -> bool:
    """
    Determine if a CommandInputParameter can optionally be an array or single item.
    
    Args:
        parameter: A CommandInputParameter object
        
    Returns:
        bool: True if the parameter can be either array or single item, False otherwise
    """
    # First, check if the type is a list (union type)
    if not isinstance(parameter.type_, list):
        return False
    
    # Check if the list contains at least two types
    if len(parameter.type_) < 2:
        return False
    
    has_array = False
    has_non_array = False
    
    # Go through each type in the union
    for type_item in parameter.type_:
        # Check if it's an array type
        if (isinstance(type_item, str) and type_item == 'array') or \
           (hasattr(type_item, 'type_') and type_item.type_ == 'array'):
            has_array = True
        # Check if it's a non-array type (and not null)
        elif (isinstance(type_item, str) and type_item != 'null' and type_item != 'array') or \
             (hasattr(type_item, 'type_') and type_item.type_ != 'array'):
            has_non_array = True
    
    # Return true only if we found both array and non-array types
    return has_array and has_non_array


def is_optional(parameter: Any) -> bool:
    """
    Determine if a CommandInputParameter is optional.
    A parameter is optional if its type includes 'null'.
    
    Args:
        parameter: A CommandInputParameter object
        
    Returns:
        bool: True if the parameter is optional, False if required
    """
    # First check if type_ is a list (union type)
    if hasattr(parameter, 'type_') and isinstance(parameter.type_, list):
        # If 'null' is in the list of types, the parameter is optional
        return 'null' in parameter.type_
    


    # If type_ is an object with a 'type_' attribute
    if hasattr(parameter, 'type_') and hasattr(parameter.type_, 'type_'):
        # For complex types like arrays or records, check if they're optional
        if parameter.type_.type_ == 'array' and hasattr(parameter.type_, 'items'):
            # An array might have optional items
            if isinstance(parameter.type_.items, list):
                return 'null' in parameter.type_.items
        # For other complex types, they're not optional unless explicitly marked
        return False
    
    # If type_ is a string and it's 'null', the parameter is optional
    # (though this would be unusual as a standalone type)
    if hasattr(parameter, 'type_') and parameter.type_ == 'null':
        return True
    
    # If none of the above conditions are met, the parameter is required
    return False


def get_type(parameter: Any, result=[], level:int=1) -> list:
    """
    Get all possible types of a CommandInputParameter, excluding 'null'.
    
    Args:
        parameter: A CommandInputParameter object
        result : a list that keeps the data types (used for recursion)

        
    Returns:
        list: List of all possible types (as strings or objects) 
              excluding 'null'
    """
    char='\t'
    if level == 1:
        result=[]
    logger.debug(f"Received Results {result}")
    if isinstance( parameter, str):
        logger.debug(f"{char * level} parameter is a string: {parameter}")
        result.extend([parameter])
        logger.debug(f"{char * level} After appending the parameter string we have { result }")
    elif isinstance( parameter, list):
        logger.debug(f"{char * level} parameter is a list ")
        for t in parameter:
            if t != 'null':
                result.extend( get_type(t, result, level=level+1))
        logger.debug(f"{char * level} After extending the list we have { result }")
    # If type_ is a list (union type)
    elif hasattr(parameter, 'type_'):
        logger.debug(f"{char * level} parameter  has a type_ {parameter.type_}")
        result.extend(get_type( parameter.type_ , result=result, level=level+1))
        logger.debug(f"{char * level} After appending the type we have { result }")
    # If type_ is an object with a type_ attribute
    if hasattr(parameter, 'items') and parameter.items:
        logger.debug(f"{char * level} parameter has items: {save(parameter.items)}")
        result.append(parameter.items)
        logger.debug(f"{char * level} After appending the items we have { result }")
    if hasattr(parameter, 'fields') and parameter.fields:
        logger.debug(f"{char * level} parameter has fields: {save(parameter.fields)}")
        # For record types, include all field types
        for field in parameter.fields:
            logger.debug(f"{char * level} Working with field {save(field)}")
            if hasattr(field, 'type_') and field.type_ != 'null':
                result.extend(get_type(field.type_, result=result, level=level))
                logger.debug(f"{char * level} After appending the fields we have { result }")
    

    logger.debug(f"{char * level} ** emit Results {list(set(result))}")
    return list(set(result))


def get_items(parameter: Any, result=[]) -> list:
    """
    Get all possible items in an array.
    
    Args:
        parameter: A CommandInputParameter object
        result : a list that keeps the data types (used for recursion)

        
    Returns:
        list: List of all possible types (as strings or objects) 
              excluding 'null'
    """
    if isinstance( parameter, str):
        pass
    elif isinstance( parameter, list):
        for t in parameter:
            if t != 'null':
                result.extend( get_items(t, result))
    # If type_ is a list (union type)
    elif hasattr(parameter, 'type_'):
        result.extend(get_items( parameter.type_ , result=result))
    
    # If type_ is an object with a items attribute
    if hasattr(parameter, 'items'):
        result.append(parameter.items)

    return list(set(result))



def get_fields(parameter: Any, result=[]) -> list:
    """
    Get all possible types of a CommandInputParameter, excluding 'null'.
    
    Args:
        parameter: A CommandInputParameter object
        result : a list that keeps the fields (used for recursion)

        
    Returns:
        list: List of all possible types (as strings or objects) 
              excluding 'null'
    """
    if isinstance( parameter, str):
        pass
    elif isinstance( parameter, list):
        for t in parameter:
            if t != 'null':
                result.extend( get_fields(t, result))
    # If type_ is a list (union type)
    elif hasattr(parameter, 'type_'):
        result.extend(get_fields( parameter.type_ , result=result))
    
    if hasattr(parameter, 'fields'):
        # For record types, include all field types
        for field in parameter.fields:
            if hasattr(field, 'type_') and field.type_ != 'null':
                result.extend(get_fields(field.type_, result=result))

    return list(set(result))


# to avoid complications of nested inputBindings
def get_input_bindings(data: Any) -> list:
    """
    Get all input bindings from a CommandInputParameter.
    
    Args:
        data: A CommandInputParameter object
        
    Returns:
        list: List of input bindings
    """
    inputBindings=[] # we may have inputbinding in the data or in the type_
    if hasattr(data,'inputBinding') and data.inputBinding:
        logger.debug(f"Shallow inputBinding {data.inputBinding}")
        inputBindings.append(data.inputBinding)
    if hasattr(data.type_,'inputBinding') and data.type_.inputBinding:
        logger.debug(f"type inputBinding {data.type_.inputBinding}")
        inputBindings.append(data.type_.inputBinding)
    if isinstance(data, list):
        logger.debug(f"list of items ")
        for item in data:
            if hasattr(item, 'inputBinding') and item.inputBinding:
                logger.debug(f"Item inputBinding {item.inputBinding}")
                inputBindings.append(item.inputBinding)
            if hasattr(item, 'type_') and hasattr(item.type_, 'inputBinding') and item.type_.inputBinding:
                logger.debug(f"Item type inputBinding {item.type_.inputBinding}")
                inputBindings.append(item.type_.inputBinding)
    if isinstance(data.type_, list):
        logger.debug(f"list of items ")
        for item in data.type_:
            if hasattr(item, 'inputBinding') and item.inputBinding:
                logger.debug(f"Item inputBinding {item.inputBinding}")
                inputBindings.append(item.inputBinding)
            if hasattr(item, 'type_') and hasattr(item.type_, 'inputBinding') and item.type_.inputBinding:
                logger.debug(f"Item type inputBinding {item.type_.inputBinding}")
                inputBindings.append(item.type_.inputBinding)

    if len(inputBindings) == 1:
        return inputBindings[0]  # Return the single input binding directly
    if not inputBindings:
        return None

    # merge into a copy: the bindings belong to the tool and must not change
    merged = copy.copy(inputBindings[0])
    for i, binding in enumerate(inputBindings):
        # go through the list of inputBindings (e.g. from type_ or inputBinding)
        for a in list( binding.attrs ):
            # find all attributes in the inputBinding
            v=getattr(binding, a, None)
            # add the value to the merged binding
            if v:
                setattr(merged, a, v)
    return merged



def get_symbols(data: Any)->tuple:
    """
    Parse the  CWL parameter.
    If the type is enum it returns a set with
    the symbols and the name of the field
    """
    enum_fields = []

    field_name = ''

    # print(f"        Received {json.dumps(save(data), indent=2)}")
    if not hasattr(data, 'type_'):
        return([],None)

    if isinstance(data.type_ , list):
        for e in data.type_:
            (e , f) = get_symbols(e)
            if e:
                enum_fields.extend(e)
            if f:
                field_name=f

    if data.type_ == 'enum':
        enum_fields = data.symbols if hasattr(data, 'symbols') else []
        field_name = data.name if hasattr(data, 'name') else None
            
    elif hasattr(data.type_, 'type_') and data.type_.type_ == 'enum':
        (enum_fields , field_name) = get_symbols(data.type_)
    

    return(set(enum_fields), field_name)