"""
The logo of CWLed.

The mark is a workflow graph that spells the W of CWL: five nodes on a zigzag of edges. The two outer
nodes are ports (the inputs and outputs of a workflow, rings), the three inner ones are steps (circles).
Edges and nodes are drawn the way the workflow editor draws a graph; the raspberry of the edges is
a nod to the zigzag of the Common Workflow Language logo.

The mark is described once, as SVG (``markSvg``): the files of ``resources/logo`` are made from it
(``resources/logo/make_logo.py``), and the application paints it with ``QSvgRenderer``, so that
every use is the same drawing. It uses nothing but what Qt's SVG module renders (gradients and strokes).
"""
from typing import Optional

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

SIZE = 256                      # the mark is drawn in a square of this size

# colours
TILE_TOP = '#2d313a'
TILE_BOTTOM = '#0f1115'
EDGE_START = '#ff5f8f'
EDGE_END = '#b92f78'
INK = '#14161a'                 # the dark of the tile, used as the core of the ports and the ring around the nodes
LIGHT = '#f4f5f7'
TEAL = '#2bc4b0'
PURPLE = '#a779ff'

# the W: top left port, bottom left step, apex step, bottom right step, top right port
POINTS = [(44, 66), (86, 188), (128, 98), (170, 188), (212, 66)]
EDGE_WIDTH = 12
STEP_RADIUS = 20
PORT_RADIUS = 13
RING = 7                        # the dark ring that separates a node from the edges


def markSvg(tile: bool = True) -> str:
    """
    The mark as SVG text. With ``tile`` it sits on a dark rounded square (an application icon);
    without, it is only the W, for a background of your own.
    """
    path = 'M ' + ' L '.join(f'{x} {y}' for x, y in POINTS)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" width="{SIZE}" height="{SIZE}">',
             '<defs>',
             f'<linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">'
             f'<stop offset="0" stop-color="{TILE_TOP}"/><stop offset="1" stop-color="{TILE_BOTTOM}"/></linearGradient>',
             f'<linearGradient id="edge" gradientUnits="userSpaceOnUse" x1="{POINTS[0][0]}" y1="{POINTS[0][1]}" '
             f'x2="{POINTS[-1][0]}" y2="{POINTS[-1][1] + 112}">'
             f'<stop offset="0" stop-color="{EDGE_START}"/><stop offset="1" stop-color="{EDGE_END}"/></linearGradient>',
             '</defs>']
    if tile:
        parts.append(f'<rect x="0" y="0" width="{SIZE}" height="{SIZE}" rx="58" ry="58" fill="url(#tile)"/>')
        parts.append(f'<rect x="1.5" y="1.5" width="{SIZE - 3}" height="{SIZE - 3}" rx="56.5" ry="56.5" fill="none" '
                     f'stroke="#ffffff" stroke-opacity="0.09" stroke-width="3"/>')
    parts.append(f'<path d="{path}" fill="none" stroke="url(#edge)" stroke-width="{EDGE_WIDTH}" '
                 f'stroke-linecap="round" stroke-linejoin="round"/>')
    for index, (x, y) in enumerate(POINTS):
        if index in (0, len(POINTS) - 1):          # a port: a light circle, like the inputs and outputs of the graph
            parts.append(f'<circle cx="{x}" cy="{y}" r="{PORT_RADIUS + RING / 2}" fill="{LIGHT}" stroke="{INK}" '
                         f'stroke-width="{RING}"/>')
        else:                                      # a step: a circle in the colour of its kind, inside a dark ring
            colour = PURPLE if index == 2 else TEAL
            parts.append(f'<circle cx="{x}" cy="{y}" r="{STEP_RADIUS + RING / 2}" fill="{colour}" stroke="{INK}" '
                         f'stroke-width="{RING}"/>')
    parts.append('</svg>')
    return ''.join(parts)


def renderer(tile: bool = True) -> QSvgRenderer:
    return QSvgRenderer(QByteArray(markSvg(tile).encode('utf-8')))


def paintMark(painter: QPainter, rect: QRectF, tile: bool = True):
    """Paint the mark into a square, scaled."""
    renderer(tile).render(painter, rect)


def markImage(size: int, tile: bool = True) -> QImage:
    """The mark as an image of ``size`` x ``size`` pixels with a transparent background."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paintMark(painter, QRectF(0, 0, size, size), tile)
    painter.end()
    return image


def markPixmap(size: int, device_pixel_ratio: Optional[float] = None, tile: bool = True) -> QPixmap:
    """The mark as a pixmap of ``size`` logical pixels, sharp on a screen with a higher pixel ratio."""
    if device_pixel_ratio is None:
        screen = QGuiApplication.primaryScreen()
        device_pixel_ratio = screen.devicePixelRatio() if screen is not None else 1.0
    pixmap = QPixmap.fromImage(markImage(max(1, round(size * device_pixel_ratio)), tile))
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap
