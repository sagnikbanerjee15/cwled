# CWLed Technical Architecture and Flow

## Table of Contents
- [Overview](#overview)
- [Core Architecture](#core-architecture)
- [Main Application Classes](#main-application-classes)
- [Editor Tab Classes](#editor-tab-classes)
- [Widget Hierarchy](#widget-hierarchy)
- [Signal Flow Architecture](#signal-flow-architecture)
- [Tab Synchronization Mechanism](#tab-synchronization-mechanism)
- [Data Flow Patterns](#data-flow-patterns)
- [Dialog System](#dialog-system)
- [Graph Visualization](#graph-visualization)

## Overview

CWLed is a PyQt6-based application for editing Common Workflow Language (CWL) documents. The architecture follows a hierarchical parent-child window structure with specialized tabs for different editing aspects. The application uses Qt's signal-slot mechanism extensively for communication between components and maintains a shared CWL data model that synchronizes across all views.

## Core Architecture

### Application Hierarchy

```
QApplication (main.py)
└── MainWindow
    ├── ChildWindow #1 (CommandLineTool)
    │   ├── TabInfoWindow
    │   ├── TabToolEditor
    │   ├── TabCommandLine
    │   └── TabCodeEditor
    ├── ChildWindow #2 (Workflow)
    │   ├── TabInfoWindow
    │   ├── TabWorkflowEditor (with CWLGraph)
    │   ├── TabSummary
    │   └── TabCodeEditor
    └── WorkspaceContents
```

### Key Design Principles

1. **Shared Data Model**: Each `ChildWindow` maintains a single `cwl_tool` object that is shared by reference across all its tabs
2. **Signal-Based Communication**: Components communicate through Qt signals, allowing loose coupling
3. **Two-Way Synchronization**: Changes in any tab (visual or code) immediately propagate to all other tabs
4. **Type-Specific Views**: Different CWL types (CommandLineTool, ExpressionTool, Workflow) have different tab configurations

## Main Application Classes

### MainWindow

**Location**: `MainWindow.py`

**Purpose**: Application entry point and container for all child windows

**Key Responsibilities**:
- Creates and manages multiple `ChildWindow` instances
- Provides menu system (File, Tools, Window)
- Manages workspace directory
- Handles global actions (validate, pack workflow, make template)
- Maintains window registry for switching between open documents

**Signals Emitted**:
- `openWindowFromFile(str)`: Request to open a file in a new window

**Signals Received**:
- `windowClosed(int)`: Notification when a child window closes
- `updateMenuSignal(int, str)`: Request to update window menu entry

**Key Methods**:
- `onCreateWindowFromFile(input_file)`: Creates a new ChildWindow for a given file
- `onNewCommandLineTool()`: Creates new CommandLineTool window
- `onNewWorkflow()`: Creates new Workflow window
- `onMenuValidate()`: Triggers validation of active window's CWL
- `setMenu()`: Sets up application menu structure

### ChildWindow

**Location**: `ChildWindow.py`

**Purpose**: Container for a single CWL document editor with multiple tabs

**Key Responsibilities**:
- Manages the lifecycle of a single CWL document
- Contains tab widgets for different editing views
- Handles file I/O (open, save, save as)
- Coordinates updates between tabs
- Manages CWL version and file format
- Provides status bar with file information

**Signals Emitted**:
- `menuValidate()`: Request validation
- `menuUpgradeVersion(str)`: Request version upgrade
- `menuPackWorkflow(str)`: Request workflow packing
- `menuRestructureWorkflow(str)`: Request workflow restructuring
- `menuMakeTemplate()`: Request template generation
- `menuReloadFile()`: Request file reload
- `windowClosed(int)`: Notification on close with window ID
- `updateMenuSignal(int, str)`: Update window menu with status

**Signals Received**:
- Parent connects to these to handle menu actions

**Shared Data**:
- `self.cwl_tool`: The CWL object (CommandLineTool, ExpressionTool, or Workflow) shared by all tabs
- `self.file_path`: Current file path
- `self.file_format`: 'JSON' or 'YAML'
- `self.track_version`: Whether to track versions with Git

**Key Methods**:
- `setupTypeSpecificTabs()`: Creates tabs based on CWL type
- `onUpdateCWL(message)`: Central method called when any tab modifies CWL data
- `loadCWL(file_path)`: Loads CWL from file and populates all tabs
- `saveCWL(file_path)`: Saves current CWL to file
- `switchFormat(new_format)`: Changes between JSON/YAML formats

**Tab Management Flow**:
1. User creates/opens a CWL document → `ChildWindow` created
2. `setupTypeSpecificTabs()` determines CWL type and creates appropriate tabs
3. Each tab receives reference to `self.cwl_tool`
4. Tabs connect their `codeUpdated` signals to parent's `onUpdateCWL()`
5. Tab changes trigger `onUpdateCWL()` which calls `getCWL()` on the losing-focus tab

## Editor Tab Classes

### TabInfoWindow

**Location**: `TabInfoWindow.py`

**Purpose**: Metadata and documentation editor

**Key Responsibilities**:
- Edit ID, label, doc, cwlVersion
- Manage namespaces and extension fields
- Git version tracking toggle
- AI-powered documentation generation

**Signals Emitted**:
- `codeUpdated(str)`: When metadata changes

**Key Methods**:
- `setCWLTool(cwl_tool)`: Receives and stores reference to shared CWL object
- `populateFromCWL()`: Populates UI fields from CWL object
- `getCWL()`: Updates CWL object from UI fields

**Data Flow**:
```
User edits field → Signal emitted → ChildWindow.onUpdateCWL() → getCWL() → Updates shared cwl_tool
```

### TabToolEditor (App Tab)

**Location**: `TabToolEditor.py`

**Purpose**: Visual editor for CommandLineTool and ExpressionTool

**Key Responsibilities**:
- Edit baseCommand, arguments, inputs, outputs
- Manage requirements (Docker, Resource, InitialWorkDir, etc.)
- Provide form-based interface for CWL constructs

**Signals Emitted**:
- `codeUpdated(str)`: When tool definition changes

**Widget Groups**:
- `QBaseCommandGroupWidget`: Manages list of base commands
- `QArgumentsGroupWidget`: Manages arguments
- `QInputsGroupWidget`: Manages inputs with InputDialog
- `QOutputsGroupWidget`: Manages outputs with OutputDialog
- Requirement widgets (Docker, Resource, EnvVar, etc.)

**Key Methods**:
- `setCWLTool(cwl_tool)`: Stores reference to CWL object
- `populateFromCWL()`: Populates all widget groups from CWL
- `getCWL()`: Collects data from all widgets and updates CWL object

**Update Pattern**:
```
Widget changed → Widget.editingFinished signal → GroupWidget catches → 
GroupWidget.editingFinished → ToolEditor.onEditingFinished → codeUpdated signal
```

### TabWorkflowEditor

**Location**: `TabWorkflowEditor.py`

**Purpose**: Visual graph editor for Workflows

**Key Responsibilities**:
- Display workflow as interactive graph
- Add/remove/configure steps
- Create connections between steps
- Manage workflow inputs/outputs through graph nodes
- Export workflow visualizations

**Signals Emitted**:
- `codeUpdated(str)`: When workflow structure changes

**Child Components**:
- `CWLGraph` (NetworkGraph.py): The graph visualization widget
- `StepNode`, `InputNode`, `OutputNode` (GraphNodes.py): Node types
- `CWLNodeItem`, `CWLPortItem`, `GraphControls` (GraphItems.py): Rabix Composer (cwl-svg) drawing of nodes, ports and edges, selection fading, and the canvas buttons (delete, zoom, fit, auto-arrange, export image)
- The graph canvas fills the editor; CWL files dropped on it become steps (`_canvasDrop` in `TabWorkflowEditor.py`). The former toolbar (Add Step, Duplicate Step, legend, drop zone) was removed; `onAddStep` is used by the canvas drop and `onDuplicateStep` has no interface at the moment

**Key Methods**:
- `setCWLWorkflow(cwl_workflow)`: Stores reference to Workflow object
- `populateFromCWL(file_location)`: Creates graph from CWL
- `getCWL()`: Extracts workflow structure from graph and updates CWL object
- `onGraphChanged()`: Called when graph is modified, emits codeUpdated
- `onAddStep()`: Opens file dialog to add new step

**Graph Update Flow**:
```
User modifies graph → CWLGraph.editingFinished signal → 
WorkflowEditor.onGraphChanged() → Emits codeUpdated → 
ChildWindow.onUpdateCWL() → getCWL() updates cwl_workflow
```

### TabSummary

**Location**: `TabSummary.py`

**Purpose**: Read-only summary view of workflow inputs/outputs

**Key Responsibilities**:
- Display workflow description
- Show inputs table (ID, Label, Type, Required, Description)
- Show outputs table (ID, Label, Type, Description)
- Provide quick overview of workflow interface

**No Signal Emission**: This is a read-only view that only receives updates

**Key Methods**:
- `setCWLWorkflow(cwl_workflow)`: Stores reference to Workflow
- `populate()`: Updates tables from workflow definition

**Update Trigger**: Refreshed when tab gains focus via `ChildWindow.onUpdateCWL()`

### TabCodeEditor

**Location**: `TabCodeEditor.py`

**Purpose**: Direct CWL code editor with syntax highlighting

**Key Responsibilities**:
- Display CWL as YAML or JSON with syntax highlighting
- Allow direct code editing
- Parse edited code and update CWL object
- Format and prettify code

**Signals Emitted**:
- `codeUpdated(str)`: When code is manually edited and validated

**Key Methods**:
- `setCWL(cwl_tool)`: Stores reference to CWL object
- `populateFromCWL()`: Converts CWL object to text and displays
- `getCWL()`: Parses text, validates, and updates CWL object
- `onFormat()`: Formats and prettifies displayed code

**Bidirectional Sync**:
```
Visual Tab Change → ChildWindow.onUpdateCWL() → getCWL() on leaving tab → 
Updates cwl_tool → Code tab gains focus → populateFromCWL() → Display updated code

Code Edit → User saves → getCWL() parses → Updates cwl_tool → 
emits codeUpdated → Other tabs refresh on next focus
```

### TabCommandLine

**Location**: `TabCommandLine.py`

**Purpose**: Preview of the command line, built from a sample job like Rabix Composer's

**Key Responsibilities**:
- Give every input a sample value (`JavascriptEditor.mockValue`, cached per input and type) or its test value (`testJob.py`)
- Build the parts in execution order (cwl-ts CommandLinePrepare / CommandLineParsers rules; record fields and enum type bindings as cwltool)
- Evaluate all expressions of the preview in one background `JSEvaluation` (QJSEngine, 3 s timeout) and render the parts coloured by kind
- On hover, outline a part and show where it comes from; on click, `TabToolEditor.inspectCommandLinePart(loc)` opens it in the inspector

**No Signal Emission**: Read-only preview; refreshes on `testJobs().changed`

**Key Methods**:
- `setCWLTool(cwl_tool)` / `populateFromCWL()`: Rebuild the preview
- `_sampleJob(tool)`: Sample and test values of the inputs
- `_commandLineParts(tool, job)`: Parts (literal text and expression results)

### testJob

**Location**: `testJob.py`

**Purpose**: Test values of tool inputs (Composer "Test Value"), kept per document file in CWLed's user data folder (not in the CWL), used by the command line preview, the Expression Editor and inline expression validation.

## Widget Hierarchy

### Base Widget Classes

#### QCWLedWidget

**Location**: `widgets/QCWLedWidget.py`

**Purpose**: Base class for all CWL editing widgets

**Provides**:
- `editingFinished` signal for change notification
- `cwl_tool` attribute for CWL data
- `cwl_version` attribute for CWL version
- Standard lifecycle methods: `setCWL()`, `getCWL()`, `getData()`, `populateFromCWL()`, `clear()`

**Pattern**:
```python
class CustomWidget(QCWLedWidget):
    def initUI(self):
        # Create UI components
        # Connect internal signals to self._emit_editing_finished()
    
    def getData(self):
        # Return CWL object representation
        return cwl_object
    
    def populateFromCWL(self, cwl_data):
        # Set UI from CWL data
```

#### QCWLedGroupWidget

**Location**: `widgets/QCWLedGroupWidget.py`

**Purpose**: Base class for managing lists of widgets (arguments, inputs, outputs, etc.)

**Features**:
- Adds "Add" button in header
- Each child widget gets "Remove" button
- Manages dynamic list of widgets
- Aggregates data from all child widgets

**Usage Pattern**:
```python
class QInputsGroupWidget(QCWLedGroupWidget):
    def __init__(self, parent, cwl_tool, cwl_version):
        super().__init__(
            parent=parent,
            cwl_tool=cwl_tool,
            cwl_version=cwl_version,
            widget_class=QInputWidget,
            label="Inputs"
        )
```

**Methods**:
- `addWidget(cwl_data)`: Adds new child widget with data
- `removeWidget(widget)`: Removes child widget
- `getData()`: Returns list of data from all children
- `populateFromCWL(cwl_data)`: Creates widgets for each item in list

### Specialized Widget Groups

- **QArgumentsGroupWidget**: Manages CommandLineTool arguments
- **QInputsGroupWidget**: Manages tool/workflow inputs
- **QOutputsGroupWidget**: Manages tool/workflow outputs
- **QBaseCommandGroupWidget**: Manages base command components
- **QSecondaryFilesGroupWidget**: Manages File input secondary files
- **QEnvVarGroupWidget**: Manages environment variables for EnvVarRequirement
- **QInitialWorkDirGroupWidget**: Manages InitialWorkDirRequirement entries

## Signal Flow Architecture

### Primary Signal Chains

#### 1. User Edits in Visual Editor (e.g., App Tab)

```
User types in QLineEdit
    ↓
QLineEdit.editingFinished signal
    ↓
Widget._emit_editing_finished()
    ↓
QCWLedWidget.editingFinished signal
    ↓
GroupWidget._emit_editing_finished()
    ↓
GroupWidget.editingFinished signal
    ↓
TabToolEditor.onEditingFinished() [or similar handler]
    ↓
TabToolEditor.codeUpdated signal emitted
    ↓
ChildWindow.onUpdateCWL(message)
    ↓
[Tab switch or save triggers getCWL() on source tab]
    ↓
Shared cwl_tool object updated
    ↓
[When target tab gains focus, populateFromCWL() called]
    ↓
All tabs now show updated data
```

#### 2. User Edits in Code Editor

```
User types in code editor
    ↓
Text modified (stored but not immediately processed)
    ↓
User switches tab OR explicitly saves
    ↓
TabCodeEditor.getCWL() called by ChildWindow.onUpdateCWL()
    ↓
Code parsed using cwl-utils
    ↓
Validation occurs
    ↓
If valid: shared cwl_tool object updated
    ↓
TabCodeEditor.codeUpdated signal emitted
    ↓
Other tabs refresh on next focus (populateFromCWL())
```

#### 3. User Edits Workflow Graph

```
User creates connection in graph
    ↓
CWLGraph.editingFinished signal
    ↓
TabWorkflowEditor.onGraphChanged()
    ↓
TabWorkflowEditor.codeUpdated signal
    ↓
ChildWindow.onUpdateCWL(message)
    ↓
[On tab switch or save]
    ↓
TabWorkflowEditor.getCWL() extracts workflow from graph
    ↓
Updates shared cwl_workflow object
    ↓
Code tab shows updated CWL when focused
```

#### 4. Menu Action Flow

```
User selects menu item in MainWindow
    ↓
MainWindow.onMenuValidate() [or other menu handler]
    ↓
MainWindow.active_window.menuValidate.emit()
    ↓
ChildWindow receives signal
    ↓
ChildWindow.onMenuValidate()
    ↓
Calls CWLRunner to validate file
    ↓
Results shown in QErrorMessage dialog
```

### Tab Switch Signal Flow

```
User clicks different tab
    ↓
QTabWidget.currentChanged(index) signal
    ↓
ChildWindow.onUpdateCWL(None) slot called
    ↓
Identifies previously active tab
    ↓
Calls previous_tab.getCWL() to save changes
    ↓
Updates shared cwl_tool object
    ↓
New tab becomes active
    ↓
[Future: Could call new_tab.populateFromCWL() here]
    ↓
Tab's showEvent or focusInEvent triggers populateFromCWL()
```

## Tab Synchronization Mechanism

### The Central Update Method: `ChildWindow.onUpdateCWL()`

This is the **orchestrator** of all synchronization. Every tab change, code edit, or visual modification flows through this method.

**Location**: `ChildWindow.py`

**Triggers**:
1. Tab changed: `self.tabs.currentChanged` signal
2. Code updated in any tab: `tab.codeUpdated` signal
3. Explicit save: User presses Ctrl+S

**Logic Flow**:

```python
def onUpdateCWL(self, message):
    # 1. Identify current and previous tabs
    current_tab = self.tabs.currentWidget()
    
    # 2. If there was a previous tab, get its data
    if hasattr(self, '_last_active_tab') and self._last_active_tab:
        if hasattr(self._last_active_tab, 'getCWL'):
            # This updates the shared cwl_tool
            self._last_active_tab.getCWL()
    
    # 3. Remember this tab for next time
    self._last_active_tab = current_tab
    
    # 4. Update status bar
    self.updateStatusBar()
    
    # 5. Update window menu entry
    self.updateMenuSignal.emit(self.window_id, self.getWindowTitle())
```

### getData() vs getCWL() Pattern

**getData()**: Used by widgets to return their data as CWL objects
- Called by: Parent widgets collecting child data
- Returns: CWL-utils object or primitive

**getCWL()**: Used by tabs to update the shared CWL object
- Called by: `ChildWindow.onUpdateCWL()` during tab switches
- Returns: Reference to the shared CWL object (usually doesn't create new)
- **Side Effect**: Modifies `self.cwl_tool` in place

### Lazy vs Immediate Updates

**Visual Editors (App, Workflow tabs)**:
- Changes tracked by signals but stored in UI widgets
- Actual CWL object updated only on:
  - Tab switch (getCWL() called)
  - Explicit save
  - Validation requested

**Code Editor**:
- Text changes stored in editor
- CWL object updated only when:
  - Tab is switched away from
  - User manually triggers parse

**Benefits**:
- Performance: Don't re-parse/rebuild on every keystroke
- User Experience: No interruption during editing
- Validation: Can catch errors on tab switch before save

### Synchronization Scenarios

#### Scenario 1: Edit in App Tab, View in Code Tab

1. User types in "Base Command" field in App tab
2. `QLineEdit.editingFinished` → cascades to `TabToolEditor.codeUpdated`
3. `ChildWindow.onUpdateCWL()` called, but getCWL() **not yet called** (same tab still active)
4. User clicks "Code" tab
5. Tab switch triggers `onUpdateCWL()` again
6. Now calls `TabToolEditor.getCWL()` to save App tab changes to `cwl_tool`
7. Code tab becomes active, eventually calls `populateFromCWL()`
8. Code tab displays updated CWL reflecting the base command change

#### Scenario 2: Edit in Code Tab, View in App Tab

1. User types CWL code in Code tab
2. Text stored in editor, `cwl_tool` not yet updated
3. User clicks "App" tab
4. Tab switch triggers `onUpdateCWL()`
5. Calls `TabCodeEditor.getCWL()` which:
   - Parses text using cwl-utils
   - Validates structure
   - Updates `cwl_tool` object with parsed result
6. If parse error: Shows error dialog, prevents tab switch
7. If valid: App tab becomes active
8. App tab's `populateFromCWL()` eventually called
9. App tab displays the updated tool definition

#### Scenario 3: Edit Workflow Graph, Save File

1. User adds step in workflow graph
2. Graph emits `editingFinished` → `TabWorkflowEditor.codeUpdated`
3. `ChildWindow.onUpdateCWL()` called (signals change)
4. User presses Ctrl+S to save
5. Save action triggers `onUpdateCWL()` one more time
6. Calls `TabWorkflowEditor.getCWL()` which extracts workflow from graph nodes
7. Updates `cwl_workflow` object
8. `saveCWL()` serializes `cwl_workflow` to file using cwl-utils

## Data Flow Patterns

### Initialization Flow

```
Application Start
    ↓
MainWindow.__init__()
    ↓
User clicks "Create CommandLineTool"
    ↓
MainWindow.onNewCommandLineTool()
    ↓
Creates empty CommandLineTool using cwl-utils
    ↓
new_child = ChildWindow(cwl_tool=new_tool)
    ↓
ChildWindow.setupTypeSpecificTabs()
    ↓
Creates TabInfoWindow(cwl_tool=self.cwl_tool) [reference passed]
Creates TabToolEditor(cwl_tool=self.cwl_tool) [same reference]
Creates TabCodeEditor(cwl_tool=self.cwl_tool) [same reference]
    ↓
Each tab calls populateFromCWL() in __init__
    ↓
Tabs display default/empty state
```

### File Loading Flow

```
User: File → Open
    ↓
ChildWindow.loadCWL(file_path)
    ↓
CWLparser.getCWL() parses file → returns CWL object
    ↓
self.cwl_tool = parsed_object
    ↓
Calls tab.setCWLTool(self.cwl_tool) for each tab [updates reference]
    ↓
Calls tab.populateFromCWL() for each tab
    ↓
All tabs now display loaded document
```

### File Saving Flow

```
User: File → Save (or Ctrl+S)
    ↓
ChildWindow.onMenuSaveFile()
    ↓
Calls onUpdateCWL() to ensure current tab saved to cwl_tool
    ↓
current_tab.getCWL() updates cwl_tool
    ↓
ChildWindow.saveCWL(file_path)
    ↓
Uses cwl-utils save() to serialize cwl_tool
    ↓
Writes to file in JSON or YAML format
    ↓
If track_version=True: Git commit and tag
```

## Dialog System

### BaseDialog

**Location**: `BaseDialog.py`

**Purpose**: Base class for all modal dialogs with consistent positioning

**Features**:
- Positions at top-right of screen where main window is located
- Multi-monitor support: Opens on same screen as MainWindow
- Auto-sizing: StepDialog gets 100px extra width
- Focus management: Calls `activateWindow()` and `raise_()` to stay on top

**Subclasses**:
- ArgumentDialog
- InputDialog
- OutputDialog
- StepDialog

### ArgumentDialog

**Location**: `DialogArgument.py`

**Purpose**: Edit CommandLineTool argument

**Fields**:
- Position (int)
- Prefix (string)
- Value/valueFrom (string or JavaScript expression)
- separate (boolean)
- shellQuote (boolean)

**Return**: CommandLineBinding or ArgumentCommandLineBinding object

### InputDialog

**Location**: `DialogInput.py`

**Purpose**: Context-dependent input editing

**For CommandLineTool**:
- Define input from scratch
- Fields: ID, Label, Type, inputBinding (prefix, position, etc.), Default Value, secondaryFiles

**For Workflow Step**:
- Connect step input to source
- Fields: ID (read-only), Source (dropdown of available outputs), Default Value
- No inputBinding section (that's in the tool definition)

**Return**: CommandInputParameter or WorkflowStepInput object

### OutputDialog

**Location**: `DialogOutput.py`

**Purpose**: Context-dependent output editing

**For CommandLineTool**:
- Define how to capture output
- Fields: ID, Label, Type, outputBinding (glob pattern), secondaryFiles

**For Workflow**:
- Connect workflow output to step output
- Fields: ID, Label, Type, Source (dropdown), pickValue, linkMerge
- No outputBinding (that's in the tool)

**Special Workflow Fields**:
- **pickValue**: How to select from multiple values (first_non_null, the_only_non_null, all_non_null)
- **linkMerge**: How to merge from multiple sources (merge_nested, merge_flattened)

**Return**: CommandOutputParameter or WorkflowOutputParameter object

### StepInspector

**Location**: `StepInspector.py`

**Purpose**: Configure a workflow step in a side panel next to the canvas (Composer
`ct-workflow-step-inspector`). `WorkflowEditor` puts it in a splitter with the `CWLGraph`
and sets `CWLGraph.inspect_step`, so double-clicking a step opens it there.

**Tabs**:
- App Info: class, CWL version, `sbg:` revision/toolkit/author, source (run file or Embedded), description
- Inputs: `Files` / `App parameters` / `Conditional inputs` groups; per input the port
  options (Show/Hide for optional File/Directory, Default/Exposed/Port for the others, applied
  by `CWLGraph.setPortOption`), a typed default value editor (`ValueEntry`), Link Merge Method,
  Pick Value (v1.2, several sources) and the connections
- Step: ID (validated, renamed through `CWLGraph.nodeEdited`), Label, Scatter Method,
  Scatter, When (v1.2), Description, Set Hints (`HintsDialog`)

**Port visibility** (`CWLGraph.refreshPortVisibility`): a step input port is drawn when its
input is a required File/Directory, when it is connected, or when it was shown from the
inspector (`CWLGraph.shown_ports`). Workflow inputs with `sbg:exposed: true` are not drawn.

**Signal Flow**:
```
User double-clicks a step node
    ↓
CWLGraph.onNodeDoubleClicked → StepInspector.inspect(node)
    ↓
User edits a field (text edits are applied after a short delay)
    ↓
The inspector updates node.cwl_step in place (or CWLGraph.setPortOption / nodeEdited)
    ↓
CWLGraph emits editingFinished → WorkflowEditor.onGraphChanged
    ↓
[Normal update cycle continues]
```

When the editor redraws the graph (`populateFromCWL`) the inspector finds the new node of
the step by name (`graphRebuilt`); it closes when the step is deleted.

### StepDialog

**Location**: `DialogStep.py`

**Purpose**: Configure workflow step (used when a `CWLGraph` has no step inspector)

**Fields**:
- ID, Label
- Run (path to tool)
- Inputs table (with sources and default values)
- Conditional Inputs section (for inputs used in `when` expressions)
- Outputs list
- Scatter (checkboxes for array inputs)
- ScatterMethod (dropdown)
- When (JavaScript expression for conditional execution)
- Requirements

**Conditional Inputs Feature**:
- Separate section for inputs not matching tool inputs
- Used for `when` statement variables
- Each has Add/Remove buttons
- Stores ID and Source

**Return**: WorkflowStep object

**Signal Flow**:
```
StepNode.onNodeDoubleClicked opens StepDialog
    ↓
Dialog populates from WorkflowStep object
    ↓
User edits and clicks OK
    ↓
Dialog.getData() creates updated WorkflowStep
    ↓
Returns to CWLGraph
    ↓
Graph updates node
    ↓
Graph emits editingFinished
    ↓
[Normal update cycle continues]
```

## Graph Visualization

### CWLGraph

**Location**: `NetworkGraph.py`

**Purpose**: Interactive graph visualization of workflow

**Components**:
- pyqtgraph GraphicsLayoutWidget for rendering
- Custom node classes (StepNode, InputNode, OutputNode)
- Edge connections representing data flow
- Port system for inputs/outputs

**Node Types**:

**InputNode**: Represents workflow input
- Green color
- Has output ports only
- Double-click opens InputDialog for workflow input

**OutputNode**: Represents workflow output
- Blue color  
- Has input ports only
- Double-click opens OutputDialog for workflow output

**StepNode**: Represents workflow step
- Orange/tan color
- Has both input and output ports
- Double-click opens the step in the StepInspector (StepDialog when there is none)
- Displays step ID and tool name

**Port System**:
- Each node has `input_ports` and `output_ports` dictionaries
- Ports are `PortItem` objects with click detection
- Connection made by clicking source port, then target port
- Creates `ConnectionItem` (QGraphicsLineItem with arrow)

**Key Methods**:
- `addStepNode(step)`: Creates StepNode from WorkflowStep object
- `addInputNode(input)`: Creates InputNode from WorkflowInputParameter
- `addOutputNode(output)`: Creates OutputNode from WorkflowOutputParameter
- `createConnection(source_port, target_port)`: Creates edge between ports
- `onNodeDoubleClicked(node)`: Opens appropriate dialog for node type

**Graph → CWL Extraction**:
```
TabWorkflowEditor.getCWL() calls:
    ↓
For each StepNode:
    node.getStepData() → WorkflowStep object
    ↓
For each InputNode:
    node.getInputData() → WorkflowInputParameter object
    ↓
For each OutputNode:
    node.getOutputData() → WorkflowOutputParameter object
    ↓
For each ConnectionItem:
    Extract source and target
    Update WorkflowStepInput.source or WorkflowOutputParameter.outputSource
    ↓
Assemble into Workflow object
```

**CWL → Graph Population**:
```
TabWorkflowEditor.populateFromCWL() calls:
    ↓
For each workflow.inputs:
    graph.addInputNode(input)
    ↓
For each workflow.outputs:
    graph.addOutputNode(output)
    ↓
For each workflow.steps:
    graph.addStepNode(step)
    ↓
For each step.in_ with source:
    Find source node and port
    Find target node and port
    graph.createConnection(source_port, target_port)
    ↓
For each workflow output with outputSource:
    Create connection from step output to workflow output
```

### Node Positioning

- Nodes stored with coordinates in CWL document via extension field
- On load: Nodes placed at saved positions
- On new step: User chooses position or default location
- On drag: New position saved immediately
- Format: `x-cwled-position: {x: 100, y: 200}`

### Graph Update Cycle

```
User creates connection in graph
    ↓
connectionCreated(source, target)
    ↓
Updates internal edge list
    ↓
Emits editingFinished signal
    ↓
TabWorkflowEditor.onGraphChanged()
    ↓
Emits codeUpdated signal
    ↓
ChildWindow.onUpdateCWL()
    ↓
[On tab switch or save]
    ↓
TabWorkflowEditor.getCWL() extracts workflow structure from graph
    ↓
Updates cwl_workflow object with connection information
```

## Summary of Key Patterns

1. **Shared Object Reference**: All tabs hold references to the same `cwl_tool` object, enabling true synchronization

2. **Lazy Updates**: Visual changes stored in UI, committed to CWL object on tab switch or save

3. **Signal Cascading**: Widgets emit signals that bubble up through parent widgets to tabs to window

4. **getCWL() on Exit**: The source tab's `getCWL()` is called when leaving, not when entering target tab

5. **Type Polymorphism**: Same dialog classes (InputDialog, OutputDialog) behave differently based on context (tool vs workflow)

6. **Two-Way Sync**: Code ↔ Visual editors stay synchronized through central `cwl_tool` object

7. **Graph as First-Class Editor**: Workflow graph is not just a visualization; it's a full editor that modifies the CWL structure

8. **Error Handling**: Parse errors in code editor prevent tab switching until resolved

9. **Extensibility**: Widget base classes (QCWLedWidget, QCWLedGroupWidget) make it easy to add new CWL feature support

10. **Menu Signal Forwarding**: MainWindow forwards menu actions as signals to active ChildWindow, maintaining separation of concerns
