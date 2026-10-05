import signal
from pathlib import Path,PosixPath
import logging
from copy import deepcopy
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import QFont,QPainter, QColor, QPen, QPolygonF, QTransform

from urllib.parse import urlparse
from PyQt6.QtCore import Qt, QPointF


from CWLparser import  Parser, is_optional
import json
from OdenGraphQt import (
    NodeGraph, BaseNode, BaseNodeCircle
)
from OdenGraphQt.constants import PipeLayoutEnum
from configuration import Configuration
import builtins
import sys
from typing import Union, Any,List,Optional
from copy import deepcopy
import data
import theme
import GraphItems
from jinja2 import Environment, FileSystemLoader
import os
from cwl_utils.parser import save
from cwl_utils_handler import get_cwl_module, get_cwl_version
import re
from DialogInput import InputDialog
from DialogOutput import OutputDialog
from DialogStep import StepDialog
from OdenGraphQt.errors import PortRegistrationError
from ports import PortSplitter
import inspect

class CWLNode(BaseNode):
    """
    class for CWL-specific functionality shared across Input, Output, and Step nodes.
    This includes setting the CWL data, adding edges, and managing ports.
    """
    cwl_step:Any = None # holds the CWL of the node
    is_workflow=False
    workflow_id: str =None # the workflow id if this is a workflow node. 
                           # this will be used to properly parse the ports
    subgraph_level=0
    workflow_filename=None   # this is the filename that invoked this tool e.g the workflow's 
    cwl_filename=None      # this is the filename that contains the CWL for this tool
    step_id=None # this keeps the id of the step in the workflow 
    # Base directory for resolving relative paths
    _base_dir = None
    title=None # custom title for the node, used in the UI
    title_above=False # if set to tTrue the title will be displayed above the node
    cwl_version: str =None
    cwl_tool:Any=None # will hold the CWL of the external tool

 

    def __init__(self):
        # drawn as a cwl-svg (Rabix Composer) node
        super().__init__(qgraphics_item=GraphItems.CWLNodeItem)
        self.set_property('width',500)
        self.logger=logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        self.logger_tooltip=logging.getLogger(f"{self.__class__.__name__}_tooltip")
        self.logger_tooltip.setLevel(data.configuration.get('logLevel',{}).get(f"{self.__class__.__name__}_tooltip", 'DEBUG'))
        self.logger_edges=logging.getLogger(f"{self.__class__.__name__}_edges")
        self.logger_edges.setLevel(data.configuration.get('logLevel',{}).get(f"{self.__class__.__name__}_edges", 'DEBUG'))
        self.logger_edges_stepstep=logging.getLogger(f"{self.__class__.__name__}_edges_stepstep")
        self.logger_edges_stepstep.setLevel(data.configuration.get('logLevel',{}).get(f"{self.__class__.__name__}_edges_stepstep", 'DEBUG'))
        self.logger_edges_stepinput=logging.getLogger(f"{self.__class__.__name__}_edges_stepinput")
        self.logger_edges_stepinput.setLevel(data.configuration.get('logLevel',{}).get(f"{self.__class__.__name__}_edges_stepinput", 'DEBUG'))
        self.logger_edges_stepoutput=logging.getLogger(f"{self.__class__.__name__}_edges_stepoutput")
        self.logger_edges_stepoutput.setLevel(data.configuration.get('logLevel',{}).get(f"{self.__class__.__name__}_edges_stepoutput", 'DEBUG'))
        self.logger_ports=logging.getLogger(f"{self.__class__.__name__}_ports")
        self.logger_ports.setLevel(data.configuration.get('logLevel',{}).get(f"{self.__class__.__name__}_ports", 'DEBUG'))
        self.logger_splitports=logging.getLogger(f"{self.__class__.__name__}_splitports")
        self.logger_splitports.setLevel(data.configuration.get('logLevel',{}).get(f"{self.__class__.__name__}_splitports", 'DEBUG'))


    def applyNodeColors(self, fill):
        """Fill the node's inner circle with a cwl-svg colour."""
        self.set_color(*fill[:3])

    def ioGlyph(self, direction):
        """cwl-svg icon of a workflow input or output: a file icon for
        File and File[] parameters (GraphNode.makeIconFragment)."""
        type_ = getattr(self.cwl_step, 'type_', None)
        if isinstance(type_, list):
            types = [t for t in type_ if t != 'null']
            type_ = types[0] if len(types) == 1 else None
        if getattr(type_, 'type_', None) == 'array':
            type_ = getattr(type_, 'items', None)
        is_file = isinstance(type_, str) and type_.split('#')[-1] == 'File'
        return f"file_{direction}" if is_file else direction

    def draw_rectangle_port(self, painter, rect, info):
        """
        Custom paint function for drawing a rectangular shaped port for required ports.

        Args:
            painter (QtGui.QPainter): painter object.
            rect (QtCore.QRectF): port rect used to describe parameters
                                needed to draw.
            info (dict): information describing the ports current state.
                {
                    'port_type': 'in',
                    'color': (0, 0, 0),
                    'border_color': (255, 255, 255),
                    'multi_connection': False,
                    'connected': False,
                    'hovered': False,
                }
        """
        painter.save()

        # Calculate the new rectangle dimensions
        # Make width twice the height for a 2:1 aspect ratio
        original_height = rect.height()
        new_width = original_height * 2
        new_height = original_height
        
        # Center the rectangle within the original rect
        center_x = rect.center().x()
        center_y = rect.center().y()
        
        # Create new rectangle with 2:1 aspect ratio, centered
        new_rect = QRectF(
            center_x - new_width  / 1.5,
            center_y - new_height / 2,
            new_width,
            new_height
        )

        # mouse over port color.
        if info['hovered']:
            color = QColor(14, 45, 59)
            border_color = QColor(136, 255, 35, 255)
        # port connected color.
        # elif info['connected']:
        #     color = QColor(195, 60, 60)
        #     border_color = QColor(200, 130, 70)
        # default port color
        else:
            color = QColor(*info['color'])
            border_color = QColor(*info['border_color'])

        pen = QPen(border_color, 1.8)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        painter.setPen(pen)
        painter.setBrush(color)
        painter.drawRect(new_rect)

        painter.restore()

    def draw_triangle_port(self, painter, rect, info):
        """
        Custom paint function for drawing a triangle shaped port with vertical base on the right.
        Creates a triangle pointing left with the vertical base on the right side.

        Args:
            painter (QtGui.QPainter): painter object.
            rect (QtCore.QRectF): port rect used to describe parameters
                                needed to draw.
            info (dict): information describing the ports current state.
                {
                    'port_type': 'in',
                    'color': (0, 0, 0),
                    'border_color': (255, 255, 255),
                    'multi_connection': False,
                    'connected': False,
                    'hovered': False,
                }
        """
        painter.save()

        # Calculate triangle dimensions based on the original rect
        original_height = rect.height()
        triangle_width = original_height * 2  # Make it wider than tall
        triangle_height = original_height
        
        # Center the triangle, then shift left by 1/3 of width
        center_x = rect.center().x()
        center_y = rect.center().y()
        left_shift = triangle_width / 3  # Move left by 1/3 of triangle width
        
        # Define triangle points (left-pointing with vertical base on right)
        # Top-right point
        top_right = QPointF(
            center_x + triangle_width / 1.5 - left_shift,
            center_y - triangle_height / 2
        )
        
        # Bottom-right point (forms vertical base with top-right)
        bottom_right = QPointF(
            center_x + triangle_width / 1.5 - left_shift,
            center_y + triangle_height / 2
        )
        
        # Left point (triangle tip pointing left)
        left_point = QPointF(
            center_x - triangle_width / 2 - left_shift,
            center_y
        )
        
        # Create triangle polygon
        triangle = QPolygonF([top_right, bottom_right, left_point])

        # Set colors based on port state
        # mouse over port color.
        if info['hovered']:
            color = QColor(14, 45, 59)
            border_color = QColor(136, 255, 35, 255)
        # port connected color.
        # elif info['connected']:
        #     color = QColor(195, 60, 60)
        #     border_color = QColor(200, 130, 70)
        # default port color
        else:
            color = QColor(*info['color'])
            border_color = QColor(*info['border_color'])

        # Set up pen and brush
        pen = QPen(border_color, 1.8)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        painter.setPen(pen)
        painter.setBrush(color)
        
        # Draw the triangle
        painter.drawPolygon(triangle)

        painter.restore()


    def onNodeDoubleClicked(self, node):
        """
        Handle the update button click event.
        This method is called when the update button is clicked.
        it has to be overriden
        """
        # self.logger = getattr(self, 'logger', logging.getLogger(self.__class__.__name__))
        # self.logger.debug(f"Update button clicked for node {self.name()}")

    def getDialogParent(self):
        """
        Resolve a stable parent widget for modal dialogs opened from graph nodes.

        Prefer the containing top-level window so dialogs stay associated with the
        active workflow window and avoid unintended activation behavior.
        """
        try:
            if hasattr(self, 'graph') and self.graph is not None:
                graph_widget = getattr(self.graph, 'widget', None)
                if graph_widget is not None:
                    return graph_widget.window()
        except Exception:
            pass
        return None
        
    def setCWLVersion(self, cwl_version: str=None):
        if not isinstance(cwl_version, str):
            self.cwl_version = get_cwl_version(self.cwl_step)
        else:
            self.cwl_version = cwl_version

    def setCustomTitle(self, title=None):
        """Set a custom title to display instead of the node name."""
        if title:
            base_title = title
        else:
            base_title= self.simplifyName()
        self.addPortTooltips()
        
        if not self.has_property('title'):
            self.create_property('title', base_title)
        if not self.has_property('full_title'):
            self.create_property('full_title', base_title)
        else:
            self.set_property('full_title', base_title)

        # The label sits under the node (cwl-svg): elide only very long titles
        from PyQt6.QtGui import QFontMetricsF
        font_metrics = QFontMetricsF(GraphItems.font())
        title = base_title
        if font_metrics.horizontalAdvance(title) > GraphItems.LABEL_MAX_WIDTH:
            while title and font_metrics.horizontalAdvance(title + '..') > GraphItems.LABEL_MAX_WIDTH:
                title = title[:-1]
            title += '..'
        self.set_property('title', title)
        if hasattr(self, 'view') and self.view:
            self.view.setToolTip(self.get_property('full_title') if title != base_title else '')

        self.updateNodeDisplay()

    def renameReferenceOfConnectedNode(self, old_ref:str, new_ref:str):
        """
        Rename references to a connected node in this node's CWL step.
        This is useful when a connected node's ID changes.
        Args:
            old_ref (str): The old reference ID to be replaced.
            new_ref (str): The new reference ID to replace with.
        Returns:
            None    
        """
        pass

    def renameReferenceOfSelfID(self, old_id:str, new_id:str):
        """
        Rename references to this node's ID in connected nodes' CWL steps.
        This is useful when this node's ID changes.
        Args:
            old_id (str): The old ID to be replaced.
            new_id (str): The new ID to replace with.
        Returns:
            None
        """
        pass

    def addPortTooltips(self):
        """Add tooltips to all ports of this node."""
        # Add tooltips to input ports
        self.logger_tooltip.debug(f"Adding the tooltips for node {self.name()}")
        for port in self.input_ports():
            self.logger_tooltip.debug(f"\ttooltips for port {port}")
            tooltip = self.createInputTooltip(port)
            self.setPortTooltip(port, tooltip)
        
        # Add tooltips to output ports  
        for port in self.output_ports():
            tooltip = self.createOutputTooltip(port)
            self.setPortTooltip(port, tooltip)

    def setPortTooltip(self, port, tooltip):
        """Set tooltip for a port using available methods."""
        try:
            # Method 1: Through port view
            if hasattr(port, 'view') and hasattr(port.view, 'setToolTip'):
                port.view.setToolTip(tooltip)
                return
            
            # Method 2: Direct on port
            if hasattr(port, 'setToolTip'):
                port.setToolTip(tooltip)
                return
                
            # Method 3: Through port model
            if hasattr(port, 'model') and hasattr(port.model, 'tooltip'):
                port.model.tooltip = tooltip
                
        except Exception as e:
            self.logger_tooltip.warning(f"Could not set tooltip for port {port.name()}: {e}")



    def createInputTooltip(self, port):
        """Create tooltip for input port.
        Specific node types can override it"""
        port_name = port.name()
        tooltip_lines = [f"Input: {port_name}"]
        self.logger_tooltip.debug(f"Setting up tooltip for node {self.name()} with tool {self.cwl_tool}")

        # Find the corresponding input in the cwl_tool's inputs
        if self.cwl_tool and hasattr(self.cwl_tool, 'inputs'):
            for inp in self.cwl_tool.inputs:
                port_info = self.splitPort(inp.id)
                if port_info.port_id == port_name:
                    # Add type information
                    if hasattr(inp, 'type_'):
                        port_type = inp.type_
                        if isinstance(port_type, list):
                            port_type = ', '.join(str(t) for t in port_type)
                        tooltip_lines.append(f"Type: {port_type}")
                    
                    # Add label if available
                    if hasattr(inp, 'label') and inp.label:
                        tooltip_lines.append(f"Label: {inp.label}")
                    
                    # Add description if available
                    if hasattr(inp, 'doc') and inp.doc:
                        tooltip_lines.append(f"Description: {inp.doc}")
                    
                    break  # Stop after finding the matching input
            
        return "\n".join(tooltip_lines)

    def createOutputTooltip(self, port):
        """Create tooltip for output port.
        Specific node types can override it"""
        port_name = port.name()
        tooltip_lines = [f"Output: {port_name}"]
        self.logger_tooltip.debug(f"Setting up tooltip for node {self.name()} with tool {self.cwl_tool}")

        return "\n".join(tooltip_lines)



    def simplifyName(self)-> str:
        '''
        simplify the name of the node
        by removing the file name
        '''
        n=None
        if hasattr( self.getCWL(), 'label') and self.getCWL().label:
            n=self.getCWL().label
            return n
        if hasattr( self.getCWL(), 'name') and self.getCWL().name:
            n=self.getCWL().name
            return n
        if type(self).__name__ == 'InputNode':
            return self.name().split('#')[-1]
        
        port_info = self.splitPort(self.name())
        n = port_info.step_id or port_info.port_id
        
        if not n:
            n=self.name().split('#')[-1]
        return n.lstrip('_')


    def updateNodeDisplay(self):
        """Update the node's visual display with custom title and name above."""
        
        if hasattr(self, 'view') and self.view:
            # Set the main title to the custom string
            if hasattr(self.view, 'text_item') and self.has_property('title'):
                # print(f"\n\n==== the title {self.get_property('title')} for node {self.name()}\n\n ")
                try:
                    self.view.text_item.setPlainText(self.get_property('title'))
                except Exception as e:
                    self.logger.warning(f"Failed to set node title: to {self.get_property('title')} {e}")
                # Set the font for the node name
               
                font = self.view.text_item.font()  # Get the current font
                font.setPointSize(data.configuration.get("graph_node").get('label_font_size'))  # Set the desired size for the node name
                self.view.text_item.setFont(font)



    @classmethod
    def set_base_directory(self, base_dir):
        """
        Set a global base directory to resolve relative paths.
        This allows us to avoid setting individual parent_filename for each node.
        
        Args:
            base_dir (str|Path): Base directory for resolving relative paths
        """
        try:
            self._base_dir = Path(base_dir) if base_dir else None
        except Exception as e:
            self.logger.warning(f"Failed to set base directory: {e}")
            self._base_dir = None
    


    
    def loadTool(self):
        """
        Adds a CWL configuration to the node and sets the node's name.
        
        Args:
            None: the CWL object or dict or filename containing the CWL description.
        """
        
        if hasattr(self, 'cwl_step') and self.cwl_step and hasattr(self.cwl_step, 'run') and not isinstance(self.cwl_step.run, str):
            self.logger.debug("Loading embedded tool from step run")
            self.cwl_tool = Parser(self.cwl_step.run).getCWL()
        else:
            self.logger.debug(f"Loading tool {self.cwl_filename} ")
            # print(f"Loading tool {self.workflow_filename} ({type(self.workflow_filename)})")
            self.cwl_tool = Parser( self.cwl_filename).getCWL()
        # self.set_name(self.cwl_tool.id )
        self.logger.debug(f"loaded tool {self.cwl_tool.id} from {self.cwl_filename} {save(self.cwl_tool)}")
        # print(f"loaded tool {self.cwl_tool.id} from {self.workflow_filename} {save(self.cwl_tool)}")
        # sys.exit(123)

    def setWorkflowFilename(self, filename:str):
        '''
        set the filename that calls this node (not the CWL object)
        This is typically the workflow file that contains this node
        '''
        if not isinstance(filename, (str, Path, PosixPath)):
            raise TypeError(f"Expected str or Path for filename, got {type(filename).__name__}")
        if isinstance(filename, str):
            pp = urlparse(filename)
            if pp.scheme:
                filename = Path(pp.path)
            else:
                filename = Path(filename)   
        
        self.workflow_filename=filename
    


    def setCWL(self, cwl_step:Any=None):
        '''
        Set the CWL for this node.This can be
        the CommandInputParameter, CommandOutputParameter,etc
        '''

        
        self.cwl_step = cwl_step
        if hasattr(self.cwl_step,'doc') and self.cwl_step.doc:
            if not self.has_property('documentation'):
                self.create_property('documentation', self.cwl_step.doc)
            else:
                self.set_property('documentation', self.cwl_step.doc)
        # self.fixPorts()
        self.setCWLVersion()
        self.logger.info(f"{self.name} \nSetting the CWL for {type(self.cwl_step).__name__} {self.cwl_step.id}")
        self.logger.debug(f"Set the CWL {type(self.cwl_step).__name__} to {json.dumps(save(self.cwl_step),indent=3)}")
        
    def fixPorts(self):
        '''
        fix the ports of this node based on the CWL
        This has to be implemented by the specific node types
        '''
        pass

    def setWorkflowID(self, workflow_id:str):
        '''
        set the workflow id for this node.
        This will be used to properly parse the ports
        '''
        self.workflow_id=workflow_id
    
    def splitPort(self, port:str):
        if( not self.workflow_id):
            raise ValueError("Cannot split port without workflow_id set in the node")
        return PortSplitter(port , workflow_id=self.workflow_id)

    def addEdge(self):
        """
        Adds edges between this node's ports and other nodes based on the CWL workflow.
        """

        # what type of node is this?
        if type(self).__name__ == 'OutputNode':
            k=self.addEdgeOfOutputNode()
        if type(self).__name__ == 'StepNode':
            k=self.addEdgeOfStepNodeToInputNode()
            k=self.addEdgeOfStepNodeToStepNode()


    def addEdgeOfStepNodeToStepNode(self):
        """
        Assuming this is an StepNode
        Add edges from this node to the output ports of of other StepNodes

        The edge is between the input port of this node
        which is typically the id only (e.g. input1)

        and the output port of the source node
        which is typically the full port (e.g. step1/output1)
        
        We need to find the source node in the graph
        by matching the node name with the node part of the source port
        """

        # get the list of the inpputs of this step
        success=False
        if not hasattr(self.cwl_step, 'in_') or not self.cwl_step.in_:
            return success
        for input_item in self.cwl_step.in_: # 'input' is a reserved keyword, changed to input_item
            # the input_item has the attribute source which is either a string or a list of strings

            if not hasattr(input_item, 'source') or not input_item.source: # we dont have any source (we may have defaults)
                continue
            # the id of the input port:
            ipid=input_item.id
            input_port_info = self.splitPort(ipid)
            
            # the source(s) of this input port
            ips=input_item.source
            if not isinstance( ips, list): # eg we have only defaults
                ips=[ips]
            self.logger_edges_stepstep.debug(f"Adding connections for StepNode {self.name().split('#')[-1]} ")
            for _i in ips:
                self.logger_edges_stepstep.debug(f"\t\t{_i.split('#')[-1]} -> {input_port_info.port_id}")


            for ip in ips:
                source_port_info = self.splitPort(ip)
                source_node=self.findSourceNodeInGraph(source_port_info)
                if source_node: 
                    source_node.outputs()[source_port_info.port_id].connect_to(self.inputs()[input_port_info.port_id])
                    self.logger_edges_stepstep.info(f"\u2705 Connection created between {self.name()} and {source_node.name()}")


    def findSourceNodeInGraph(self, source_port_info:PortSplitter):
        """
        Find the source node in the graph based on the source port info.
        
        Args:
            source_port (str): Parsed source port information.
        """
        if not isinstance(source_port_info, PortSplitter):
            raise ValueError("source_port_info must be an instance of PortSplitter")
        node_type="cwled.step.StepNode"  # type of node we are looking for the source port
        if source_port_info.step_id is None: return None  # this is probably a source from an InputNode
        self.logger_edges_stepstep.debug(f"Finding source node with port info {source_port_info}")
        # break down the source_port_info
        self.logger_edges_stepstep.debug(f"Looking for source node {source_port_info} ")
        debug_list=[]


        for idx, source_node in enumerate(self.graph.get_nodes_by_type(node_type)):
            self.logger_edges_stepstep.debug(f"Checking source node {source_node.name()} ")
            source_node_info= self.splitPort(source_node.name())
            debug_list.append( source_node_info.stepport )
            # if the source node name (without workflow id) matches the source port step we found it
            if source_node_info.stepport == source_port_info.step_id:
                return source_node
        self.logger_edges_stepstep.warning(
            f"\u274C Could not find a node matching {source_port_info.step_id}",
             f" in {json.dumps(debug_list, indent=2)}"
             )

        return None

        
        


    def addEdgeOfStepNodeToInputNode(self):
        """
        Assuming this is an StepNode
        Add edges from this node to the output ports of InputNodes
        """

        # get the list of the inpputs of this step
        success=False
        if not hasattr(self.cwl_step, 'in_') or not self.cwl_step.in_:
            return success
        for input_item in self.cwl_step.in_: # 'input' is a reserved keyword, changed to input_item
            # the input_item has the attribute source which is either a string or a list of strings

            if not hasattr(input_item, 'source') or not input_item.source:
                continue
            ipid=input_item.id
            input_port_info = self.splitPort(ipid)
            self.logger_edges_stepinput.debug(f"Adding connections of StepNode {self.name()} ")
            self.logger_edges_stepinput.debug(f"to its input port {input_port_info.port_id}")
            ips=input_item.source
            if not isinstance( ips, list): # eg we have only defaults
                ips=[ips]
            
            for idx, source_node in enumerate(self.graph.all_nodes()):
                    if type(source_node).__name__ == "InputNode":
                        self.logger_edges_stepinput.debug(f"Graph contains InputNode {source_node.name()}")

            for ip in ips:
                source_port_info = self.splitPort(ip)
                self.logger_edges_stepinput.debug(f"with source {source_port_info.full_port}")
                # check if we can find this node in the graph 
                # only looking in the list of InputNodes

                for idx, source_node in enumerate(self.graph.all_nodes()):
                    if type(source_node).__name__ == "InputNode" and \
                        (source_node.name() == source_port_info.full_port or \
                        source_node.name().endswith( f"#{source_port_info.full_port}" ) 
                        ):
                        source_port='source'
                        try:
                            source_node.outputs()[source_port].connect_to(self.inputs()[input_port_info.port_id])
                            self.logger_edges_stepinput.info(f"\u2705 Connection created between {self.name()} and {source_node.name()}")
                            success=True
                            break
                        except KeyError:
                            self.logger_edges_stepinput.warning(f"\u274C  Connection failed between {self.name()} and {source_node.name()}")
                            self.logger_edges_stepinput.warning(f"The nodes inputs are { self.inputs()}")
                
        # if not success:
        #     self.logger_edges.warning(f"\u274C Cannot find the source node {source_port_info.get('node')}"
                                        #   f" in the graph {json.dumps( [x.name() for x in self.graph.all_nodes()], indent=2)}")



    def addEdgeOfOutputNode(self):
        """
        Assuming this is an OutputNode
        Add edges from this node to the output ports of other nodes
        """

        # by design the name of the port for the OutputNode
        # is 'sink'
        # the source of the output is in the attribute outputSource
        # points to the output port of another node
        success=False
        my_port='sink'
        ops=self.getCWL().outputSource
        if not ops: return success
        if not isinstance( ops, list):
            ops=[ops]
        for op in ops:
            source_port_info = self.splitPort(op)
            if not source_port_info.full_port:
                self.logger_edges.critical( f"Cannot split port {op} for OutputNode {self.name()} {json.dumps(save(self.getCWL()), indent=3, default=str)}" )
                sys.exit(1)
            self.logger_edges.debug(f"Adding connections for OutputNode {self.name()} "
                                f"to its source port {source_port_info.full_port}")
            
            # check if we can find this node in the graph
            
            for idx, source_node in enumerate(self.graph.all_nodes()):
                if  type(source_node).__name__ == 'StepNode' and \
                    (source_node.name() == source_port_info.node or \
                    source_node.name().endswith( f"#{source_port_info.node}" ) 
                    ):  
                    source_port=source_port_info.port_id
                    source_node.outputs()[source_port].connect_to(self.inputs()[my_port])
                    self.logger_edges.info(f"\u2705 Connection created between {self.name()} and {source_node.name()}")
                    success=True
                    break
            
        # if not success:
        #     self.logger_edges.warning(f"\u274C Cannot find the source node {source_port_info.get('node')}"
        #                                   f" in the graph {json.dumps( [x.name() for x in self.graph.all_nodes()], indent=2)}")

        return success
    


    
    def addPorts(self, port_side='input', ports_data:Any=[]):
        """
        Adds ports (inputs or outputs) with colors based on the port's 'required' status.
        
        Args:
            port_side: Type of ports to add ('input' or 'output') not used anymore
            ports_data: List of CWL port objects.
               this can be inputs i.e. WorkflowStepInput 
               or outputs i.e. WorkflowStepOutput.
        """
        # w=self.get_property('width')
        port_font = QFont()
        port_font.setPointSize(data.configuration.get("graph_node").get('port_font_size'))
        
        self.logger_ports.info(f"Adding ports for node [{self.name().split('#')[-1]}]")
        for port in ports_data:
            
            self.logger_ports.debug(f"Received port for {save(port)} {type(port)}")
            # print(f"Received port for {save(port)} {type(port)}")
            # Get required status, handle both object and dict
            required = not is_optional(port)
            
            # cwl-svg port colours: light grey, darker when optional
            color = theme.GRAPH['port']
            if not required:
                color = theme.GRAPH['io_optional']
            # if the port has a pick value we make it grayer
            # if hasattr(port, 'pickValue') and port.pickValue:
            #     color =  # Muted grayish-green

            # depending on the input port type we will have different shape

            # painter_func = draw_rectangle_port if required else draw_triangle_port  
            # a port with a pickValue will be rectangle
            # painter_func = self.draw_rectangle_port if required else self.draw_rectangle_port
            
            # Get port ID
            port_id = None
            if hasattr(port, 'id'):
                port_info = self.splitPort(port.id)
                
            # Get port type
            if hasattr(port, 'type_'):
                port_type= port.type_  
            else:
                port_type="UNKNOWN type"

            # Extract the actual port_id for checking
            actual_port_id = port_info.port_id if port_info else None
            
            # Check if port is already registered
            if actual_port_id:
                existing_inputs = self.inputs()
                existing_outputs = self.outputs()
                if (actual_port_id in existing_inputs or 
                    actual_port_id in existing_outputs):
                    self.logger_ports.debug(f"Port {actual_port_id} already registered, skipping")
                    continue
        
            

            if re.search('InputParameter',type(port).__name__ ):
                # Set painter function: required ports=rectangle, optional=circular
                
                port_side='input' 
                # the port id follows the pattern <tool_id>/<port_id>
                # aa=port_id.split('/')
                # port_id=aa[-1]
                port_id=port_info.port_id

                try:
                    new_port = self.add_input(
                        port_id, 
                        color=color, 
                        multi_input=True
                    )
                    self.logger_ports.info(f"\u2705 {self.name().split('#')[-1]}. "
                                           f"Added Input port {port_id} (required: {required}) of type {port_type}")
                    if new_port and hasattr(new_port, 'view') and hasattr(new_port.view, 'text_item'):
                        new_port.view.text_item.setFont(port_font)
                except PortRegistrationError as e:
                    pass
            elif re.search('WorkflowStepInput',type(port).__name__ ):
                # Set painter function: required ports=rectangle, optional=circular
                port_side='input' 
                # the port id follows the pattern <tool_id>/<port_id>
                # aa=port_id.split('/')
                # port_id=aa[-1]
                port_id=port_info.port_id

                # self.logger.critical(f"The painter func is {painter_func}")
                try:
                    new_port = self.add_input(
                        port_id, 
                        color=color, 
                        multi_input=True
                    )
                    self.logger_ports.info(f"\u2705 {self.name().split('#')[-1]}. "
                                           f"Added Input port {port_id} (required: {required}) of type {port_type}")
                    if new_port and hasattr(new_port, 'view') and hasattr(new_port.view, 'text_item'):
                        new_port.view.text_item.setFont(port_font)
                except PortRegistrationError as e:
                    logger.critical(f"problem with {save(port), {e}}")
                    pass

                    
            elif re.search('OutputParameter',type(port).__name__ ):
                
                port_side='output' 
                # the port id follows the pattern <tool_id>/<port_id>
                # aa=port_id.split('/')
                # port_id=aa[-1]
                port_id=port_info.port_id
                try:
                    new_port = self.add_output(
                        port_id, 
                        color=color, 
                        painter_func=None
                    )
                    self.logger_ports.info(f"\u2705  {self.name().split('#')[-1]}. "
                                           f"Adding Output port {port_id} (required: {required}) of type {port_type}")
                
                    if new_port and hasattr(new_port, 'view') and hasattr(new_port.view, 'text_item'):
                        new_port.view.text_item.setFont(port_font)  
                except PortRegistrationError as e:
                    pass 

            self.logger_ports.debug(f"Adding {port_type} port {port_id}")




    def getCWL(self):
        """
        Get the CWL dictionary for this node.
        
        This method is a placeholder and should be overridden in subclasses.
        
        Returns:
            dict: A dictionary representing the CWL for this node.
        """

        return self.cwl_step
    
    def getData(self):
        """ alias for getCWL"""
        # print(f"Returning getCWL for {json.dumps(save(self.getCWL()), indent=2, default=str)}")
        self.fixPorts()
        return self.getCWL()
    






    def __str__(self):
        """
        Return a string representation of the CWLNode.
        Includes inputs, node information (id, cwl_filename, parent_filename), and outputs.
        """
        input_ports = []
        if hasattr(self, 'inputs') :
            for port_name, port_obj in self.inputs().items():
                input_ports.append(f"Input Port: {port_name} (Connected: {port_obj.connected_ports()})")
        inputs_str = "\n".join(input_ports) if input_ports else "No input ports"

        output_ports = []
        if hasattr(self, 'outputs') :
            for port_name, port_obj in self.outputs().items():
                output_ports.append(f"Output Port: {port_name} (Connected: {port_obj.connected_ports()})")
        outputs_str = "\n".join(output_ports) if output_ports else "No output ports"

        if type(self).__name__ == 'OutputNode':
            outputSource=self.getCWL().outputSource
            if outputSource:
                inputs_str=f"{inputs_str} (Output Source: {outputSource})"
        node_info = [
            f"  Node ID: {self.id}",
            f"  Node Name: {self.name()}",
            f"  Node Type: {type(self).__name__}",
            f"  CWL File: {self.cwl_filename if self.cwl_filename else 'N/A'}",
            f"  Parent File: {self.workflow_filename if self.workflow_filename else 'N/A'}",
            f"  Inputs: {inputs_str}" ,
            f"  Outputs: {outputs_str}" ,
            f"  CWL Class: {type(self.cwl_step)}"
        ]
        node_info_str = "\n".join(node_info)

        return f"""===\n{node_info_str} \n===\n"""

class InputNode(CWLNode,  QObject):
    '''
    This type of node is used to represent the input ports
    it is circular and has only a single output line that connects to another node's inputs
    '''
    __identifier__ = 'cwled.input'
    NODE_NAME='InputNode'
    # VIEW_CLASS = FixedSizeNodeViewer
    
    # Define signal for when input node is updated
    inputnodeUpdated = pyqtSignal(str)
    
    def __init__(self):
        # QObject.__init__(self)
        # super(InputNode, self).__init__()
        super().__init__()
        QObject.__init__(self)
        self.logger=logging.getLogger(self.__class__.__name__)
        try:
            self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        except Exception as e:
            self.logger.setLevel("DEBUG")
        # print(f"{self.properties()}")
        # sys.exit(123)
        # self.set_property('width',20)
        # self.set_property('height',20)
        self.create_property('worklow_input_id', self.id)
        self.simplifyName()
        self.add_output('source', display_name=False)
        
        self.applyNodeColors(theme.GRAPH['io'])
        self.view.setGlyph('input')
        

    def setCWL(self, cwl_step: Any = None):
        if type(cwl_step).__name__ not in ['WorkflowInputParameter','InputParameter']:
            raise TypeError(f"Expected WorkflowInputParameter, got {type(cwl_step).__name__}")
        result = super().setCWL(cwl_step)
        self.view.setGlyph(self.ioGlyph('input'))
        return result

    def createOutputTooltip(self, port):
        """Create tooltip for output port."""
        port_name = port.name()
        tooltip_lines = [f"Output: {port_name}"]
        self.logger_tooltip.debug(f"Setting up tooltip for node {self.name()} with tool {self.cwl_tool}")
        
        # Add type information if available
        if port_name == 'source':
            tooltip_lines = [f"Workflow input : {self.name().split('#')[-1]}"]
        if hasattr(self.getCWL(), 'type_'):
            port_type = self.getCWL().type_
            if isinstance(port_type, list):
                port_type = ', '.join(str(t) for t in port_type)
            tooltip_lines.append(f"Type: {port_type}")
        if hasattr(self.getCWL(), 'label') and self.getCWL().label:
            tooltip_lines.append(f"Label: {self.getCWL().label}")
        if hasattr(self.getCWL(), 'doc') and self.getCWL().doc:
            tooltip_lines.append(f"Description: {self.getCWL().doc}")
        if is_optional( self.getCWL() ):
            self.applyNodeColors(theme.GRAPH['io_optional'])
        else:
            self.applyNodeColors(theme.GRAPH['io'])
        return "\n".join(tooltip_lines)


    

    def onNodeDoubleClicked(self,node):
        """
        Calls the InputDialog to edit the input parameter when the node is double-clicked.
        Args:
            node: The node that was double-clicked
        """
        self.logger.debug(f"InputNode.on_double_clicked called for node {self.name()}")
        
        self.logger.debug(
            f"Edit button clicked, opening InputDialog for {type(self.getCWL()).__name__}"
        )
        # node_width=self.get_property('width') 
        # node_height=self.get_property('height')
        dialog = InputDialog(
            parent=self.getDialogParent(),
            input_parameter=self.getCWL(),
            input_parameter_type='WorkflowInputParameter'
        )
        
        # Position the dialog next to the main window
        dialog.show_next_to_main_window()
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get inputs from the dialog
            inputs = dialog.getData()
            self.logger.debug(f"Dialog returned: {inputs}")
            
            self.setCWL(inputs)
            self.set_name( self.getCWL().id )
            # Update the node's display with the new name/title
            self.setCustomTitle()
            
            # Refresh the node view to reflect any changes
            # if hasattr(self, 'view') and self.view:
                # self.view.draw_node()
            # self.set_property('width', node_width)
            # self.set_property('height', node_height)
            # Emit the inputnodeUpdated signal to notify other components
            self.inputnodeUpdated.emit(self.id)

    def renameReferenceOfConnectedNode(self, old_ref:str, new_ref:str):
        """
        Rename references to a connected node in this InputNode's CWL step.
        
        For InputNodes, this is a no-op because InputNodes do not reference other nodes.
        InputNodes only output data and do not maintain references to other nodes in their
        CWL structure.
        
        Args:
            old_ref (str): The old reference ID to be replaced (unused).
            new_ref (str): The new reference ID to replace with (unused).
        
        Returns:
            None
        """
        # since the input node does not reference any other nodes we don't have to do anything
        pass
    
    def renameReferenceOfSelfID(self, old_id:str, new_id:str):
        """
        Rename this InputNode's ID in its own structure.
        
        For InputNodes, this updates the graph node's name to reflect the new ID.
        The CWL WorkflowInputParameter's id is already updated by the InputDialog
        before this method is called.
        
        Args:
            old_id (str): The old ID of this node (unused, kept for interface consistency).
            new_id (str): The new ID to set for this node.
        
        Returns:
            None
        
        Side Effects:
            - Updates the node's display name in the graph to new_id
        """
        self.set_name(new_id)

class OutputNode(CWLNode,QObject):
    '''
    This type of node is used to represent the output port
    it is circular and has only a single input line that connects to another node's outputs
    '''
    __identifier__ = 'cwled.output'
    NODE_NAME='OutputNode'
    
    # Define signal for when output node is updated
    outputnodeUpdated = pyqtSignal(str)
    
    def __init__(self):
        # QObject.__init__(self)
        # super(OutputNode, self).__init__()
        # BaseNodeCircle.__init__(self)
        CWLNode.__init__(self)
        QObject.__init__(self)
        self.logger=logging.getLogger(self.__class__.__name__)
        try:
            self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        except Exception as e:
            self.logger.setLevel("DEBUG")
        self.create_property('worklow_output_id', self.id)
        self.add_input( 'sink', multi_input=True, display_name=False)
        self.applyNodeColors(theme.GRAPH['io'])
        self.view.setGlyph('output')
        
    def setCWL(self, cwl_step: Any = None):
        if type(cwl_step).__name__ not in ['WorkflowOutputParameter']:
            raise TypeError(f"Expected WorkflowOutputParameter, got {type(cwl_step).__name__}")
        if is_optional( cwl_step ):
            self.applyNodeColors(theme.GRAPH['io_optional'])
        else:
            self.applyNodeColors(theme.GRAPH['io'])
        result = super().setCWL(cwl_step)
        self.view.setGlyph(self.ioGlyph('output'))
        return result
    
    def createInputTooltip(self, port):
        """Create tooltip for input port."""
        port_name = port.name()
        tooltip_lines = [f"Input: {port_name}"]
        self.logger_tooltip.debug(f"Setting up tooltip for node {self.name()} with tool {self.cwl_tool}")
        # Add type information if available
        if port_name == 'sink':
            tooltip_lines = [f"Workflow output : {self.name().split('#')[-1]}"]
        if hasattr(self.getCWL(), 'type_'):
            port_type = self.getCWL().type_
            if isinstance(port_type, list):
                port_type = ', '.join(str(t) for t in port_type)
            tooltip_lines.append(f"Type: {port_type}")
        if hasattr(self.getCWL(), 'label') and self.getCWL().label:
            tooltip_lines.append(f"Label: {self.getCWL().label}")
        
        if hasattr(self.getCWL(), 'pickValue') and self.getCWL().pickValue:
            tooltip_lines.append(f"Conditional Value: {self.getCWL().pickValue}")
        if hasattr(self.getCWL(), 'doc') and self.getCWL().doc:
            tooltip_lines.append(f"Description: {self.getCWL().doc}")
            
        return "\n".join(tooltip_lines)

    
    def onNodeDoubleClicked(self, node):
        """
        Calls the OutputDialog to edit the output parameter when the node is double-clicked.
        Args:
            node: The node that was double-clicked
        """
        self.logger.debug(f"OutputNode.on_double_clicked called for node {node.name()}")
        
        # Only proceed if the clicked node is this node
        if node.id != self.id:
            self.logger.debug(f"Ignoring double-click: node {node.id} != this node {self.id}")
            return
            
        self.logger.debug(f"Processing double-click on output node {self.name()}")
        
        self.logger.debug(
            f"Edit button clicked, opening OutputDialog for {type(self.getCWL()).__name__}"
        )
        
        dialog = OutputDialog(
            parent=self.getDialogParent(),
            output_parameter=self.getCWL()
        )
        
        # Position the dialog next to the main window
        dialog.show_next_to_main_window()
        outputSource=self.getCWL().outputSource
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get outputs from the dialog
            outputs = dialog.getData()
            # print(f"Dialog returned: {save(outputs)}")
            outputs.outputSource=outputSource
            
            self.setCWL(outputs)
            self.set_name( self.getCWL().id )
            # Update the node's display with the new name/title
            self.setCustomTitle()
            
            # Refresh the node view to reflect any changes
            # if hasattr(self, 'view') and self.view:
                # self.view.draw_node()
            
            # Emit the outputnodeUpdated signal to notify other components
            self.outputnodeUpdated.emit(node.id)
    


    def setInputSource( self, input_id, source_node,source_port):
        """
        Add a source to this output node's outputSource list.
        """
        s=self.splitPort( f"{source_node}/{source_port}")

        # Build the source string
        if s.port_id != 'source':
            source_str=f"{s.step_id}/{s.port_id}"
        else:
            source_str=s.step_id

        # Collect existing outputSources
        existing=[]
        if isinstance(self.cwl_step.outputSource, list):
            existing=list(self.cwl_step.outputSource)
        elif self.cwl_step.outputSource:
            existing=[ self.cwl_step.outputSource]

        # Normalize existing entries for comparison
        normalized=[ self.splitPort(op).full_port for op in existing]
        if source_str not in normalized:
            existing.append( source_str )

        if len(existing)==1:
            self.cwl_step.outputSource=existing[0]
        else:
            self.cwl_step.outputSource=existing


    def removeInputSource(self, 
                          input_id: str,
                          source_node: str,
                          source_port: str):
        """
        Remove the input source for this output node.
        Since an OutputNode has only one input ('sink'), this clears the outputSource.
        """
        # print(f"Removing input source {source_node} / {source_port} from output node {self.name()}")
        step_id=self.splitPort(source_node).port_id  # since this is the name of the node we get the port_id with the anme of the node (not step_id)
        source_port_str= f"{step_id}/{source_port}"
        # print(f"Removing source port {source_port_str} from output node {self.name()}")
        # print(f"With output Source {self.cwl_step.outputSource}")
        if hasattr(self.cwl_step, 'outputSource'):
            self.logger.debug(f"Removing outputSource from {self.name()}")
            if isinstance(self.cwl_step.outputSource, str): 
                self.cwl_step.outputSource = None
            elif isinstance(self.cwl_step.outputSource, list):
                self.cwl_step.outputSource  = [s for s in self.cwl_step.outputSource  if self.splitPort(s).stepport != source_port_str]
                if len(self.cwl_step.outputSource) == 0:
                    self.cwl_step.outputSource = None
            # print(f"After update output Source {self.cwl_step.outputSource}")
            self.outputnodeUpdated.emit(self.id)
            return

    def renameReferenceOfConnectedNode(self, old_ref:str, new_ref:str):
        """
        Rename references to old_ref in connected nodes to new_ref.
        Handles both formats:
        - Direct node reference (e.g., InputNode: "input1")
        - Node/port reference (e.g., StepNode: "step1/output1")
        """
        os=[]
        if isinstance(self.cwl_step.outputSource, list): 
            os=self.cwl_step.outputSource
        else: 
            os=[ self.cwl_step.outputSource]
        for o in os:
            # Check if this is a direct reference (InputNode) or node/port reference (StepNode)
            if '/' in o:
                # Node/port format (e.g., "step1/output1")
                d=self.splitPort( o )
                if d.node == old_ref:
                    if d.port_id != 'source':
                        new_port=f"{new_ref}/{d.port_id}"
                    else:
                        new_port=new_ref
                    os.remove(o)
                    os.append(new_port)
                    self.logger.debug(f"Renaming reference in outputSource from {old_ref} to {new_ref}")
            else:
                # Direct node reference (e.g., "input1" from InputNode)
                if o == old_ref:
                    os.remove(o)
                    os.append(new_ref)
                    self.logger.debug(f"Renaming direct reference in outputSource from {old_ref} to {new_ref}")
        if len(os)==1:
            self.cwl_step.outputSource=os[0]
        else:
            self.cwl_step.outputSource=os

    def renameReferenceOfSelfID(self, old_id:str, new_id:str):
        """
        Rename this OutputNode's ID in its own structure.
        
        For OutputNodes, this updates the graph node's name to reflect the new ID.
        The CWL WorkflowOutputParameter's id is already updated by the OutputDialog
        before this method is called.
        
        Args:
            old_id (str): The old ID of this node (unused, kept for interface consistency).
            new_id (str): The new ID to set for this node.
        
        Returns:
            None
        
        Side Effects:
            - Updates the node's display name in the graph to new_id
        """
        self.set_name(new_id)


class StepNode(CWLNode, QObject):
    """
    Create the basic node for a tool.

    This class represents a step node in the CWL (Common Workflow Language) graph.
    It requires a name (coming from the "label" of the tool), a list of inputs, and a list of outputs.

    Attributes:
        __identifier__ (str): Unique node identifier domain.
        NODE_NAME (str): Name of the node.
        cwl_tool (CWLobject): Dictionary containing the CWL description of the node loaded from its file.
        cwl_step (Any): Object holding the step CWL 
        logger (logging.Logger): Logger for the class.
        stepnodeUpdated (pyqtSignal): Signal emitted when the step node is updated.
    """
    # unique node identifier domain.
    __identifier__ = 'cwled.step'

    NODE_NAME = 'StepNode'

    
    # Define the stepnodeUpdated signal
    stepnodeUpdated = pyqtSignal(str)

    def __init__(self):
        """
        Initialize the StepNode.

        This constructor initializes the StepNode, sets up the logger, and logs the creation of the node.
        """
        # QObject.__init__(self)
        # super(StepNode, self).__init__()
        super().__init__()
        QObject.__init__(self)
        
        self.logger=logging.getLogger(self.__class__.__name__)
        try:
            self.logger.setLevel(data.configuration.get('logLevel',{}).get(self.__class__.__name__, 'DEBUG'))
        except Exception as e:
            self.logger.setLevel("DEBUG")
        self.logger.debug(f"Adding node {self.name()}")  
        
        self.create_property('worklow_step_id', self.id)

        # We'll connect to the double-click signal later when the node is added to a graph
        # Don't try to connect here as self.graph may not exist yet

    def setCWL( self, cwl_step:Any=None):
        """
        Set the CWL for this node.

        Args:
            cwl_step: CWL object or dict containing the CWL description of the node.
        """
        if type( cwl_step).__name__ not in ['WorkflowStep']:
            raise TypeError(f"Expected WorkflowStep, got {type(cwl_step).__name__}")
        if not self.workflow_filename :
            raise ValueError("Cannot set CWL without filename set in the node")
        super().setCWL(cwl_step)
        self.setCWLFilename()
        if not self.cwl_filename :
            raise ValueError("Cannot set CWL without the CWL document filename set in the node")

        # print(f"The filename is {self.workflow_filename}")
        # print(f"The run filename is {self.cwl_step.run}")
        # print(f"The cwl filename is {self.cwl_filename}")

        self.loadTool( self.cwl_filename)

    def setCWLFilename(self):
        """Constructs the absolute path to the CWL document for this step.

        This method resolves the path to the tool's CWL file. It combines
        the directory of the parent workflow file (`self.workflow_filename`) with the
        relative path from the `run` field of the workflow step
        (`self.cwl_step.run`). If `run` is a URI, its path is extracted.
        The resulting absolute path is stored in `self.cwl_filename`.

        This is crucial for loading the tool's definition, as `run` often
        contains a relative path or a URI.
        """
        
        runfn = None
        if hasattr(self.cwl_step, 'run') and self.cwl_step.run:
            runfn = self.cwl_step.run
        # print(f"setCWLFilename run filename is {runfn}")
        if runfn:
            if isinstance(runfn, str):
                parsed_runfn = urlparse(runfn)
                runfn_path = parsed_runfn.path if parsed_runfn.scheme else runfn

                # the runfn_path can either be absolute or relative to the workflow file
                # if it is absolute we use it as is
                if os.path.isabs(runfn_path):
                    self.cwl_filename = runfn_path
                    # print(f"The filename is {self.cwl_filename}. We keep it as is.")
                else:
                    # print(f"Joining dirname of {self.workflow_filename} with {runfn_path}   to get CWL filename")
                    self.cwl_filename = os.path.abspath(
                        os.path.join(
                            os.path.dirname(self.workflow_filename), runfn_path
                        )
                    )
                    # print(f"The filename is {self.cwl_filename}")
            else:
                self.cwl_filename = self.workflow_filename

    def createInputTooltip(self, port):
        """Create tooltip for input port."""
        port_name = port.name()
        tooltip_lines = [f"Input: {port_name}"]
        self.logger_tooltip.debug(f"Setting up tooltip for node {self.name()} with tool {self.cwl_tool}")
        # Add type information if available from the cwl_step
        if hasattr(self, 'cwl_tool') and self.cwl_tool:
            for input_def in self.cwl_tool.inputs:
                self.logger_tooltip.debug(f"Input_def {input_def}, {input_def.id}")
                if self.splitPort( input_def.id).port_id == port_name:
                    self.logger_tooltip.debug(f"We have a match to port {port_name}")
                    if hasattr(input_def, 'label'):
                        tooltip_lines.append(f"Label: {input_def.label}")
                    if hasattr(input_def, 'name'):
                        tooltip_lines.append(f"Name: {input_def.label}")
                    if hasattr(input_def, 'type_'):
                        tooltip_lines.append(f"Type: {str(input_def.type_)}")
                    if hasattr( input_def , 'pickValue') and input_def.pickValue:
                        tooltip_lines.append(f"Conditional Value : {input_def.pickValue}")
                    if hasattr(input_def, 'doc'):
                        tooltip_lines.append(f"Description: {input_def.doc}")
                    self.logger_tooltip.debug(f"The tooltip is {tooltip_lines}")
                    break
            for input_def in self.cwl_step.in_:
                self.logger_tooltip.debug(f"Input_def {input_def}, {input_def.id}")
                if self.splitPort( input_def.id).port_id == port_name:
                    self.logger_tooltip.debug(f"We have a match to port {port_name}")
                    if hasattr( input_def , 'pickValue') and input_def.pickValue:
                        tooltip_lines.append(f"Conditional Value: {input_def.pickValue} " + 
                                             f"from: {'|'.join([self.splitPort(x).port_id for x in input_def.source])}")
                    self.logger_tooltip.debug(f"The tooltip is {tooltip_lines}")
                    break

        return "\n".join(tooltip_lines)
    
    def createOutputTooltip(self, port):
        """Create tooltip for output port."""
        port_name = port.name()
        tooltip_lines = [f"Output: {port_name}"]
        self.logger_tooltip.debug(f"Setting up tooltip for node {self.name()} with tool {self.cwl_tool}")
        
        # Add type information if available
        if hasattr(self, 'cwl_tool') and self.cwl_tool:
            for output_def in self.cwl_tool.outputs:
                self.logger_tooltip.debug(f"Output def {output_def}, {output_def.id}")
                if self.splitPort( output_def.id).port_id == port_name:
                    if hasattr(output_def, 'label'):
                        tooltip_lines.append(f"Label: {output_def.label}")
                    if hasattr(output_def, 'name'):
                        tooltip_lines.append(f"Name: {output_def.label}")
                    if hasattr(output_def, 'type_'):
                        tooltip_lines.append(f"Type: {output_def.type_}")
                    if hasattr(output_def, 'doc'):
                        tooltip_lines.append(f"Description: {output_def.doc}")
                    break
        return "\n".join(tooltip_lines)

    def loadTool(self ,filename:Union[str,Path,PosixPath]=None):
        """
        Add the CWL part that corresponds to this node.

        This method adds the CWL object to the node and loads the CWL of this tool.

        Args:
            filename: filename containing the CWL description of the node.
        """

        super().loadTool()
        # cwl-svg icons: workflow and command line tool steps only
        if self.cwl_tool.class_ == 'Workflow':
            self.view.setGlyph('workflow')
            self.is_workflow = True
        elif self.cwl_tool.class_ == 'CommandLineTool':
            self.view.setGlyph('tool')
        else:
            self.view.setGlyph(None)
        if hasattr(self.cwl_step, 'when') and self.cwl_step.when:
            self.applyNodeColors(theme.GRAPH['step_conditional'])
        else:
            self.applyNodeColors(theme.GRAPH['step'])
        self.logger.debug(f"For StepNode: {self.name()} - class {self.cwl_tool.class_}")
        
        self.addInputs()
        
        self.addOutputs()

    def addInputs(self):
        # add the inputs to the node
        # the inputs we add are coming from the tool definition (CWL file) not the step
        # the ports that are referenced in the step should be a subset of these
        self.logger.debug(f"Adding inputs for {json.dumps(save(self.cwl_tool), indent=2)}")
        inputs = []
        if not hasattr(self.cwl_tool, 'inputs'):
            raise ValueError(
                f"Tool does not have an 'inputs' attribute. {self.cwl_tool.attrs}"
            )
        if not hasattr(self.cwl_step, 'in_'):
            raise ValueError(
                f"Tool does not have an 'in_' attribute. {self.cwl_tool.attrs}"
            )
        self.logger_ports.info(f"{self.name()}. Adding Input ports {json.dumps([ x.id for x in self.cwl_tool.inputs],indent=2)}")
        self.addPorts('input', self.cwl_tool.inputs)
        self.logger_ports.info(f"{self.name()}. Adding In_ ports {json.dumps([ x.id for x in self.cwl_step.in_],indent=2)}")
        self.addPorts('input', self.cwl_step.in_)

    def addOutputs(self):
        # add the outputs to the node
        # the outputs we add are coming from the tool definition (CWL file) not the step
        # the ports that are referenced in the step should be a subset of these
        self.logger.debug(f"Adding outputs for {json.dumps(save(self.cwl_tool), indent=2)}")
        outputs = []
        if hasattr(self.cwl_tool, 'outputs'):
            outputs = self.cwl_tool.outputs
        else:
            raise ValueError(
                f"Tool {self.cwl_filename} does not have an 'outputs' attribute."
            )
             
        self.addPorts('output', outputs)

    def onNodeDoubleClicked(self, node):
        """
        Calls the StepDialog to edit the step when the node is double-clicked.
        Args:
            node: The node that was double-clicked
        """
        self.logger.debug(f"StepNode.on_double_clicked called for node {node.name()}")
        
        # Only proceed if the clicked node is this node
        if node.id != self.id:
            self.logger.debug(f"Ignoring double-click: node {node.id} != this node {self.id}")
            return
            
        self.logger.debug(f"Processing double-click on step node {self.name()}")
        
        self.logger.debug(
            f"Edit button clicked, opening StepDialog for {type(self.getCWL()).__name__}"
        )
        # print(f"Will open stepdialog with the inputs")
        # print(f"{json.dumps(save(self.cwl_tool.inputs),indent=2)}")
        
        dialog = StepDialog(
            parent=self.getDialogParent(),
            cwl_step=self.getCWL(),
            cwl_step_inputs=self.cwl_tool.inputs,
            workflow_id=self.workflow_id
        )
        dialog.setDefaults()
        
        # Position the dialog next to the main window
        dialog.show_next_to_main_window()
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get step data from the dialog
            step_data = dialog.getData()
            self.logger.debug(f"Dialog returned: {step_data}")
            
            self.setCWL(step_data)
            
            # Update the node's display with the new name/title
            self.setCustomTitle()
            # node.set_width(NODE_STEP_WIDTH)
            # Emit the stepnodeUpdated signal to notify other components
            self.stepnodeUpdated.emit(node.id)
        # sys.exit(123)

    def removeInputSource(self, 
                          target_port: str,
                          source_node: str = None,
                          source_port: str = None):
        """
        Finds the corresponding input in the step's 'in_' list and clears its 'source'.
        """
        self.logger.debug(f"Attempting to remove source for input '{target_port}' from step '{self.name()}'")
        step_id= self.splitPort(source_node).port_id if source_node else None
        if source_port == 'source':
            source_port_str= step_id
        else:  
            source_port_str= f"{step_id}/{source_port}" if source_node else source_port
        for idx,i in enumerate(self.cwl_step.in_):
            d = self.splitPort(i.id)
            if d.port_id == target_port:
                if hasattr(i, 'source'):
                    self.logger.info(f"Clearing source for input '{target_port}' in step '{self.name()}'")
                    if isinstance(i.source, str):
                        i.source = None
                    elif isinstance(i.source, list):
                        i.source = [s for s in i.source if s != source_port_str]
                        if len(i.source) == 0:
                            i.source = None
                       
                    if i.source is None and i.default is None:
                        self.logger.debug(f"Source for input '{target_port}' is now None")
                        del self.cwl_step.in_[idx]
                    # If the input now has no source and no default, it might be invalid.
                    # cwl-utils should handle this, but we could also remove it if it's truly empty.
                    # For now, just clearing the source is safest.
                    self.stepnodeUpdated.emit(self.id)
                    return


    def setInputSource( self, input_id, source_node,source_port):
        """
        for a step node we need to add a source in its inputs list
        """
        module=get_cwl_module(self.cwl_version)
        # go through the inputs
        
        # print(f"THe current CWL is {json.dumps(save(self.cwl_step), indent=3, default=str)}")
        # print(f"This stepnode is of version {self.cwl_version}")
        
        # print(f"We will connect input {input_id} to {source_node}/{source_port}")
        # sys.exit(123)
        # go through the inputs until we find the one we want
        found_port=False # keep track if we have found this port or we need to add it
        s=self.splitPort( f"{source_node}/{source_port}")
        for i in self.cwl_step.in_:
            d=self.splitPort( i.id )
            # print(f"Checking for the input we wanted {save(i)} , {d.port_id}")
            # split the i.id to get the actual id.
            if d.port_id != input_id: continue
            found_port=True
            # print("Found the port")
            # print(f"The port is {d}")
            # print(f"The source is {s}")
            if s.port_id != 'source':
                source_str=s.stepport
            else: 
                source_str=s.step_id
            # print(f"The source_str is {source_str}")

            if hasattr(i, 'source') :
                if not i.source: # e.g. when we have only a default value
                    i.source=[]
                # print(f"existing source is {i.source}")
                s=[]
                if not isinstance( i.source , list):
                    s=[i.source]
                else:
                    s=i.source
                s=[ self.splitPort( sp ).stepport for sp in s]
                if source_str not in s:
                    s.append( source_str )
                    # print(f"Appending {source_str}")
                if len(s)==1:
                    i.source=s[0]
                else:
                    i.source=s
                # print(f"source is now {i.source}")
                # sys.exit(123)
            # else:
            #     print(f"{save(i)} did not have a source !!!")

        if not found_port: # we need to create a new id for this connection
            if source_port == 'source':
                source_str=s.step_id
            else :
                source_str=s.stepport
            # print(f"Did not find port {input_id}, creating a new one with {s.step_id}")
            self.cwl_step.in_.append( 
                module.WorkflowStepInput(
                    id=input_id,
                    source=source_str
                )
            )
        
        # for i in self.cwl_step.in_:
        #     if not i.source and not i.default:
        #         print(f"Removing empty source from {save(i)}")
        #         self.cwl_step.in_.remove(i)

        # print(f"THe new CWL is {json.dumps(save(self.cwl_step), indent=3, default=str)}")


    def renameReferenceOfConnectedNode(self, old_ref:str, new_ref:str):
        """
        Rename references to a connected node in this StepNode's input sources.
        
        Handles both reference formats:
        - Direct node reference (e.g., InputNode: "input1")
        - Node/port reference (e.g., StepNode: "step1/output1")
        
        This method iterates through all inputs of this StepNode (in the cwl_step.in_ list)
        and updates any source references that match old_ref to new_ref. Sources can be
        either a single string or a list of strings (for multiple input sources).
        
        Args:
            old_ref (str): The old reference ID to be replaced. Can be a simple node name
                          (e.g., "input1") or the node part of a node/port reference
                          (e.g., "step1" in "step1/output1").
            new_ref (str): The new reference ID to replace with.
        
        Returns:
            None
        
        Side Effects:
            - Modifies source attributes in self.cwl_step.in_ to update references
            - Logs debug messages for each renamed reference
        
        Examples:
            >>> # Direct reference from InputNode
            >>> step.cwl_step.in_[0].source = "input1"
            >>> step.renameReferenceOfConnectedNode("input1", "newInput1")
            >>> # Result: in_[0].source = "newInput1"
            
            >>> # Node/port reference from another StepNode
            >>> step.cwl_step.in_[0].source = "step1/output1"
            >>> step.renameReferenceOfConnectedNode("step1", "newStep1")
            >>> # Result: in_[0].source = "newStep1/output1"
        """
        for i in self.cwl_step.in_: #source is a WorkflowStepInput 
            if hasattr(i, 'source') and i.source:
                s=[]
                if not isinstance( i.source , list):
                    s=[i.source]
                else:
                    s=i.source
                for idx,source_str in enumerate(s):
                    # Check if this is a direct reference (InputNode) or node/port reference (StepNode)
                    if '/' in source_str:
                        # Node/port format (e.g., "step1/output1")
                        d=self.splitPort( source_str )
                        if d.node == old_ref:
                            new_port=f"{new_ref}/{d.port_id}"
                            s[idx]=new_port
                            self.logger.debug(f"Renaming reference in input source from {old_ref} to {new_ref}")
                    else:
                        # Direct node reference (e.g., "input1" from InputNode)
                        if source_str == old_ref:
                            s[idx]=new_ref
                            self.logger.debug(f"Renaming direct reference in input source from {old_ref} to {new_ref}")
                if len(s)==1:
                    i.source=s[0]
                else:
                    i.source=s

    def renameReferenceOfSelfID(self, old_ref:str, new_ref:str):
        """
        Rename this StepNode's ID in its own input and output port IDs.
        
        When a StepNode's ID changes, all of its input and output port IDs must be updated
        because they include the step ID as a prefix (e.g., "step1/input1", "step1/output1").
        This method updates both the input port IDs (in cwl_step.in_) and output port IDs
        (in cwl_step.out) to use the new step ID.
        
        Args:
            old_ref (str): The old ID of this step node.
            new_ref (str): The new ID to set for this step node.
        
        Returns:
            None
        
        Side Effects:
            - Updates all input port IDs in self.cwl_step.in_ from "old_ref/port" to "new_ref/port"
            - Updates all output port IDs in self.cwl_step.out from "old_ref/port" to "new_ref/port"
            - Updates the node's display name in the graph to new_ref
        
        Examples:
            >>> # Before: step has ID "step1" with input "step1/input1"
            >>> step.renameReferenceOfSelfID("step1", "myNewStep")
            >>> # After: input ID is now "myNewStep/input1"
        """
        def renamed(port_id):
            # keep the document part of full ids (file:///wf.cwl#step/port)
            d=self.splitPort( port_id )
            if d.node != old_ref:
                return port_id
            new_port=f"{new_ref}/{d.port_id}"
            return f"{d.filename}#{new_port}" if d.filename else new_port

        for i in self.cwl_step.in_: #source is a WorkflowStepInput
            i.id=renamed( i.id )
        
        outputs=[]
        for o in self.cwl_step.out: # a WorkflowStepOutput or its id
            output_id = renamed( o if isinstance(o, str) else o.id )
            if isinstance(o, str):
                outputs.append(output_id)
            else:
                o.id=output_id
                outputs.append(o)
        self.cwl_step.out=outputs

        self.set_name(new_ref)

    def getCWLTool(self):
        """
        Get the CWL tool object for this step node.

        Returns:
            Any: The CWL tool object associated with this step node.
        """
        return self.cwl_tool





def is_uri(path):
    """
    Determine if a path is a URI or a local filesystem path.
    
    Args:
        path (str): The path to check
        
    Returns:
        bool: True if the path is a URI, False if it's a local path
    """
    if not isinstance(path, str):
        return False
        
    # Parse the URL
    parsed = urlparse(path)
    
    # Check if it has a scheme (like http://, file://, etc.)
    has_scheme = bool(parsed.scheme)
    
    # For Windows paths like "C:/folder", parsed.scheme would be "C"
    # So we need an extra check to exclude single-letter schemes
    windows_drive_letter = len(parsed.scheme) == 1 and Path(path).exists()
    
    return has_scheme and not windows_drive_letter