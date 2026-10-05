import os
from pathlib import Path
import sys

def getResourcePath() -> Path:
    """
    Get the path to the resources directory.
    Handles both development (source) and frozen (py2app/PyInstaller) environments.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller onefile
            return Path(sys._MEIPASS) / 'resources'
        else:
            # PyInstaller onedir
            return Path(sys.executable).parent / 'resources'
    elif 'RESOURCEPATH' in os.environ:
        # py2app
        return Path(os.environ['RESOURCEPATH']) / 'resources'
    else:
        # Running from source
        # Assuming this file is in cwled/helperFunctions.py
        # Resources are in ../resources relative to cwled package root
        # cwled package root is parent of this file
        return Path(__file__).resolve().parent.parent / 'resources'

from typing import Any
from urllib.parse import unquote, urlparse
from PyQt6.QtWidgets import QWidget


def uriToPath(text: str) -> str:
    """
    The path that a ``file:`` URI names, with its %XX undone (``Application%20Support`` is ``Application Support``):
    ``urlparse(uri).path`` leaves them, and a path built from it does not exist when the folder has a space in its name.
    The path of a URI with another scheme is as ``urlparse`` gives it, and text without a scheme (a plain path) is returned as it is.
    """
    if not isinstance(text, str):
        return text
    parsed = urlparse(text)
    if parsed.scheme == 'file':
        return unquote(parsed.path)
    return parsed.path if parsed.scheme else text

def addArrayItem(array:list, value:Any, array_index:int):
    '''
    add an item to an arary at position = array_index
    If the index is larger than the array it will add as many None elements as necessary
    '''
    if len(array) <= array_index:
        array.extend([None] * (array_index - len(array) + 1))
    array[array_index]=value    
    
def traverseCWLversion(current_object: QWidget) -> str:
    """
    Recursively finds the cwl_version from a parent object.

    The function traverses up the parent hierarchy of a QWidget.
    - If a parent has a `cwl_version` attribute that is not None, it returns that version.
    - The recursion stops when a `cwl_version` is found or an object of class 'ChildWindow' is reached.
    - If a 'ChildWindow' is reached and it does not have a defined `cwl_version`, an Exception is raised.
    - If the top of the hierarchy is reached without finding a 'ChildWindow' or a `cwl_version`, an Exception is raised.
    """
    parent = current_object.parent()
    if parent is None:
        raise Exception("Reached top of hierarchy without finding cwl_version or ChildWindow.")
    if type(parent).__name__== 'ChildWindow':
        # cwl_version check has already failed for this ChildWindow object
        raise Exception("Reached ChildWindow but cwl_version is not defined.")
    if hasattr(parent, 'cwl_version') and getattr(parent, 'cwl_version') is not None:
        return getattr(parent, 'cwl_version')

    

    return traverseCWLversion(parent)