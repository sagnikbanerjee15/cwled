
import os
import csv
def loadEDAMformat(filename):
    if not os.path.isfile(filename) or not os.access(filename, os.R_OK):
        raise FileNotFoundError(f"File '{filename}' does not exist or is not accessible.")
    result = {}
    with open(filename, encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            semantic_type = row.get('Class ID', '').strip().split('/')[-1]
            if semantic_type.startswith('format_'):
                result[semantic_type] = {
                    'Preferred Label': row.get('Preferred Label', '').strip(),
                    'Definitions': row.get('Definitions', '').strip(),
                    'File extension': row.get('File extension', '').strip()
                }
    return result
"""
Utility module for handling CWL utilities.

This module provides functions for dynamically loading the appropriate CWL module
based on version requirements.
"""

import logging
from cwl_utils.parser import save
import re
from typing import Union, Any
import inspect

# here we list all possible datatypes that we can have in CWL.
CWLType = [
    'null',  # no value
    'boolean',  # a binary value
    'int',  # 32-bit signed integer
    'long',  # 64-bit signed integer
    'float',  # single precision (32-bit) IEEE 754 floating-point number
    'double',  # double precision (64-bit) IEEE 754 floating-point number
    'string',  # Unicode character sequence
    'File',  # A File object
    'Directory',  # A Directory Object
    'record'  # a record
]

CWLTypeOutput = CWLType.append('stdout')




def is_cwl_object(obj):
    """
    Check if the given object is a CWL-related object.

    Args:
        obj: Any Python object to check.

    Returns:
        bool: True if the object's class module path starts with 'cwl_utils.parser.cwl_v', False otherwise.
    """
    module = getattr(obj.__class__, "__module__", "")
    return module.startswith("cwl_utils.parser.cwl_v")


def get_cwl_version(cwl_tool: Union[Any, None]) -> Union[str, None]:
    """
    Extract the CWL version from a CWL tool object.

    If the object is None, returns None. If the object is not a CWL object, returns None.
    Otherwise, inspects the object's class module path to determine the CWL version.
    If the version is not recognized, raises a ValueError and includes the full call stack.

    Args:
        cwl_tool (Any or None): The CWL tool object to inspect.

    Returns:
        str or None: The CWL version string ('v1.0', 'v1.1', 'v1.2'), or None if not found or on error.
    """
    if cwl_tool is None:
        return None  # Default to latest version if no tool provided
    if not is_cwl_object(cwl_tool):
        logging.getLogger(__name__).warning("Cannot extract CWL version from non CWL object")
        return None
    try:
        cwl_version = cwl_tool.__class__.__module__
        if 'cwl_v1_2' in cwl_version:
            return 'v1.2'
        elif 'cwl_v1_1' in cwl_version:
            return 'v1.1'
        elif 'cwl_v1_0' in cwl_version:
            return 'v1.0'
        elif cwl_version == 'builtins':
            return None
        else:
            # Get the full stack of caller functions
            stack = inspect.stack()
            stack_info = []
            for frame in stack[1:]:  # skip the current frame
                func_name = frame.function
                caller_self = frame.frame.f_locals.get('self', None)
                if caller_self:
                    class_name = caller_self.__class__.__name__
                    stack_info.append(f"{class_name}.{func_name}")
                else:
                    stack_info.append(func_name)
            caller_stack = " -> ".join(stack_info)
            raise ValueError(
                f"Unsupported CWL version in tool: {cwl_version}. Call stack: {caller_stack}"
            )
    except Exception as e:
        logging.getLogger(__name__).error(f"Error extracting CWL version: {e}")
        return None  # Default to latest version on error


def get_cwl_module(cwl_version: Union[str, Any]):
    """
    Dynamically import the appropriate CWL module based on version.

    If a string is provided, it should be a CWL version (e.g., '1.0', '1.1', '1.2', 'v1.2').
    The string can contain the 'v' prefix or not. If a CWL object is passed, its version is extracted.
    If the version is not recognized, defaults to the latest version and logs a warning.

    Args:
        cwl_version (str or Any): The CWL version string or CWL object.

    Returns:
        module: The appropriate cwl_utils parser module for the specified version.
    """
    # if we don't provide the version as a string
    if not isinstance(cwl_version, str):
        cwl_version = get_cwl_version(cwl_version)
    cwl_version = str(cwl_version).replace('v', '')
    if cwl_version == '1.0':
        from cwl_utils.parser import cwl_v1_0 as cwl_module
    elif cwl_version == '1.1':
        from cwl_utils.parser import cwl_v1_1 as cwl_module
    elif cwl_version == '1.2':
        from cwl_utils.parser import cwl_v1_2 as cwl_module
    else:
        # Default to latest version
        from cwl_utils.parser import cwl_v1_2 as cwl_module
        logging.getLogger(__name__).warning(
            f"Unrecognized CWL version '{cwl_version}', defaulting to v1.2"
        )
    return cwl_module



def format_parameter_type(cwl_type: Any) -> str:
    """
    Short display form of a CWL parameter type, as shown in Rabix Composer's
    lists: ``File``, ``Array<File>``, ``string?`` (optional), and unions such as
    ``File, Array<File>``.
    """
    def name(t: Any) -> str:
        if isinstance(t, str):
            return t.split('#')[-1].split('/')[-1]
        t_type = getattr(t, 'type_', None)
        if t_type == 'array':
            return f"Array<{name(getattr(t, 'items', None))}>"
        if t_type == 'record':
            return 'record'
        if t_type == 'enum':
            return 'enum'
        if isinstance(t, list):
            return ', '.join(name(x) for x in t)
        return 'n/a' if t is None else str(t_type or t)

    if isinstance(cwl_type, list):
        nullable = 'null' in cwl_type
        names = [name(t) for t in cwl_type if t != 'null']
        return ', '.join(f"{n}?" if nullable else n for n in names) or 'null'
    return name(cwl_type)


def format_input_binding(input_binding: Any) -> str:
    """Rabix Composer input binding summary: the prefix, else ``pos: N``, else ``unbound``."""
    if not input_binding:
        return "unbound"
    if getattr(input_binding, 'prefix', None):
        return input_binding.prefix
    if getattr(input_binding, 'position', None):
        return f"pos: {input_binding.position}"
    return "pos: 0"
