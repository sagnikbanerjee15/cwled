from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
import sys
import logging
import builtins
import argparse
import subprocess
import colorlog
import os
from pathlib import Path
from configuration import Configuration
from MainWindow import MainWindow
import data
import workspaceFolders
import logger
from logger import pinThirdPartyLoggers
from CWLtoolFactory import CWLRunner
from helperFunctions import getResourcePath
import theme
# setup the logging root.
# all subsequent loggers will be children of this.
logger=colorlog.getLogger('main')
# formatter = logging.Formatter('%(levelname)s:[%(asctime)s] %(name)s  -  %(message)s')

def getToolVersion():
    """
    Produce a string that corresponds to the version of the tool.
    The version will follow the format CWL_ed:<github commit or github tag>-<date of update>.

    Returns:
        str: The version string.
    """
    try:
        # Get the latest commit hash
        commit_hash = subprocess.check_output(['git', 'rev-parse','--short', 'HEAD']).strip().decode('utf-8')
        
        # Get the latest commit date
        commit_date = subprocess.check_output(['git', 'log', '-1', '--format=%cd', '--date=short']).strip().decode('utf-8')
        
        # Format the version string
        version_string = f"CWL_ed:{commit_hash}({commit_date})"
        return version_string
    except Exception as e:
        logger.error(f"Error retrieving version information: {e}")
        return "CWL_ed:unknown"
    
def parseArgs():
    parser = argparse.ArgumentParser(description="Edit CWL tools and workflows.")
    
    # Add a positional argument for the input file (for double-clicking)
    parser.add_argument('file_to_open', 
                        nargs='?', 
                        help='Path to the input file to open directly.')

    # Add an argument for the input file
    parser.add_argument('--input-file', 
                        dest='input_file', 
                        type=str,nargs="+", 
                        help='Path(s) to the input file(s). For multiple inputs, separate them with a space. ' + 
                             'These paths should be under a workspace folder.')
    parser.add_argument('--new-workflow', 
                        dest='new_workflow', 
                        type=str, 
                        help='Edit a new Workflow')
    parser.add_argument('--export-image', 
                        dest='export_image', 
                        type=str, 
                        help="Export a plot of the workflow to an image (.svg, .jpg,.png)")
    parser.add_argument('--new-commandline', 
                        dest="new_commandline", 
                        type=str, 
                        help='Name of the new CommandLineTool')
    parser.add_argument('--new-expression', 
                        dest="new_expression", 
                        type=str, 
                        help='Name of the new ExpressionTool')
    parser.add_argument('--workspace', 
                        type=str, 
                        dest="workspace" , 
                        help='Default location for the CWL tools and workflows collection. '+
                             'It is the first workspace folder, followed by the folders added to the workspace. '+
                             'Tools and workflows cannot be accessed outside the workspace folders.')
    parser.add_argument('--version', 
                        action='store_true', 
                        help='Show the version of the tool and exit.')
    parser.add_argument('--reset-config',
                        action='store_true',
                        dest='reset_config',
                        help='Reset user config to defaults before startup.')
    # parser.add_argument('--config', help='Location of the configuration file', type=str, default=None)
    # Parse the arguments
    # Parse the arguments
    args = parser.parse_args()
    return args 


def nameNewDocument(window, window_id, name):
    """
    Give the document that `window.add_window_to_menu` just created the name
    received on the command line. The name is the id of the CWL tool, so it is
    shown in the info tab, the code editor and in the tab and window titles.

    The name is part of the new document rather than an edit of it, so the
    document is not reported as modified (no `*` in the titles).

    Args:
        window: the MainWindow that created the document
        window_id: the id returned by `window.add_window_to_menu`
        name (str): the name (CWL id) of the new document
    """
    document = window.open_windows[window_id]
    document.cwl_tool.id = name
    document.onUpdateCWL()  # push the new id to all the tabs
    document._mark_clean_snapshot()  # the named document is the baseline for changes
    document.updateWindowTitle()


def main():
    builtins.labelWidth = 100
    data.script_directory=Path(__file__).resolve().parent
    data.config_directory=getResourcePath() / 'config' # this is the path within the package with the default configuration files

    logger.info(f"Program runs from: {data.script_directory}")
    logger.info(f"Configuration directory in {data.config_directory}")
    args=parseArgs()

    # Handle positional argument
    if args.file_to_open:
        if args.input_file is None:
            args.input_file = []
        args.input_file.append(args.file_to_open)

    # Check if the version argument is provided
    if args.version:
        print(getToolVersion())
        sys.exit(0)

    # Let's define the app
    app = QApplication(sys.argv)
    # Set application attributes before creating widgets
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    app.setAttribute(Qt.ApplicationAttribute.AA_NativeWindows, False)
    # load the configuration
    logger.info("Loading the configuration")
    conf=Configuration(
        configuration_directory=data.config_directory
    )
    if args.reset_config:
        logger.info("Resetting configuration to defaults from command line argument --reset-config")
        conf.resetConfigurationFile('cwled.yaml')
    conf.loadConfiguration( "cwled.yaml")#,"dataStructures.yaml"] )
    data.configuration=conf.getConfiguration()
    data.configuration_manager=conf  # Store the Configuration object for accessing its methods
    # datatypes=Configuration(configuration_directory=data.config_directory)
    # datatypes.loadConfiguration("dataStructures.yaml")
    data.datatypes=data.configuration.get('data_types') # we get the data types in a separate variable for easier access
    logger.info("Configuration loaded")
    # re-apply the pin now that `logLevel` is available to override it
    pinThirdPartyLoggers()

    # setup the fonts for the application
    # Composer uses the system UI font (San Francisco on macOS); a font family
    # other than the shipped default in the configuration still takes precedence.
    font_family = data.configuration.get('main_window').get('font_family')
    app.setFont(theme.uiFont(font_family, int(data.configuration.get('main_window').get('font_size'))))
    
    # Rabix Composer look and feel (dark theme, Fusion based so it is identical on every OS)
    theme.applyTheme(app)


    # Handle the workspace folders: the folder given on the command line comes
    # first, followed by the folders of the configuration (the single
    # `workspace` setting and the saved `workspace_folders`); without any of
    # them the current directory is used.
    workspace_path = None
    if args.workspace:
        # Convert to Path object for easier handling
        workspace_path = Path(args.workspace)
        # Check if workspace directory exists and create it if not
        if not workspace_path.exists():
            logger.info(f"\u23F3 Creating workspace directory: {workspace_path}")
            try:
                workspace_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"\u2705 Created workspace directory: {workspace_path}")
            except Exception as e:
                logger.error(f"\u274C Failed to create workspace directory: {e}")
    # Store the workspace folders in the data module to make them available application-wide
    workspaceFolders.initialise(workspace_path)
    
    logger.info(f"\u2139 Changing working directory to workspace: {data.workspace_directory}")

    # check the tools 
    try:
        f=CWLRunner()
        logger.info("\u2139 All tools available: ")
    except Exception as e:
        logger.critical(f"\u274C Error initializing CWLRunner: {e}")
        sys.exit(1)
    # Create a Qt widget, which will be our window.
    ei=None
    if args.input_file:
        f=[Path(x).resolve() for x in args.input_file] # this can be a list
        if args.export_image:
            ei=args.export_image
    else:
        f=None
    
    if f is not None:
        for x in f:logger.info(f"\u2139 Working with {str(x)} file")
    os.chdir(str(data.workspace_directory))
    # Create the main window
    window = MainWindow(f,ei)
    window.show()
    
    # Handle command line arguments for creating new workflow/tools
    if args.new_workflow:
        logger.info(f"\u23F3 Creating a new workflow with name: {args.new_workflow}")
        # Create a new workflow child window
        child_window_id = window.add_window_to_menu('Workflow')
        # If a name was provided, set it as the id of the new document
        if args.new_workflow != "":
            nameNewDocument(window, child_window_id, args.new_workflow)
    elif args.new_commandline:
        logger.info(f"\u23F3 Creating a new command line tool with name: {args.new_commandline}")
        # Create a new CommandLineTool child window
        child_window_id = window.add_window_to_menu('CommandLineTool')
        # If a name was provided, set it as the id of the new document
        if args.new_commandline != "":
            nameNewDocument(window, child_window_id, args.new_commandline)
    elif args.new_expression:
        logger.info(f"\u23F3 Creating a new expression tool with name: {args.new_expression}")
        # Create a new ExpressionTool child window
        child_window_id = window.add_window_to_menu('ExpressionTool')
        # If a name was provided, set it as the id of the new document
        if args.new_expression != "":
            nameNewDocument(window, child_window_id, args.new_expression)
    elif not args.input_file:
        # If no specific action was requested, do nothing
        pass

    # Start the event loop.
    app.exec()



if __name__ == "__main__":
    main()