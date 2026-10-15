"""
The words that the autocompletion of the Code tab offers: the names of the CWL v1.2 classes and of
the fields of the documents (tools, workflows, steps, parameters, bindings and requirements).

A data module only: the list is handed to QsciAPIs by liveValidation.py.
"""

CLASSES = (
    'CommandLineTool', 'ExpressionTool', 'Workflow', 'WorkflowStep', 'Operation',
    'InputParameter', 'OutputParameter', 'CommandInputParameter', 'CommandOutputParameter',
    'WorkflowOutputParameter', 'CommandLineBinding', 'CommandOutputBinding',
    'CommandInputRecordSchema', 'CommandInputEnumSchema', 'CommandInputArraySchema',
    'CommandOutputRecordSchema', 'CommandOutputEnumSchema', 'CommandOutputArraySchema',
    'SecondaryFileSchema', 'File', 'Directory', 'Dirent', 'EnvironmentDef', 'SoftwarePackage',
    'DockerRequirement', 'SoftwareRequirement', 'InitialWorkDirRequirement', 'EnvVarRequirement',
    'ResourceRequirement', 'InlineJavascriptRequirement', 'ShellCommandRequirement',
    'SchemaDefRequirement', 'LoadListingRequirement', 'WorkReuse', 'NetworkAccess',
    'InplaceUpdateRequirement', 'ToolTimeLimit', 'ScatterFeatureRequirement',
    'SubworkflowFeatureRequirement', 'MultipleInputFeatureRequirement',
    'StepInputExpressionRequirement',
)

FIELDS = (
    # the document
    'cwlVersion', 'class', 'id', 'label', 'doc', 'intent', 'inputs', 'outputs', 'requirements', 'hints',
    'steps', 'baseCommand', 'arguments', 'stdin', 'stdout', 'stderr', 'successCodes',
    'temporaryFailCodes', 'permanentFailCodes', 'expression', 'expressionLib', '$namespaces',
    '$schemas', '$graph', '$import', '$include', '$mixin',
    # parameters
    'type', 'default', 'name', 'inputBinding', 'outputBinding', 'secondaryFiles', 'format',
    'streamable', 'loadContents', 'loadListing', 'outputSource', 'items', 'fields', 'symbols',
    # bindings
    'position', 'prefix', 'separate', 'itemSeparator', 'valueFrom', 'shellQuote',
    'glob', 'outputEval', 'pattern', 'required',
    # workflow steps
    'run', 'in', 'out', 'scatter', 'scatterMethod', 'when', 'source', 'linkMerge', 'pickValue',
    # file and directory values
    'location', 'path', 'basename', 'dirname', 'nameroot', 'nameext', 'checksum', 'size',
    'contents', 'listing', 'entry', 'entryname', 'writable',
    # requirements and hints
    'dockerPull', 'dockerLoad', 'dockerFile', 'dockerImport', 'dockerImageId', 'dockerOutputDirectory',
    'packages', 'package', 'version', 'specs', 'coresMin', 'coresMax', 'ramMin', 'ramMax',
    'tmpdirMin', 'tmpdirMax', 'outdirMin', 'outdirMax', 'envDef', 'envName', 'envValue', 'types',
    'timelimit', 'enableReuse', 'networkAccess', 'inplaceUpdate',
)

# The words offered, once each and in alphabetical order
CWL_WORDS = tuple(sorted(set(CLASSES) | set(FIELDS)))


def completionWords() -> list[str]:
    """The words of the autocompletion, unique and sorted."""
    return list(CWL_WORDS)
