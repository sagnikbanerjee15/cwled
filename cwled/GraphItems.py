"""Rabix Composer look for the workflow graph.

OdenGraphQt draws nodes as titled boxes.  The items here draw them the way
Composer's graph library (cwl-svg, "rabix-dark" theme) does instead: a grey
ring around a filled circle that carries the node icon, ports spread over the
ring, the node label underneath and the port labels shown on hover.  Edges are
thin grey curves with a halo in the canvas colour, and selecting something
fades the rest of the graph.
"""
import math
import weakref

from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QEvent, QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter,
                         QPainterPath, QPainterPathStroker, QPen)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (QApplication, QGraphicsItem, QHBoxLayout,
                             QPushButton, QWidget)

from OdenGraphQt.constants import PipeLayoutEnum, PortTypeEnum
from OdenGraphQt.qgraphics.node_abstract import AbstractNodeItem
from OdenGraphQt.qgraphics.node_base import NodeItem
from OdenGraphQt.qgraphics.pipe import LivePipeItem, PipeItem
from OdenGraphQt.qgraphics.port import PortItem

import theme

# cwl-svg geometry
NODE_RADIUS = 30            # GraphNode.radius
PORT_RADIUS = 7             # IOPort.radius
PORT_ARC = 140              # degrees of the ring used by each side's ports
INNER_RATIO = 0.75          # inner circle radius / ring radius
LABEL_OFFSET = 30           # node label baseline below the ring
PORT_LABEL_GAP = 10         # port label distance from the port centre
LABEL_STROKE = 4            # label halo ($label-stroke-width)
RING_WIDTH = 2              # $node-outer-stroke-width
EDGE_WIDTH = 2              # $edge-inner-stroke-width
EDGE_HALO = 7               # $edge-outer-stroke-width (rabix-dark)
EDGE_TIP_OFFSET = 16        # edge hover label above the cursor
FONT_SIZE = 13              # Composer $font-size-base (px)
PORT_FONT_SIZE = 12         # .9em
MIN_SCALE, MAX_SCALE = 0.2, 2.0
LABEL_MAX_WIDTH = 400       # longer node labels are elided

# cwl-svg node icons (graph-node.ts): viewBox, placement around the node
# centre and the SVG shapes.
_ICONS = {
    'workflow': ('0 0 400.01 399.88', (-9, -10, 20, 20),
                 '<path d="M400,200a80,80,0,0,1-140.33,52.53L158.23,303.24a80,80,0,1,1-17.9-35.77'
                 'l101.44-50.71a80.23,80.23,0,0,1,0-33.52L140.33,132.53a79.87,79.87,0,1,1,17.9-35.77'
                 'l101.44,50.71A80,80,0,0,1,400,200Z" transform="translate(0.01 -0.16)"/>'),
    'tool': ('0 0 398.39 397.78', (-10, -8, 20, 15),
             '<polygon points="38.77 397.57 0 366 136.15 198.78 0 31.57 38.77 0 200.63 198.78 38.77 397.57"/>'
             '<rect x="198.39" y="347.78" width="200" height="50"/>'),
    'file_input': ('0 0 499 462.86', (-11, -10, 20, 20),
                   '<path d="M386.06,0H175V58.29l50,50V50H337.81V163.38h25l86.19.24V412.86H225V353.71'
                   'l-50,50v59.15H499V112.94Zm1.75,113.45v-41l41.1,41.1Z"/>'
                   '<polygon points="387.81 1.06 387.81 1.75 387.12 1.06 387.81 1.06"/>'
                   '<polygon points="290.36 231 176.68 344.68 141.32 309.32 194.64 256 0 256 0 206 '
                   '194.64 206 142.32 153.68 177.68 118.32 290.36 231"/>'),
    'file_output': ('0 0 499 462.86', (-7, -11, 20, 20),
                    '<polygon points="387.81 1.06 387.81 1.75 387.12 1.06 387.81 1.06"/>'
                    '<polygon points="499 231 385.32 344.68 349.96 309.32 403.28 256 208.64 256 208.64 206 '
                    '403.28 206 350.96 153.68 386.32 118.32 499 231"/>'
                    '<path d="M187.81,163.38l77.69.22H324V112.94L211.06,0H0V462.86H324V298.5H274V412.86H50V50'
                    'H162.81V163.38Zm25-90.92,41.1,41.1-41.1-.11Z"/>'),
    'input': ('0 0 499 365', (-11, -10, 20, 20),
              '<path d="M316.5,68a181.72,181.72,0,0,0-114.12,40.09L238,143.72a132.5,132.5,0,1,1,1.16,214.39'
              'L203.48,393.8A182.5,182.5,0,1,0,316.5,68Z" transform="translate(0 -68)"/>'
              '<polygon points="290.36 182 176.68 295.68 141.32 260.32 194.64 207 0 207 0 157 194.64 157 '
              '142.32 104.68 177.68 69.32 290.36 182"/>'),
    'output': ('0 0 500.36 365', (-9, -10, 20, 20),
               '<path d="M291.95,325.23a134,134,0,0,1-15.76,19,132.5,132.5,0,1,1,0-187.38,133.9,133.9,0,0,1,'
               '16.16,19.55l35.81-35.81A182.5,182.5,0,1,0,327.73,361Z" transform="translate(0 -68)"/>'
               '<polygon points="500.36 182 386.68 295.68 351.32 260.32 404.64 207 210 207 210 157 404.64 157 '
               '352.32 104.68 387.68 69.32 500.36 182"/>'),
}
_renderers = {}


def _color(key):
    return QColor(*theme.GRAPH[key][:3])


def font(pixel_size=FONT_SIZE):
    """Graph text font (the UI font at a fixed pixel size, as in Composer)."""
    graph_font = QFont(QApplication.font())
    graph_font.setPixelSize(pixel_size)
    return graph_font


def labelScale(view_scale):
    """cwl-svg keeps labels readable when zoomed out (Workflow.scaleAtPoint)."""
    view_scale = min(max(view_scale, MIN_SCALE), MAX_SCALE)
    return 1 + (1 - view_scale) / (view_scale * 2)


def _renderer(name):
    if name not in _renderers:
        view_box, _, body = _ICONS[name]
        fill = theme.GRAPH['background']
        colour = '#{:02x}{:02x}{:02x}'.format(*fill[:3])
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">'
               f'<g fill="{colour}" stroke="{colour}" stroke-width="3" stroke-linecap="round">'
               f'{body}</g></svg>')
        _renderers[name] = QSvgRenderer(QByteArray(svg.encode()))
    return _renderers[name]


def _drawIcon(painter, name, centre):
    """Draw a cwl-svg node icon centred on the node (SVG 'meet' scaling)."""
    if name not in _ICONS:
        return
    view_box, (x, y, width, height), _ = _ICONS[name]
    box_w, box_h = (float(v) for v in view_box.split()[2:])
    scale = min(width / box_w, height / box_h)
    w, h = box_w * scale, box_h * scale
    frame = QRectF(centre.x() + x + (width - w) / 2, centre.y() + y + (height - h) / 2, w, h)
    _renderer(name).render(painter, frame)


def _drawLabel(painter, origin, text_font, text, colour):
    """Draw text the way cwl-svg draws labels: a halo in the canvas colour
    painted under the text (paint-order: stroke)."""
    path = QPainterPath()
    path.addText(origin, text_font, text)
    halo = QPen(_color('background'), LABEL_STROKE)
    halo.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(halo)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.setPen(colour)
    painter.setFont(text_font)
    painter.drawText(origin, text)


def portAngle(count, index, port_type):
    """Angle (degrees, clockwise from 3 o'clock) of a port on the ring
    (GraphNode.createPortMatrix)."""
    step = (index + 1) * PORT_ARC / (count + 1)
    if port_type == PortTypeEnum.IN.value:
        return 180 + PORT_ARC / 2 - step
    return -PORT_ARC / 2 + step


class PortLabel(QGraphicsItem):
    """Port name next to its port; inputs read leftwards, outputs rightwards."""

    def __init__(self, text, port_type, parent=None):
        super().__init__(parent)
        self._text = text
        self._port_type = port_type
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(3)
        self.setVisible(False)

    def text(self):
        return self._text

    def _textX(self, metrics):
        if self._port_type == PortTypeEnum.IN.value:
            return -PORT_LABEL_GAP - metrics.horizontalAdvance(self._text)
        return PORT_LABEL_GAP

    def boundingRect(self):
        metrics = QFontMetricsF(font(PORT_FONT_SIZE))
        pad = LABEL_STROKE / 2
        return QRectF(self._textX(metrics) - pad, -metrics.height() / 2 - pad,
                      metrics.horizontalAdvance(self._text) + 2 * pad, metrics.height() + 2 * pad)

    def paint(self, painter, option, widget=None):
        port_font = font(PORT_FONT_SIZE)
        metrics = QFontMetricsF(port_font)
        node = self.parentItem()
        colour = _color('faded_label') if getattr(node, '_faded', False) else _color('label')
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # alignment-baseline: middle
        baseline = (metrics.ascent() - metrics.descent()) / 2
        _drawLabel(painter, QPointF(self._textX(metrics), baseline), port_font, self._text, colour)
        painter.restore()


class CWLPortItem(PortItem):
    """A small round port on the node ring."""

    SIZE = 2 * (PORT_RADIUS + 3)    # a little larger than the dot, for easier grabbing

    def __init__(self, parent=None):
        super().__init__(parent)
        self._width = self._height = self.SIZE
        self._color = tuple(theme.GRAPH['port'][:3]) + (255,)

    def boundingRect(self):
        return QRectF(0.0, 0.0, self.SIZE, self.SIZE)

    def shape(self):
        path = QPainterPath()
        path.addEllipse(self.boundingRect())
        return path

    def mousePressEvent(self, event):
        # the viewer starts the connection drag; keep the press from
        # selecting the node or the edge under the port
        event.accept()

    def paint(self, painter, option, widget=None):
        node = self.parentItem()
        if getattr(node, '_faded', False):
            fill = _color('faded')
        else:
            fill = QColor(*self.color[:3])
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.hovered:
            painter.setPen(QPen(_color('port_hover'), 2))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(self.boundingRect().center(), PORT_RADIUS, PORT_RADIUS)
        painter.restore()


class CWLNodeItem(NodeItem):
    """Workflow node drawn as cwl-svg draws it."""

    def __init__(self, name='node', parent=None):
        self._radius = NODE_RADIUS
        self._label_scale = 1.0
        self._label_rect = QRectF()
        self._glyph = None
        self._hovered = False
        self._label_hovered = False     # the pointer is on the name of a node with a clickable name
        self.labelClickable = False     # clicking the name does something (it is underlined on hover)
        self.labelToolTip = ''          # what clicking the name does
        self._faded = False
        self._lit_ports = set()
        super().__init__(name, parent)
        self._width = self._height = 2 * self._radius
        # the title text item only holds the label text, the node paints it
        self._icon_item.setVisible(False)
        self._text_item.setVisible(False)
        self._text_item.set_locked(True)
        self._text_item.document().contentsChanged.connect(self._labelChanged)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('')

    # ---- size -------------------------------------------------------------
    @NodeItem.width.setter
    def width(self, width=0.0):
        AbstractNodeItem.width.fset(self, 2 * self._radius)

    @NodeItem.height.setter
    def height(self, height=0.0):
        AbstractNodeItem.height.fset(self, 2 * self._radius)

    def calc_size(self, add_w=0.0, add_h=0.0):
        return 2 * self._radius, 2 * self._radius

    def labelText(self):
        return self._text_item.toPlainText()

    def _updateLabelGeometry(self):
        self.prepareGeometryChange()
        text = self.labelText()
        if not text:
            self._label_rect = QRectF()
            return
        metrics = QFontMetricsF(font())
        scale = self._label_scale
        pad = LABEL_STROKE / 2
        width = metrics.horizontalAdvance(text)
        baseline = 2 * self._radius + LABEL_OFFSET
        self._label_rect = QRectF(self._radius - scale * (width / 2 + pad),
                                  baseline - scale * (metrics.ascent() + pad),
                                  scale * (width + 2 * pad),
                                  scale * (metrics.ascent() + metrics.descent() + 2 * pad))

    def _labelChanged(self):
        self._updateLabelGeometry()
        self.update()

    def isLabelAt(self, scene_pos):
        """True if ``scene_pos`` is on the name of the node, the label under the circle."""
        if self._label_rect.isNull():
            return False
        pos = self.mapFromScene(scene_pos)
        if not self._label_rect.contains(pos):
            return False
        # zoomed out, the label grows into the ring: the circle is not the name
        return math.hypot(pos.x() - self._radius, pos.y() - self._radius) > self._radius

    def boundingRect(self):
        ring = QRectF(0.0, 0.0, self._width, self._height).adjusted(-RING_WIDTH, -RING_WIDTH,
                                                                    RING_WIDTH, RING_WIDTH)
        if self._label_rect.isNull():
            return ring
        return ring.united(self._label_rect)

    def shape(self):
        # the label belongs to the node: it can be clicked and dragged too
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        path.addEllipse(QRectF(0.0, 0.0, self._width, self._height))
        if not self._label_rect.isNull():
            path.addRect(self._label_rect)
        return path

    def setLabelScale(self, scale):
        if abs(scale - self._label_scale) < 1e-3:
            return
        self._label_scale = scale
        self._labelChanged()

    def setGlyph(self, name):
        """Set the cwl-svg icon: workflow, tool, input, output, file_input,
        file_output or None."""
        self._glyph = name
        self.update()

    # ---- layout -----------------------------------------------------------
    def draw_node(self):
        inputs = [port for port in self._input_items if port.isVisible()]
        outputs = [port for port in self._output_items if port.isVisible()]
        self.prepareGeometryChange()
        self._radius = NODE_RADIUS + max(len(inputs), len(outputs)) * PORT_RADIUS
        self._width = self._height = 2 * self._radius
        self.align_ports()
        self._updateLabelGeometry()
        self.update()

    def post_init(self, viewer=None, pos=None):
        super().post_init(viewer, pos)
        view = self.viewer()
        if view:
            self.setLabelScale(labelScale(view.transform().m11()))

    def align_ports(self, v_offset=0.0):
        radius = self._radius
        for port_type, items in ((PortTypeEnum.IN.value, self._input_items),
                                 (PortTypeEnum.OUT.value, self._output_items)):
            ports = [port for port in items if port.isVisible()]
            # cwl-svg orders the ports by descending id, first on top
            ports.sort(key=lambda port: port.name.casefold(), reverse=True)
            for index, port in enumerate(ports):
                angle = math.radians(portAngle(len(ports), index, port_type))
                centre = QPointF(radius + radius * math.cos(angle), radius + radius * math.sin(angle))
                half = port.boundingRect().width() / 2
                port.setPos(centre.x() - half, centre.y() - half)
                items[port].setPos(centre)

    def align_label(self, h_offset=0.0, v_offset=0.0):
        self._labelChanged()

    def align_icon(self, h_offset=0.0, v_offset=0.0):
        pass

    def align_widgets(self, v_offset=0.0):
        pass

    def auto_switch_mode(self):
        pass

    def set_proxy_mode(self, mode):
        pass

    def _set_text_color(self, color):
        pass

    def _tooltip_disable(self, state):
        self.setToolTip('')

    @NodeItem.name.setter
    def name(self, name=''):
        NodeItem.name.fset(self, name)
        self.setToolTip('')

    # ---- ports ------------------------------------------------------------
    def _newPort(self, port_type, name, multi_port, display_name, locked):
        port = CWLPortItem(self)
        port.name = name
        port.port_type = port_type
        port.multi_connection = multi_port
        port.display_name = display_name
        port.locked = locked
        return self._add_port(port)

    def add_input(self, name='input', multi_port=False, display_name=True,
                  locked=False, painter_func=None):
        return self._newPort(PortTypeEnum.IN.value, name, multi_port, display_name, locked)

    def add_output(self, name='output', multi_port=False, display_name=True,
                   locked=False, painter_func=None):
        return self._newPort(PortTypeEnum.OUT.value, name, multi_port, display_name, locked)

    def _add_port(self, port):
        label = PortLabel(port.name, port.port_type, self)
        if port.port_type == PortTypeEnum.IN.value:
            self._input_items[port] = label
        else:
            self._output_items[port] = label
        if self.scene():
            self.post_init()
        return port

    def _refreshPortLabels(self):
        for items in (self._input_items, self._output_items):
            for port, label in items.items():
                label.setVisible(port.isVisible() and port.display_name
                                 and (self._hovered or port in self._lit_ports))

    def hoverEnterEvent(self, event):
        self._hovered = True
        self._refreshPortLabels()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        self._setLabelHovered(self.labelClickable and self.isLabelAt(event.scenePos()))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self._setLabelHovered(False)
        self._refreshPortLabels()
        super().hoverLeaveEvent(event)

    def _setLabelHovered(self, hovered):
        if hovered == self._label_hovered:
            return
        self._label_hovered = hovered
        self.setToolTip(self.labelToolTip if hovered else '')
        self.update()

    # ---- selection --------------------------------------------------------
    def setFaded(self, faded, lit_ports=()):
        lit_ports = {port for port in lit_ports if port.parentItem() is self}
        if faded == self._faded and lit_ports == self._lit_ports:
            return
        self._faded = faded
        self._lit_ports = lit_ports
        for items in (self._input_items, self._output_items):
            for port, label in items.items():
                port.update()
                label.update()
        self._refreshPortLabels()
        self.update()

    def _innerColor(self):
        fill = tuple(self.color[:3])
        if not self._faded:
            return QColor(*fill)
        if fill == theme.GRAPH['step'][:3]:
            return _color('faded_step')
        if fill == theme.GRAPH['io'][:3]:
            return _color('faded_io')
        background = theme.GRAPH['background']
        return QColor(*((c + b) // 2 for c, b in zip(fill, background)))

    # ---- painting ---------------------------------------------------------
    def paint(self, painter, option, widget=None):
        radius = self._radius
        centre = QPointF(radius, radius)
        if self.isSelected():
            ring = _color('primary')
        elif self._faded:
            ring = _color('faded')
        else:
            ring = _color('edge')
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(QPen(ring, RING_WIDTH))
        painter.setBrush(_color('background'))
        painter.drawEllipse(centre, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._innerColor())
        painter.drawEllipse(centre, radius * INNER_RATIO, radius * INNER_RATIO)
        if self._glyph:
            _drawIcon(painter, self._glyph, centre)
        text = self.labelText()
        if text:
            label_font = font()
            painter.translate(radius, 2 * radius + LABEL_OFFSET)
            painter.scale(self._label_scale, self._label_scale)
            x = -QFontMetricsF(label_font).horizontalAdvance(text) / 2
            colour = _color('faded_label') if self._faded else _color('label')
            _drawLabel(painter, QPointF(x, 0), label_font, text, colour)
            if self._label_hovered:
                # like a link: the name can be clicked
                painter.setPen(QPen(colour, 1))
                width = QFontMetricsF(label_font).horizontalAdvance(text)
                painter.drawLine(QPointF(x, 3), QPointF(x + width, 3))
        painter.restore()


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------
class EdgeTip(QGraphicsItem):
    """'source (port) → destination (port)' shown over a hovered edge."""

    def __init__(self, text):
        super().__init__()
        self._text = text
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(100)

    def boundingRect(self):
        metrics = QFontMetricsF(font())
        width = metrics.horizontalAdvance(self._text)
        pad = LABEL_STROKE / 2
        return QRectF(-width / 2 - pad, -metrics.ascent() - pad,
                      width + 2 * pad, metrics.ascent() + metrics.descent() + 2 * pad)

    def paint(self, painter, option, widget=None):
        label_font = font()
        width = QFontMetricsF(label_font).horizontalAdvance(self._text)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _drawLabel(painter, QPointF(-width / 2, 0), label_font, self._text, _color('label'))
        painter.restore()


def _endpointName(port):
    node = port.node
    title = node.labelText() if isinstance(node, CWLNodeItem) else node.name
    title = title or node.name
    # workflow inputs and outputs have a single, unnamed port
    if not port.display_name:
        return title
    return f"{title} ({port.name})"


def _pipeInit(original):
    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self._faded = False
        self._tip = None
        self._color = theme.GRAPH['edge']
        self._dir_pointer.setVisible(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset()
    return __init__


def _setPipeStyling(self, color, width=2, style=0):
    # the pen only sets the hit area and bounds (the halo), paint() draws
    pen = QPen(QColor(*color[:3]), EDGE_HALO)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    self.setPen(pen)
    self.setBrush(QBrush(Qt.BrushStyle.NoBrush))


def _pipeShape(self):
    stroker = QPainterPathStroker()
    stroker.setWidth(EDGE_HALO)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    return stroker.createStroke(self.path())


def _paintPipe(self, painter, option, widget=None):
    live = isinstance(self, LivePipeItem)
    if live:
        colour = _color('edge')
    elif self._active or self.isSelected():
        colour = _color('primary')
    elif getattr(self, '_faded', False):
        colour = _color('faded')
    else:
        colour = QColor(*self._color[:3])
    path = self.path()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_color('background'), EDGE_HALO, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(path)
    inner = QPen(colour, EDGE_WIDTH, Qt.PenStyle.SolidLine,
                 Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    if live:
        # port-drag: stroke-dasharray 5 (in pen widths for Qt)
        inner.setCapStyle(Qt.PenCapStyle.FlatCap)
        inner.setDashPattern([5 / EDGE_WIDTH, 5 / EDGE_WIDTH])
    painter.setPen(inner)
    painter.drawPath(path)
    painter.restore()


def _drawPathHorizontal(original):
    def _draw_path_horizontal(self, start_port, pos1, pos2, path):
        if self.viewer_pipe_layout() != PipeLayoutEnum.CURVED.value:
            return original(self, start_port, pos1, pos2, path)
        # cwl-svg makeConnectionPath: control points half way across
        tangent = abs(pos1.x() - pos2.x()) / 2
        if start_port.port_type == PortTypeEnum.IN.value:
            tangent = -tangent
        path.cubicTo(QPointF(pos1.x() + tangent, pos1.y()),
                     QPointF(pos2.x() - tangent, pos2.y()), pos2)
        self.setPath(path)
    return _draw_path_horizontal


def _hideDirectionPointer(self):
    self._dir_pointer.setVisible(False)


def _pipeHoverEnter(original):
    def hoverEnterEvent(self, event):
        original(self, event)
        if self.input_port is None or self.output_port is None or not self.scene():
            return
        _removeTip(self)
        self._tip = EdgeTip(f"{_endpointName(self.output_port)} → {_endpointName(self.input_port)}")
        self.scene().addItem(self._tip)
        self._tip.setPos(event.scenePos() - QPointF(0, EDGE_TIP_OFFSET))
    return hoverEnterEvent


def _pipeHoverMove(self, event):
    if getattr(self, '_tip', None) is not None:
        self._tip.setPos(event.scenePos() - QPointF(0, EDGE_TIP_OFFSET))
    QGraphicsItem.hoverMoveEvent(self, event)


def _pipeHoverLeave(original):
    def hoverLeaveEvent(self, event):
        _removeTip(self)
        original(self, event)
    return hoverLeaveEvent


def _removeTip(pipe):
    tip = getattr(pipe, '_tip', None)
    pipe._tip = None
    if tip is not None and tip.scene():
        tip.scene().removeItem(tip)


def _pipeDelete(original):
    def delete(self):
        _removeTip(self)
        original(self)
    return delete


def _hideIndexPointer(original):
    def draw_index_pointer(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self._idx_pointer.setVisible(False)
        self._idx_text.setVisible(False)
    return draw_index_pointer


def patchPipes():
    """Draw every graph connection as a cwl-svg edge."""
    if getattr(PipeItem, '_cwled_composer', False):
        return
    PipeItem._cwled_composer = True
    PipeItem.__init__ = _pipeInit(PipeItem.__init__)
    PipeItem.set_pipe_styling = _setPipeStyling
    PipeItem.shape = _pipeShape
    PipeItem.paint = _paintPipe
    PipeItem._draw_path_horizontal = _drawPathHorizontal(PipeItem._draw_path_horizontal)
    PipeItem._draw_direction_pointer = _hideDirectionPointer
    PipeItem.hoverEnterEvent = _pipeHoverEnter(PipeItem.hoverEnterEvent)
    PipeItem.hoverMoveEvent = _pipeHoverMove
    PipeItem.hoverLeaveEvent = _pipeHoverLeave(PipeItem.hoverLeaveEvent)
    PipeItem.delete = _pipeDelete(PipeItem.delete)
    LivePipeItem.draw_index_pointer = _hideIndexPointer(LivePipeItem.draw_index_pointer)


# ---------------------------------------------------------------------------
# selection and zoom
# ---------------------------------------------------------------------------
def _gone(*objects) -> bool:
    """True when a Qt object is deleted or being destroyed (e.g. a closing
    workflow, whose scene still emits selectionChanged while it goes away)."""
    return any(obj is None or sip.isdeleted(obj) for obj in objects)


def refreshSelection(scene):
    """cwl-svg selection: everything fades except the selection, the edges
    of a selected node and the nodes at their other end."""
    if _gone(scene):
        return
    nodes = [item for item in scene.items() if isinstance(item, CWLNodeItem)]
    pipes = [item for item in scene.items()
             if isinstance(item, PipeItem) and not isinstance(item, LivePipeItem)]
    selected_nodes = [node for node in nodes if node.isSelected()]
    selected_pipes = [pipe for pipe in pipes if pipe.isSelected()]
    fade = bool(selected_nodes or selected_pipes)
    lit_nodes, lit_pipes, lit_ports = set(selected_nodes), set(selected_pipes), set()
    for node in selected_nodes:
        for port in node.inputs + node.outputs:
            for pipe in port.connected_pipes:
                lit_pipes.add(pipe)
                lit_nodes.update(end.node for end in (pipe.input_port, pipe.output_port) if end)
    for pipe in selected_pipes:
        lit_ports.update(end for end in (pipe.input_port, pipe.output_port) if end)
    for node in nodes:
        node.setFaded(fade and node not in lit_nodes, lit_ports)
    for pipe in pipes:
        faded = fade and pipe not in lit_pipes
        if getattr(pipe, '_faded', False) != faded:
            pipe._faded = faded
            pipe.update()


def viewScale(viewer):
    return viewer.transform().m11()


def contentRect(scene):
    """Bounds of the workflow on the canvas: the visible nodes (with their
    labels and ports) and edges, leaving out the viewer's helper items."""
    rect = QRectF()
    for item in scene.items():
        if not item.isVisible():
            continue
        if isinstance(item, (CWLNodeItem, PipeItem)) or isinstance(item.parentItem(), CWLNodeItem):
            rect = rect.united(item.sceneBoundingRect())
    return rect


def fitToViewport(graph):
    """Frame the whole workflow (cwl-svg Workflow.fitToViewport): 100px of
    padding, never zoomed in past 100% nor out past the minimum zoom."""
    viewer = graph.viewer()
    items = [node.view for node in graph.all_nodes()]
    if not items:
        return
    # twice: the label size follows the zoom
    for _ in range(2):
        rect = QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())
        rect.adjust(-50, -50, 50, 50)
        size = viewer.viewport().size()
        scale = min(size.width() / max(rect.width(), 1.0), size.height() / max(rect.height(), 1.0))
        if scale > 1 or scale < MIN_SCALE:
            scale = min(max(scale, MIN_SCALE), 1.0)
            frame = QRectF(0, 0, size.width() / scale, size.height() / scale)
            frame.moveCenter(rect.center())
            rect = frame
        viewer._scene_range = rect
        viewer._update_scene()


def zoomFactor(viewer, factor):
    """``factor`` limited so that the zoom stays between cwl-svg's MIN_SCALE and MAX_SCALE."""
    scale = viewScale(viewer)
    return min(max(scale * factor, MIN_SCALE), MAX_SCALE) / scale


def zoomViewer(viewer, factor, position=None):
    """Zoom the canvas by ``factor`` around ``position`` (a point of the viewport; by default its centre)."""
    factor = zoomFactor(viewer, factor)
    if abs(factor - 1) < 1e-6:
        return
    anchor = viewer.mapToScene(position) if position is not None else None
    viewer.scale(factor, factor, anchor)


def panViewer(viewer, dx, dy):
    """Move the canvas by (dx, dy) pixels of the viewport: the content follows the movement."""
    scale = viewScale(viewer)
    viewer._set_viewer_pan(-dx / scale, -dy / scale)


class ViewLink(QObject):
    """
    "Link views": panning or zooming the workflow graph of one window does the
    same in the graphs of the other visible windows, so that two workflows (or
    two versions of one) that are compared side by side stay aligned. The
    movement is the same on the screen, whatever the zoom of each graph.
    """
    changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._viewers = []          # weak references to the viewers of the graphs
        self._busy = False

    def enabled(self):
        return self._enabled

    def setEnabled(self, enabled):
        enabled = bool(enabled)
        if enabled != self._enabled:
            self._enabled = enabled
            self.changed.emit(enabled)

    def register(self, viewer):
        self._viewers.append(weakref.ref(viewer))

    def others(self, viewer):
        """The other graphs that are shown."""
        live = []
        for reference in list(self._viewers):
            other = reference()
            if other is None or _gone(other):
                self._viewers.remove(reference)
            elif other is not viewer and other.isVisible():
                live.append(other)
        return live

    def panned(self, viewer, dx, dy):
        """``viewer`` was panned by (dx, dy) scene units."""
        if not self._enabled or self._busy:
            return
        scale = viewScale(viewer)
        self._busy = True
        try:
            for other in self.others(viewer):
                other._pan_unlinked(dx * scale / viewScale(other), dy * scale / viewScale(other))
        finally:
            self._busy = False

    def zoomed(self, viewer, factor, anchor):
        """``viewer`` was zoomed by ``factor`` around the scene point ``anchor``."""
        if not self._enabled or self._busy:
            return
        point = viewer.mapFromScene(anchor) if anchor is not None else viewer.viewport().rect().center()
        self._busy = True
        try:
            for other in self.others(viewer):
                other._scale_unlinked(factor, factor, other.mapToScene(point))
        finally:
            self._busy = False


# one for the application: it links the graphs of all windows
LINK = ViewLink()


class CanvasNavigator(QObject):
    """
    Moving around the workflow canvas, as in Composer and the usual graph editors:

    * dragging the empty canvas with the left mouse button moves it. The viewer
      would draw a selection rectangle instead (it only pans with Alt + left
      button or the middle button); Shift + drag still selects with a
      rectangle. Nodes, ports and connections are dragged as before: only a
      drag that starts on the empty canvas pans;
    * holding Space makes a left drag move the canvas wherever it starts;
    * scrolling with a trackpad moves the canvas, and Cmd/Ctrl + scroll or a
      pinch zooms (the wheel of a mouse still zooms);
    * the arrow keys move the canvas, + and - zoom and 0 fits the workflow.
    """
    KEY_STEP = 60               # pixels moved by an arrow key (four times as many with Shift)
    KEY_ZOOM = 1.1              # zoom by + and - (the zoom buttons' step)

    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self._press = None      # viewport position where the left button went down
        self._last = None       # viewport position of the last pan step; None unless panning
        self._space = False     # Space is held
        self._space_pan = False  # the pan started with Space: the whole press is ours
        viewer.viewport().installEventFilter(self)
        viewer.installEventFilter(self)

    @property
    def panning(self):
        return self._last is not None

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self.viewer:
            if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                return self._key(event, kind == QEvent.Type.KeyPress)
            if kind == QEvent.Type.FocusOut:
                self._setSpace(False)
            return False
        if kind == QEvent.Type.MouseButtonPress:
            self._stop()
            if event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.NoModifier:
                self._press = event.position().toPoint()
                if self._space:
                    self._space_pan = True
                    self._begin(self._press)
                    return True
            else:
                self._press = None
        elif kind == QEvent.Type.MouseMove:
            if self.panning or self._press is not None:
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    self._stop()
                elif self._pan(event.position().toPoint()):
                    return True
        elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            ours = self._space_pan
            self._stop()
            return ours
        elif kind == QEvent.Type.Wheel:
            return self._wheel(event)
        elif kind == QEvent.Type.NativeGesture:
            return self._gesture(event)
        return False

    # -- dragging ----------------------------------------------------------------
    def _begin(self, position):
        self._last = position
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)

    def _pan(self, position):
        """Move the canvas with the mouse; True if the move belongs to the pan."""
        viewer = self.viewer
        if not self.panning:
            # The viewer has seen the press by now: it arms its selection
            # rectangle exactly when the press was on the empty canvas.
            if not viewer._rubber_band.isActive:
                return False
            if (position - self._press).manhattanLength() < QApplication.startDragDistance():
                return False
            viewer._rubber_band.isActive = False
            viewer._rubber_band.hide()
            self._begin(self._press)
        previous = self._last
        panViewer(viewer, position.x() - previous.x(), position.y() - previous.y())
        self._last = position
        return True

    def _stop(self):
        if self.panning:
            QApplication.restoreOverrideCursor()
        self._press = self._last = None
        self._space_pan = False

    # -- trackpad and wheel ----------------------------------------------------------
    def _wheel(self, event):
        viewer = self.viewer
        pixels = event.pixelDelta()
        precise = not pixels.isNull() or event.phase() != Qt.ScrollPhase.NoScrollPhase
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            amount = pixels.y() if not pixels.isNull() else event.angleDelta().y()
            zoomViewer(viewer, 1.001 ** amount, event.position().toPoint())
            return True
        if precise:
            if pixels.isNull():
                pixels = event.angleDelta() / 2
            panViewer(viewer, pixels.x(), pixels.y())
            return True
        return False        # the wheel of a mouse zooms, in the viewer

    def _gesture(self, event):
        kind = event.gestureType()
        if kind == Qt.NativeGestureType.ZoomNativeGesture:
            zoomViewer(self.viewer, 1 + event.value(), event.position().toPoint())
            return True
        if kind == Qt.NativeGestureType.SmartZoomNativeGesture:
            fitToViewport(self.viewer._cwled_graph)
            return True
        return False

    # -- keys ------------------------------------------------------------------------
    def _setSpace(self, held):
        if held != self._space:
            self._space = held
            if held:
                self.viewer.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.viewer.viewport().unsetCursor()

    def _key(self, event, pressed):
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._setSpace(pressed)
            return True
        if not pressed or event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier & ~Qt.KeyboardModifier.KeypadModifier:
            return False
        step = self.KEY_STEP * (4 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
        moves = {Qt.Key.Key_Left: (step, 0), Qt.Key.Key_Right: (-step, 0),
                 Qt.Key.Key_Up: (0, step), Qt.Key.Key_Down: (0, -step)}
        if key in moves:
            panViewer(self.viewer, *moves[key])
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            zoomViewer(self.viewer, self.KEY_ZOOM)
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            zoomViewer(self.viewer, 1 / self.KEY_ZOOM)
        elif key == Qt.Key.Key_0:
            fitToViewport(self.viewer._cwled_graph)
        else:
            return False
        return True


def install(graph):
    """Hook a NodeGraph up to the Composer look: label scaling on zoom,
    selection fading, Composer's zoom range, moving around the canvas (see
    CanvasNavigator) and linking its view to the other graphs (see ViewLink)."""
    import OdenGraphQt.widgets.viewer as viewer_module
    # cwl-svg zooms between 0.2 and 2 (the viewer measures zoom as scale - 1)
    viewer_module.ZOOM_MIN = MIN_SCALE - 1
    viewer_module.ZOOM_MAX = MAX_SCALE - 1
    viewer = graph.viewer()
    scene = viewer.scene()
    update_scene = viewer._update_scene

    def _update_scene():
        update_scene()
        if _gone(viewer, scene):
            return
        scale = labelScale(viewScale(viewer))
        for item in scene.items():
            if isinstance(item, CWLNodeItem):
                item.setLabelScale(scale)

    viewer._update_scene = _update_scene

    # every pan and zoom of the canvas, whoever asks for it (the mouse, the wheel, the zoom
    # buttons, the keys), is passed on to the linked views
    viewer._cwled_graph = graph
    viewer._pan_unlinked = viewer._set_viewer_pan
    viewer._scale_unlinked = viewer.scale

    def _set_viewer_pan(pos_x, pos_y):
        viewer._pan_unlinked(pos_x, pos_y)
        LINK.panned(viewer, pos_x, pos_y)

    def _scale(sx, sy, pos=None):
        anchor = pos if pos is not None else viewer._scene_range.center()
        viewer._scale_unlinked(sx, sy, pos)
        LINK.zoomed(viewer, sx, anchor)

    viewer._set_viewer_pan = _set_viewer_pan
    viewer.scale = _scale
    LINK.register(viewer)
    CanvasNavigator(viewer)
    scene.selectionChanged.connect(lambda: refreshSelection(scene))
    graph.port_connected.connect(lambda *args: refreshSelection(scene))
    graph.port_disconnected.connect(lambda *args: refreshSelection(scene))


# ---------------------------------------------------------------------------
# canvas buttons
# ---------------------------------------------------------------------------
class GraphControls(QWidget):
    """Composer's graph canvas buttons, bottom right of the canvas:
    delete, zoom in / out, fit to viewport, auto-arrange and export."""

    ZOOM_STEP = 0.1         # workflow-graph-editor upscale() / downscale()

    def __init__(self, canvas, graph, on_delete=None, on_arrange=None, on_export=None):
        super().__init__(canvas.parentWidget())
        self.canvas = canvas
        self.graph = graph
        self.setObjectName('graphControls')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.delete_button, = self._group(layout, [('trash', 'Delete', on_delete)])
        self.zoom_in_button, self.zoom_out_button, self.fit_button = self._group(layout, [
            ('plus', 'Zoom In', lambda: self.zoomBy(self.ZOOM_STEP)),
            ('minus', 'Zoom Out', lambda: self.zoomBy(-self.ZOOM_STEP)),
            ('compress', 'Fit to Viewport', self.fitToViewport)])
        self.arrange_button, = self._group(layout, [('paint-brush', 'Auto-arrange', on_arrange)])
        # linked views: panning and zooming this graph does the same in the graphs of the other windows
        self.link_button, = self._group(layout, [('link', 'Link the view to the other windows\' workflows', None)])
        self.link_button.setCheckable(True)
        self.link_button.setChecked(LINK.enabled())
        self.link_button.toggled.connect(LINK.setEnabled)
        LINK.changed.connect(self.link_button.setChecked)
        self.export_button, = self._group(layout, [('file-image-o', 'Export Image', on_export)])
        self.delete_button.parentWidget().setVisible(False)
        viewer = graph.viewer()
        viewer.scene().selectionChanged.connect(self.refresh)
        update_scene = viewer._update_scene

        def _update_scene():
            update_scene()
            if not _gone(self):
                self.refresh()

        viewer._update_scene = _update_scene
        canvas.installEventFilter(self)
        self.refresh()
        self.reposition()

    def _group(self, layout, specs):
        group = QWidget(self)
        group_layout = QHBoxLayout(group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(0)
        buttons = []
        for index, (glyph, tip, slot) in enumerate(specs):
            button = QPushButton(group)
            # .btn-group: only the outer corners are rounded
            if len(specs) == 1:
                position = 'only'
            else:
                position = 'first' if index == 0 else 'last' if index == len(specs) - 1 else 'middle'
            button.setProperty('graphControl', position)
            button.setIcon(theme.icon(glyph, color=theme.TEXT, disabled_color=theme.TEXT_DISABLED))
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if slot:
                button.clicked.connect(lambda checked=False, slot=slot: slot())
            group_layout.addWidget(button)
            buttons.append(button)
        layout.addWidget(group)
        return buttons

    def zoomBy(self, step):
        viewer = self.graph.viewer()
        scale = viewScale(viewer)
        target = min(max(scale + step, MIN_SCALE), MAX_SCALE)
        if abs(target - scale) > 1e-6:
            viewer.scale(target / scale, target / scale)

    def fitToViewport(self):
        fitToViewport(self.graph)

    def refresh(self):
        viewer = self.graph.viewer()
        if _gone(self, viewer) or _gone(viewer.scene()):
            return
        scale = viewScale(viewer)
        self.zoom_in_button.setEnabled(scale < MAX_SCALE - 1e-3)
        self.zoom_out_button.setEnabled(scale > MIN_SCALE + 1e-3)
        has_selection = bool(viewer.scene().selectedItems())
        group = self.delete_button.parentWidget()
        if group.isVisible() != has_selection:
            group.setVisible(has_selection)
            self.adjustSize()
            self.reposition()

    def reposition(self):
        # .svg-btns: 10px from the right, just above the bottom edge
        if _gone(self, self.canvas):
            return
        self.adjustSize()
        frame = self.canvas.geometry()
        self.move(frame.right() - self.width() - 10 + 1, frame.bottom() - self.height() - 5 + 1)
        self.raise_()

    def eventFilter(self, watched, event):
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        if watched is self.canvas and event.type() in (QEvent.Type.Resize, QEvent.Type.Move,
                                                        QEvent.Type.Show):
            self.reposition()
        return super().eventFilter(watched, event)
