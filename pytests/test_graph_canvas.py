"""The workflow graph: clicking names, double clicks, moving around the canvas, linked views."""
import shutil
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QCursor, QNativeGestureEvent, QPointingDevice, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import GraphItems
from conftest import FIXTURES
from qt_helpers import LEFT, NO_MODIFIER, graph_point, near, open_documents, park_cursor, pump, titles
from WorkspaceContents import ROLE_PATH

CTRL = Qt.KeyboardModifier.ControlModifier


@pytest.fixture
def workflow(window):
    """The document of 50-workflow.cwl (its steps are the files echo.cwl and uppercase.cwl) and its graph."""
    document = open_documents(window, ['50-workflow.cwl'])['50-workflow.cwl']
    graph = document.workflow_editor.graph
    pump(8)
    return document, graph, graph.graph.viewer()


# ---------------------------------------------------------------------------------------- drawing the graph
def hover_canvas(viewer):
    """Rest the mouse pointer over the canvas, as it is while someone works on the graph with the keyboard."""
    viewport = viewer.viewport()
    QCursor.setPos(viewport.mapToGlobal(viewport.rect().center()))
    pump(4)
    assert viewer.underMouse(), "the pointer is over the canvas"


def switch_away_and_back(document):
    tabs = document.tabs
    visual = tabs.indexOf(document.workflow_editor)
    tabs.setCurrentIndex(0 if visual else 1)
    pump(4)
    tabs.setCurrentIndex(visual)


@pytest.mark.parametrize('redraw', [
    pytest.param(lambda document: document.workflow_editor.graph.showGraph(), id='showGraph'),
    pytest.param(lambda document: document.workflow_editor.populateFromCWL(), id='populateFromCWL'),
    pytest.param(switch_away_and_back, id='back to the Visual Editor tab'),
    pytest.param(lambda document: document.loadCWL(), id='reloading the file'),
])
def test_drawing_the_graph_with_the_pointer_on_the_canvas_opens_no_menu(window, workflow, redraw):
    document, _graph, viewer = workflow
    opened = []

    def close_popup():
        # a menu that is opened (modally) blocks the call that opened it: note it and close it
        popup = QApplication.activePopupWidget()
        if popup is not None:
            opened.append(type(popup).__name__)
            popup.close()

    watchdog = QTimer()
    watchdog.timeout.connect(close_popup)
    watchdog.start(20)
    try:
        hover_canvas(viewer)
        redraw(document)
        pump(6)
    finally:
        watchdog.stop()
    assert opened == [], f"drawing the graph opened {opened}"
    assert QApplication.activePopupWidget() is None and QApplication.activeModalWidget() is None
    assert viewer.underMouse(), "the pointer was over the canvas all along"
