# This file is used to store variables that are shared across all the modules



configuration={} # load and store the configuration file
configuration_manager=None # store the Configuration object to access its methods

# dict that holds various cwl dicts. 
# each CWLtool, ExpressionToll, Workflow
# becomes an item in this 
# eg cwl_dict.get('tool1')
cwl_dict={}

# Store the workspace directory that will be used throughout the application:
# the current workspace folder (default location for file dialogs and new files)
workspace_directory = ""

# All the folders of the workspace (roots of the Workspace panel), see workspaceFolders.py
workspace_folders = []

# Store data type information
datatypes={}