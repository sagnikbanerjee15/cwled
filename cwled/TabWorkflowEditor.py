from PyQt6 import sip
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor, QFontMetrics, QUndoStack, QPainter, QPen, QPixmap
import json
import builtins
import data
import theme
import GraphItems
import logging
from NetworkGraph import CWLGraph
from CWLparser import Parser
from pathlib import Path
from typing import Union
import os,sys
import traceback
from typing import Any,Union, Optional
from cwl_utils_handler import get_cwl_module,get_cwl_version
from cwl_utils.parser import save
from GraphNodes import StepNode
from StepInspector import StepInspector
from ports import PortSplitter

class WorkflowEditor(QWidget):
    '''
    Workflow editor tab
    This class provides a widget for editing CWL workflow files
    It displays a graph visualization of the workflow with editing controls
    '''
    cwl_workflow: Any = None # the main object representing the workflow
    updateSignal = pyqtSignal(str)
    codeUpdated = pyqtSignal(str)  # Signal emitted when the workflow is updated    
    tabActivated = pyqtSignal()      # Emitted when this tab becomes current
    tabDeactivated = pyqtSignal()    # Emitted when this tab stops being current
    tab_signal_connected = False # Remember if the singla is connected
    was_active = False # Remember if the tab was active
    file_location = None
    zoom=None
       
    def __init__(self, 
                 cwl_workflow: Any = None, 
                 parent=None, 
                 file_location: Union[str, Path] = None):
        super().__init__(parent)

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel', {}).get(self.__class__.__name__, 'DEBUG'))
        self.setCWLWorkflow(cwl_workflow)
        if file_location:
            self.file_location = Path(file_location).resolve()
        
        # Enable focus tracking
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # self.tabDeactivated.connect(self.getNodeCoordinates)
        # Drag and drop will be enabled only on the dedicated drop zone
        self.initUI()

    def setCWLWorkflow(self, cwl_workflow:Union[Any,None]=None):
        '''
        set the cwl tool to be edited
        it must be a CommandLineTool 
        '''

        type_of_cwl_workflow = type(cwl_workflow).__name__ if cwl_workflow else 'None'
        if type_of_cwl_workflow not in ['Workflow']:
            self.logger.error(f"Expected a Workflow, but got {type_of_cwl_workflow}")
            raise TypeError(f"Expected a Workflow, but got {type_of_cwl_workflow}")

        self.cwl_workflow = cwl_workflow
        self.setCWLVersion()
        self.logger.info(f"\u2705 Set new CWL workflow of class {self.cwl_workflow.class_} "
                         f"and version {self.cwl_workflow.cwlVersion}")
        # self.updateSignal.emit('cwl_tool')


    def setCWLVersion(self, cwl_version:Optional[str]=None):
        '''
        set the CWL version for the tool editor
        '''
        self.cwl_version=get_cwl_version( self.cwl_workflow)
       
        self.logger.debug(f"CWL version for {self.__class__.__name__} is set: {self.cwl_version}")
        


    def eventFilter(self, watched, event):
        """
        Filters events from watched objects. We use this to capture when
        the graph viewer loses focus.
        """
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        if watched is getattr(self, '_canvas', None) and event.type() in (
                QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return self._canvasDrop(event)
        if event.type() == QEvent.Type.FocusOut:
            # Check if the widget that lost focus is the graph viewer
            if watched is self.graph.graph.viewer():
                self.logger.debug("Graph viewer lost focus, capturing node coordinates.")
                self.getNodeCoordinates()
                # self.onGraphChanged()
                # self.codeUpdated.emit("CWL workflow updated")
        
        # Pass the event on to the parent class
        return super().eventFilter(watched, event)


    @staticmethod
    def _cwlFiles(mime_data) -> list:
        """The CWL documents (local files) being dragged."""
        if not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls()
                if url.isLocalFile() and url.toLocalFile().lower().endswith(('.cwl', '.json', '.yaml', '.yml'))
                and os.path.isfile(url.toLocalFile())]

    def _canvasDrop(self, event) -> bool:
        """Accept CWL files over the canvas and add them as steps where dropped."""
        files = self._cwlFiles(event.mimeData())
        if not files:
            event.ignore()
            return True         # nothing else can be dropped on the canvas
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if event.type() == QEvent.Type.Drop:
            viewer = self.graph.graph.viewer()
            position = viewer.mapToScene(event.position().toPoint())
            # after the drag has finished (adding may ask questions)
            QTimer.singleShot(0, lambda: self._addDroppedSteps(files, position))
        return True

    def _addDroppedSteps(self, files: list, position: QPointF):
        for index, cwl_file in enumerate(files):
            offset = 60 * index
            self.onAddStep(cwl_file=cwl_file, position=QPointF(position.x() + offset, position.y() + offset))
        self.graph.graph.viewer().setFocus()

    def initUI(self):
        # Create a main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        
        # The canvas takes the whole editor: steps are added by dropping a document on it (see
        # _canvasDrop) and workflow inputs and outputs by dragging from a port. Dropping is handled
        # by the canvas, not by this widget.
        self.setAcceptDrops(False)

        # Create the CWLGraph widget for displaying the workflow
        self.graph = CWLGraph(
            workflow_file=self.file_location,
            parent=self,
            cwl_workflow=self.cwl_workflow
        )


        # self.graph.connection_created.connect( self.onGraphChanged)
        # self.graph.node_created.connect(self.onGraphChanged)
        self.graph.editingFinished.connect( self.onGraphChanged )

        # Composer step inspector, docked on the right of the canvas: steps
        # double-clicked on the canvas open there instead of in a dialog
        self.step_inspector = StepInspector(self.graph, parent=self)
        self.graph.inspect_step = self.step_inspector.inspect
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName('inspectorSplitter')
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.graph)
        self.splitter.addWidget(self.step_inspector)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([10000, StepInspector.DEFAULT_WIDTH])
        # Add the canvas to the layout, taking all remaining space
        main_layout.addWidget(self.splitter, 1)  # The 1 gives this widget a stretch factor

        # Tools and workflows dragged from the Workspace panel (or a file
        # manager) onto the canvas become steps where they are dropped.
        # OdenGraphQt would otherwise try to import them as graph sessions.
        viewer = self.graph.graph.viewer()
        try:
            viewer.data_dropped.disconnect(self.graph.graph._on_node_data_dropped)
        except (TypeError, RuntimeError):
            pass
        self._canvas = viewer.viewport()
        self._canvas.installEventFilter(self)

        # Composer's canvas buttons: delete, zoom, fit, auto-arrange, export
        self.graph_controls = GraphItems.GraphControls(
            self.graph.graph_widget,
            self.graph.graph,
            on_delete=self.graph.deleteSelection,
            on_arrange=self.onResetPlot,
            on_export=self.onExportImage,
        )

        
        # Set the layout for this widget
        self.setLayout(main_layout)

    def exportSVGWithTooltips(self, file_path):
        """
        Export the graph as SVG with optional embedded tooltips showing node names/titles.
        
        Args:
            file_path (str): Path where the SVG file should be saved
        """
        from PyQt6.QtGui import QPainter
        from PyQt6.QtSvg import QSvgGenerator
        from PyQt6.QtCore import QRectF
        
        viewer = self.graph.graph.viewer()
        scene = viewer.scene()
        # Bounds of the drawn graph (hidden helper items left out)
        rect = GraphItems.contentRect(scene)
        # Add some padding around the content
        padding = 20
        rect.adjust(-padding, -padding, padding, padding)

        # Generate SVG with tooltips
        import xml.etree.ElementTree as ET
        from PyQt6.QtCore import QBuffer, QIODevice
        
        # First, generate the SVG using the standard method
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        
        generator = QSvgGenerator()
        generator.setOutputDevice(buffer)
        generator.setSize(rect.size().toSize())
        # Set viewBox to start at (0,0) with the size of the rect
        generator.setViewBox(QRectF(0, 0, rect.width(), rect.height()))
        generator.setTitle("Workflow Graph")
        generator.setDescription("Exported CWL workflow graph with tooltips.")
        
        painter = QPainter(generator)
        # Render the scene rect to a target starting at (0,0)
        target = QRectF(0, 0, rect.width(), rect.height())
        scene.render(painter, target=target, source=rect)
        painter.end()
        
        # Get the SVG content as bytes
        svg_content = bytes(buffer.data()).decode('utf-8')
        buffer.close()
        
        # Parse the SVG XML
        try:
            # Register SVG namespace
            ET.register_namespace('', 'http://www.w3.org/2000/svg')
            root = ET.fromstring(svg_content)
            
            # Get all nodes from the graph and scene items
            nodes = self.graph.graph.all_nodes()
            scene_items = scene.items()
            
            # Map node positions to their titles, also get scene bounding boxes
            # Transform coordinates from scene to SVG coordinate system
            node_info = {}
            for node in nodes:
                pos = node.pos()
                # Get the custom title or name
                if hasattr(node, 'get_property') and node.has_property('full_title'):
                    display_name = node.get_property('full_title')
                else:
                    display_name = node.name()
                if hasattr(node, 'get_property') and node.has_property('documentation'):
                    display_name = f"{display_name}\n{node.get_property('documentation')}"
               
                
                # Get the visual widget's bounding box if available
                view = node.view if hasattr(node, 'view') else None
                if view and hasattr(view, 'boundingRect'):
                    bbox = view.boundingRect()
                    # Get the scene position of the view
                    if hasattr(view, 'scenePos'):
                        scene_pos = view.scenePos()
                        center_x = scene_pos.x() + bbox.width() / 2
                        center_y = scene_pos.y() + bbox.height() / 2
                    else:
                        # Fall back to node position
                        center_x = pos[0]
                        center_y = pos[1]
                else:
                    # Use node position as center
                    center_x = pos[0]
                    center_y = pos[1]
                
                # Transform scene coordinates to SVG coordinates (starting at 0,0)
                svg_x = center_x - rect.x()
                svg_y = center_y - rect.y()
                    
                node_info[node.name()] = {
                    'x': svg_x,
                    'y': svg_y,
                    'title': display_name
                }
            
            self.logger.debug(f"Processing {len(node_info)} nodes for tooltips")
            
            # New approach: Look for text elements in SVG and add tooltips to their parent groups
            # Text elements often contain the node names/labels
            import re
            svg_ns = {'svg': 'http://www.w3.org/2000/svg'}
            
            # Track which nodes we've added tooltips for
            tooltips_added = 0
            processed_groups = set()
            
            # Strategy 1: Find text elements and add tooltips to their parent groups
            for text_elem in root.findall('.//svg:text', svg_ns):
                text_content = ''.join(text_elem.itertext()).strip()
                
                if text_content:
                    # Find matching node
                    matched_title = None
                    for node_name, info in node_info.items():
                        # Check if text matches node name or title
                        if text_content == node_name or text_content == info['title']:
                            matched_title = info['title']
                            break
                        # Also check partial matches
                        elif text_content in node_name or node_name in text_content:
                            matched_title = info['title']
                            break
                        elif text_content in info['title'] or info['title'] in text_content:
                            matched_title = info['title']
                            break
                    
                    if matched_title:
                        # Find the parent group that contains this text
                        parent = None
                        for p in root.iter():
                            if text_elem in list(p):
                                parent = p
                                break
                        
                        # Walk up to find the top-level group for this node
                        while parent is not None and parent.tag.endswith('g'):
                            parent_id = id(parent)
                            if parent_id not in processed_groups:
                                # Check if title already exists
                                has_title = any(child.tag.endswith('title') for child in parent)
                                if not has_title:
                                    title_elem = ET.Element('{http://www.w3.org/2000/svg}title')
                                    title_elem.text = matched_title
                                    parent.insert(0, title_elem)
                                    tooltips_added += 1
                                    processed_groups.add(parent_id)
                                    self.logger.debug(f"Added tooltip '{matched_title}' based on text '{text_content}'")
                                break
                            # Try parent's parent
                            found_parent = False
                            for pp in root.iter():
                                if parent in list(pp) and pp.tag.endswith('g'):
                                    parent = pp
                                    found_parent = True
                                    break
                            if not found_parent:
                                break
            
            # Strategy 2: If no tooltips added yet, add to all top-level groups
            if tooltips_added == 0:
                self.logger.warning("No text-based matches found, trying group-based approach")
                # Find all top-level g elements (children of root or one level down)
                top_groups = []
                for child in root:
                    if child.tag.endswith('g'):
                        top_groups.append(child)
                        for subchild in child:
                            if subchild.tag.endswith('g'):
                                top_groups.append(subchild)
                
                # Sort node_info by position to match with groups
                sorted_nodes = sorted(node_info.items(), key=lambda x: (x[1]['y'], x[1]['x']))
                
                for i, group in enumerate(top_groups[:len(sorted_nodes)]):
                    if i < len(sorted_nodes):
                        node_name, info = sorted_nodes[i]
                        has_title = any(child.tag.endswith('title') for child in group)
                        if not has_title:
                            title_elem = ET.Element('{http://www.w3.org/2000/svg}title')
                            title_elem.text = info['title']
                            group.insert(0, title_elem)
                            tooltips_added += 1
            
            self.logger.info(f"Added {tooltips_added} tooltips to groups")
            
            # Strategy 3: Add tooltips directly to shape elements (rect, ellipse, path, circle, polygon)
            # This ensures hovering over the actual shapes shows tooltips
            shape_tooltips_added = 0
            for group in processed_groups:
                # Find the group element by id
                for g in root.iter():
                    if id(g) == group:
                        # Get the title from this group
                        tooltip_text = None
                        for child in g:
                            if child.tag.endswith('title'):
                                tooltip_text = child.text
                                break
                        
                        if tooltip_text:
                            # Add the same title to all shape children
                            for shape in g.iter():
                                if any(shape.tag.endswith(t) for t in ['rect', 'ellipse', 'circle', 'path', 'polygon']):
                                    # Check if it already has a title
                                    has_title = any(c.tag.endswith('title') for c in shape)
                                    if not has_title:
                                        shape_title = ET.Element('{http://www.w3.org/2000/svg}title')
                                        shape_title.text = tooltip_text
                                        shape.insert(0, shape_title)
                                        shape_tooltips_added += 1
                        break
            
            self.logger.info(f"Added {shape_tooltips_added} tooltips to shape elements")
            self.logger.info(f"Total tooltips: {tooltips_added} groups + {shape_tooltips_added} shapes = {tooltips_added + shape_tooltips_added}")
            
            # Write the modified SVG to file with proper formatting
            tree = ET.ElementTree(root)
            ET.indent(tree, space='  ')  # Pretty print for debugging
            tree.write(file_path, encoding='utf-8', xml_declaration=True)
            
            
        except Exception as e:
            self.logger.error(f"Error adding tooltips to SVG: {e}")
            # Fallback: save without tooltips
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(svg_content)
    
    def onExportImage(self, filename=None):
        """
        Export the current graph view as an image (SVG, PNG, JPEG).
        If filename is not set or does not end with a supported extension, open a dialog.
        """
        supported_exts = ['.svg', '.png', '.jpeg', '.jpg']
        file_path = filename
        if not file_path or not any(file_path.lower().endswith(ext) for ext in supported_exts):
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Graph Image",
                "",
                "SVG Image (*.svg);;PNG Image (*.png);;JPEG Image (*.jpeg *.jpg)"
            )
            if not file_path:
                return

        viewer = self.graph.graph.viewer()
        scene = viewer.scene()
        # Bounds of the drawn graph (hidden helper items left out)
        rect = GraphItems.contentRect(scene)
        # Add some padding around the content
        padding = 20
        rect.adjust(-padding, -padding, padding, padding)

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.png':
            from PyQt6.QtGui import QImage, QPainter
            image = QImage(rect.size().toSize(), QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.white)
            painter = QPainter(image)
            scene.render(painter, source=rect)
            painter.end()
            image.save(file_path)
        elif ext in ['.jpeg', '.jpg']:
            from PyQt6.QtGui import QImage, QPainter
            image = QImage(rect.size().toSize(), QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.white)
            painter = QPainter(image)
            scene.render(painter, source=rect)
            painter.end()
            image.save(file_path, "JPEG")
        elif ext == '.svg':
            self.exportSVGWithTooltips(file_path)
            # Use the new function that adds tooltips
            # from PyQt6.QtGui import QPainter
            # from PyQt6.QtSvg import QSvgGenerator
            # from PyQt6.QtCore import QRectF
            # generator = QSvgGenerator()
            # generator.setFileName(file_path)
            # generator.setSize(rect.size().toSize())
            # # Set viewBox to start at (0,0) with the size of the rect
            # generator.setViewBox(QRectF(0, 0, rect.width(), rect.height()))
            # generator.setTitle("Workflow Graph")
            # generator.setDescription("Exported CWL workflow graph.")
            # painter = QPainter(generator)
            # # Render the scene rect to a target starting at (0,0)
            # target = QRectF(0, 0, rect.width(), rect.height())
            # scene.render(painter, target=target, source=rect)
            # painter.end()
        



    def onZoom(self):
        pass
        # print(f"Zoom level is { self.graph.graph.get_zoom()}")

    def onResetPlot(self):
        """
        Reset the graph view to fit all nodes
        """
        self.logger.debug("Reset Plot button clicked")
        try:
            if self.node_coordinates:
                self.node_coordinates = {}
            self.graph.showGraph()
            self.logger.info("\u2705 Graph view reset to fit all nodes")
        except Exception as e:
            self.logger.error(f"Error resetting graph view: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to reset graph view:\n{str(e)}")

    def populateFromCWL(self, file_location: Union[str, Path] = None):
        '''
        Set the relevant fields from the global cwl_dict and update the graph
        This function is called when the tab is selected or when the cwl_dict is updated
        '''
        if file_location:
            self.file_location = file_location
            
        self.logger.debug(f"Populating workflow editor with CWL document of class {self.cwl_workflow.class_}")
        
        # Update the graph with the current CWL dictionary
        self.graph.setCWL(self.cwl_workflow)
        self.graph.setFileLocation(self.file_location)
        self.getNodeCoordinates()
        self.graph.makeGraph()
        self.graph.showGraph()
        self.step_inspector.graphRebuilt()
        
    def generateUniqueStepID(self, new_step_id: str) -> str:
        """
        Generate a unique step ID by checking against existing step IDs in the graph"""
        existing_steps = []
        for node in self.graph.graph.all_nodes():
            if node.type_ == 'cwled.step.StepNode':
                existing_steps.append(node.name())

        # get the existing steps
        counter = 1
        
        while new_step_id in existing_steps:
            counter += 1
            new_step_id = f"{new_step_id}_{counter}"
        return new_step_id
    
    def userProvideFile(self) -> Optional[str]:
        # Use workspace directory if available, otherwise fallback to file location or home directory
        home_dir = str(Path.home())
        self.logger.info(f"Setting the default value {home_dir} ")
        if self.file_location:
            # Try to start in the same directory as the current workflow file
            try:
                file_dir = str(Path(self.file_location).parent)
                if Path(file_dir).exists():
                    home_dir = file_dir
                self.logger.info(f"Setting the base directory for tools to {home_dir} based on the workflow location")
            except:
                home_dir = str(Path.home())
                self.logger.info(f"Setting the base directory for tools to {home_dir} since the directory of the workflow does not exist")
        elif hasattr(data, 'workspace_directory'):
            home_dir = data.workspace_directory
            self.logger.info(f"Setting the base directory for tools to {home_dir}")
            
    

        files= QFileDialog.getOpenFileName(
            main_window,
            'Select CWL Tool or Workflow',
            home_dir,
            "CWL Files (*.cwl *.yaml *.yml *.json);;All Files (*)",
            # options = QFileDialog.Option.DontUseNativeDialog
        )
        cwl_file=files[0]
        return cwl_file if cwl_file else None
            
    def onAddStep(self, cwl_file: Optional[str] = None, position: Optional[QPointF] = None):
        """
        Handle Add Step button click - opens a file dialog to select a CWL file and creates a new step node
        based on that file with the proper input and output ports according to CWL v1.2 specification

        ``position``: scene position of the new step (a file dropped on the
        canvas): it is placed there and the other nodes stay where they are.
        """
        
        self.logger.info(f"Adding Step to workflow")
        if cwl_file:
            self.logger.debug(f"Using provided CWL file: {cwl_file}")
        else:
            self.logger.debug(f"No CWL file provided, opening file dialog")
        if not cwl_file:
            cwl_file = self.userProvideFile()
            if not cwl_file:
                self.logger.debug("No CWL file selected, aborting Add Step")
                return
            
        self.logger.debug(f"Selected CWL file: {cwl_file}")
        if self.file_location and Path(cwl_file).resolve() == Path(self.file_location).resolve():
            QMessageBox.warning(self, "Add Step", "A workflow cannot be a step of itself.")
            return
        module=get_cwl_module( self.cwl_workflow.cwlVersion)
        try:
            # Parse the selected CWL file
            cwl_parser = Parser(cwl_file)
            tool_cwl = cwl_parser.getCWL()
            if not self.graph.checkToolWorkflowVersionCompatibility(tool_cwl=tool_cwl):
                self.logger.warning("Add Step aborted due to CWL version mismatch")
                return
            # Extract relevant information from the tool
            tool_id = PortSplitter(tool_cwl.id, workflow_id=self.cwl_workflow.id).port_id if tool_cwl.id else 'unnamed_tool'
            tool_class = tool_cwl.class_
            if not self.file_location:
                QMessageBox.information(self, "Save Required",
                    "The workflow must be saved before adding steps.\n"
                    "Please choose a file location.")
                default_dir = str(data.workspace_directory) if data.workspace_directory else ""
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Workflow As",
                    default_dir,
                    "CWL Files (*.cwl);;All Files (*)"
                )
                if not file_path:
                    self.logger.debug("Save cancelled, aborting Add Step")
                    return
                self.file_location = Path(file_path).resolve()
                self.graph.setFileLocation(self.file_location)
                self.logger.debug(f"Workflow will be saved to: {self.file_location}")
            try:
                run_path=os.path.relpath( cwl_file, start=os.path.dirname(self.file_location))
            except ValueError as e:
                self.logger.warning("Cannot use this tool, ",
                                    "since it is not in a sub directory of the main workflow",
                                    f"Workflow {self.file_location}, Tool {cwl_file}: {str(e)}")
                return 
            # print(f"The path of the new step is {run_path} and thw workspace is {str(data.workspace_directory)}")
            # need to create a new WorkflowStep to pass to the StepNode
            step_data=module.WorkflowStep(
                id=self.generateUniqueStepID(tool_id),
                label=tool_cwl.label,
                in_=[],
                out=[],
                run=run_path
            )
        #     # Add SubworkflowFeatureRequirement if this is adding a workflow as a step
            if tool_class == 'Workflow':
                self.addRequirementIfMissing('SubworkflowFeatureRequirement')
                
            
            # Extract outputs for the "out" field
            if hasattr(tool_cwl,'outputs') and tool_cwl.outputs:
                for output_item in tool_cwl.outputs:
                    # Handle outputs in both array and object formats
                    output_id = PortSplitter( output_item.id , tool_id ).port_id
                    # Strip off any leading namespace from id if present
                    if output_id and '#' in output_id:
                        output_id = output_id.split('#')[-1]

                    step_data.out.append(
                        module.WorkflowStepOutput(
                            id=output_id
                        )
                    )
   
        #     # we need to call makeGraph to update the graph

            if not self.cwl_workflow.steps:
                self.cwl_workflow.steps=[]
            self.cwl_workflow.steps.append(step_data)

            if position is not None:
                # keep every node where it is, the new one goes where it was dropped
                self.getNodeCoordinates()
                self.node_coordinates[step_data.id] = {'x': position.x(), 'y': position.y()}

            # Update the  CWL dictionary in the graph before making the graph
            self.graph.setCWL(self.cwl_workflow)
            self.graph.makeGraph()
            if position is not None:
                self.setNodeCoordinates()
                node = self.graph.graph.get_node_by_name(step_data.id)
                if node is not None:
                    # centred on the drop point
                    x = position.x() - node.view.width / 2
                    y = position.y() - node.view.height / 2
                    node.set_pos(x, y)
                    self.node_coordinates[step_data.id] = {'x': x, 'y': y}
                self.graph.graph.viewer().update()
            else:
                self.graph.showGraph()
                # Ensure proper placement of inputs and outputs after adding a new step
                try:
                    self.graph.arrange_inputs_outputs(force_all=False)
                except Exception as e:
                    self.logger.warning(f"Error arranging inputs/outputs after adding step: {str(e)}")


        #     # Display information to the user
        #     self.logger.debug(f"Created new step node: {new_step_id} referencing {cwl_file}")
            self.logger.info(f"\u2705 Successfully added step node from {cwl_file}")
        except Exception as e:
            self.logger.error(f"Error creating step node from {cwl_file}: {str(e)} =>\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Error", f"Failed to create step node from {cwl_file}:\n{str(e)}")
            return
        
    def onDuplicateStep(self):
        """
        Duplicate the currently selected step node. Creates a new step with the same
        'run' reference and output ports, but with no input connections.
        """
        self.logger.info("Duplicating selected step")

        # Get selected nodes
        selected_nodes = self.graph.graph.selected_nodes()
        if not selected_nodes:
            QMessageBox.information(self, "Duplicate Step",
                "Please select a step node to duplicate.")
            return

        if len(selected_nodes) > 1:
            QMessageBox.information(self, "Duplicate Step",
                "Please select only one step node to duplicate.")
            return

        node = selected_nodes[0]
        if node.type_ != 'cwled.step.StepNode':
            QMessageBox.information(self, "Duplicate Step",
                "Only step nodes can be duplicated. Please select a step node.")
            return

        try:
            module = get_cwl_module(self.cwl_workflow.cwlVersion)
            original_step = node.cwl_step

            # Generate a unique ID based on the original step's ID
            new_step_id = self.generateUniqueStepID(original_step.id)

            # Build label with "(Copy)" suffix
            new_label = f"{original_step.label} (Copy)" if original_step.label else None

            # Copy output port definitions from the original step
            new_outputs = []
            if original_step.out:
                for out in original_step.out:
                    new_outputs.append(
                        module.WorkflowStepOutput(id=out.id)
                    )

            # Create the new WorkflowStep with no input connections
            step_data = module.WorkflowStep(
                id=new_step_id,
                label=new_label,
                in_=[],
                out=new_outputs,
                run=original_step.run
            )

            # Add SubworkflowFeatureRequirement if the tool is a Workflow
            if hasattr(node, 'cwl_tool') and node.cwl_tool and node.cwl_tool.class_ == 'Workflow':
                self.addRequirementIfMissing('SubworkflowFeatureRequirement')

            if not self.cwl_workflow.steps:
                self.cwl_workflow.steps = []
            self.cwl_workflow.steps.append(step_data)

            # Rebuild the graph
            self.graph.setCWL(self.cwl_workflow)
            self.graph.makeGraph()
            self.graph.showGraph()
            try:
                self.graph.arrange_inputs_outputs(force_all=False)
            except Exception as e:
                self.logger.warning(f"Error arranging inputs/outputs after duplicating step: {str(e)}")

            self.logger.info(f"\u2705 Successfully duplicated step '{original_step.id}' as '{new_step_id}'")
        except Exception as e:
            self.logger.error(f"Error duplicating step: {str(e)} =>\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Error", f"Failed to duplicate step:\n{str(e)}")

    def findJavaScript(self):
        """
        Recursively traverses a CWL object (from parsed YAML/JSON) to find
        strings that look like CWL JavaScript expressions.
        """
        def traverse(obj):
            if isinstance(obj, dict):
                for value in obj.values():
                    if traverse(value):
                        return True
            elif isinstance(obj, list):
                for item in obj:
                    if traverse(item):
                        return True
            elif isinstance(obj, str):
                stripped_str = obj.strip()
                if stripped_str.startswith("$(") or stripped_str.startswith("${"):
                    self.logger.info(f"Found potential JavaScript expression: {obj}")
                    return True
            return False

        return traverse(save(self.cwl_workflow))

    def addRequirementIfMissing(self, requirement_class: str):
        """
        Add a requirement of the specified class to the workflow if it is not already present.
        """
        if getattr(self.cwl_workflow, 'requirements', None) is None:
            self.cwl_workflow.requirements = []
        
        # Check if the requirement is already present
        for req in self.cwl_workflow.requirements:
            req_class = req.get('class') if isinstance(req, dict) else getattr(req, 'class_', None)
            if req_class == requirement_class:
                self.logger.debug(f"Requirement {requirement_class} already present in workflow.")
                return  # Requirement already exists
        
        # Add the missing requirement
        module = get_cwl_module(self.cwl_workflow.cwlVersion)
        requirement_instance = getattr(module, requirement_class)()
        self.cwl_workflow.requirements.append(requirement_instance)
        self.logger.info(f"\u2705 Added missing requirement {requirement_class} to workflow.")

    def findMultiStepInputs(self):
        """
        Find inputs that are connected to multiple steps in the workflow.
        Returns a list of such input IDs.
        """
        input_connections = {}
        
        # Iterate over all step nodes in the graph
        for self.cwl_workflow_step in self.cwl_workflow.steps:
            for step_input in self.cwl_workflow_step.in_:
                if isinstance(step_input.source, list):
                    return True
                
            
        
        return False

    def findScatter(self):
        """
        Check if any workflow step has a scatter field.
        Returns True if scatter is found, False otherwise.
        """
        if not hasattr(self.cwl_workflow, 'steps') or not self.cwl_workflow.steps:
            return False
        
        for step in self.cwl_workflow.steps:
            if hasattr(step, 'scatter') and step.scatter:
                self.logger.info(f"Found scatter in step {step.id}: {step.scatter}")
                return True
        
        return False
 
    def onGraphChanged(self):
        """
        When the graph is changed this function is called to update
        the local cwl_workflow object.

        The changes of the workfow are not propagated to the
        ChildWindow yet.
        They are propagated when the tab is changed or
        when the graph viewer loses focus.

        """
        self.logger.info(f"\u231B Graph changed, updating CWL workflow")
        self.cwl_workflow=self.graph.getData()
        js_expressions = self.findJavaScript()
        if js_expressions:
            self.addRequirementIfMissing('InlineJavascriptRequirement')
        if self.findMultiStepInputs():
            self.addRequirementIfMissing('MultipleInputFeatureRequirement')
        if self.findScatter():
            self.addRequirementIfMissing('ScatterFeatureRequirement')
        # self.codeUpdated.emit("CWL workflow updated")

 
    def getCWL(self):
        """
        Get the CWL of the workflow

        This ensures that any changes made via the graph UI (like connections between nodes)
        are properly captured in the main CWL dictionary when the widget loses focus.

        In reality this function updates the self.cwl_dict which is a reference
        to the cwl_dict shared in all tabs of this ChildWindow
        
        """
        #check if we need to add the JavascriptRequirement
        
        return self.cwl_workflow



    def setNodeCoordinates( self ):
        """
        Iterate over all nodes in the underlying graph, and update their coordinates
        based on the values stored in self.node_coordinates

        Stores:
            self.node_coordinates = {
                <node_name>: {"x": float, "y": float}
            }

        Returns:
            dict: The mapping of node names to coordinate dicts.
        """
        updated_count=0
        if not hasattr(self, "node_coordinates"):
            return None
        if not hasattr(self.graph, "graph") or not hasattr(self.graph.graph, "all_nodes"):
            self.logger.warning("Graph structure does not expose graph.all_nodes()")
            return None
        for node in  self.graph.graph.all_nodes():
            node_id = node.name()
                
            if node_id in self.node_coordinates:
                stored_coords = self.node_coordinates[node_id]
                try:
                    new_x = float(stored_coords['x'])
                    new_y = float(stored_coords['y'])
                    
                    # Get current position to check if update is needed
                    current_pos = None
                    if hasattr(node, 'set_pos') and callable(node.set_pos):
                        node.set_pos(new_x, new_y) 
                        node.view.update()
                        updated_count += 1
                        self.logger.debug(f"Updated position for node {node_id}: x={new_x}, y={new_y}")
                    else:
                        self.logger.debug(f"Node {node_id} does not have set_pos method")
                        
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Invalid coordinates for node {node_id}: {stored_coords} - {e}")

        self.graph.graph.viewer().update()       
        self.logger.info(f'\u2705 Updated the positions of {updated_count} nodes')

        return updated_count

    def getNodeCoordinates( self ):
        """
        Iterate over all nodes in the underlying graph, capture their (x,y) coordinates
        and store them on the editor instance.

        Stores:
            self.node_coordinates = {
                <node_name>: {"x": float, "y": float}
            }

        Returns:
            dict: The mapping of node names to coordinate dicts.
        """
        if not self.zoom:
            self.zoom=self.graph.graph.get_zoom()
        # print(f"Zoom level set to {self.zoom}")
        coords = {}
        if not hasattr(self, "node_coordinates"):
            self.node_coordinates = {}
        if not hasattr(self.graph, "graph") or not hasattr(self.graph.graph, "all_nodes"):
            self.logger.warning("Graph structure does not expose graph.all_nodes()")
            return self.node_coordinates
        # self.graph.graph.clear_undo_stack()
        for node in  self.graph.graph.all_nodes():
            node_id = node.name()
            # Get position coordinates
            x_val = y_val = None
             # Debug: Check current positions

            try:
                x_val = float(node.x_pos())
                y_val = float(node.y_pos())
            except Exception as e:
                self.logger.debug(f"Could not get x_pos/y_pos for node {node_id}: {e}")
            
            if x_val is not None and y_val is not None:
                coords[node_id] = {"x": x_val, "y": y_val}
                # self.logger.debug(f"Captured coordinates for node {node_id}: x={x_val}, y={y_val}")
            else:
                self.logger.warning(f"Could not determine coordinates for node {node_id}")

        self.node_coordinates.update(coords)
        
        self.logger.debug(f"\u2705 Captured coordinates for {len(coords)} nodes")
        
        return self.node_coordinates