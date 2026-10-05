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


def selected(window):
    index = window.sidebar.workspace_panel.tree_view.currentIndex()
    return index.data(ROLE_PATH) if index.isValid() else None


def reset_selection(window):
    panel = window.sidebar.workspace_panel
    panel.tree_view.setCurrentIndex(panel.model.index(0, 0))
    panel.tree_view.collapseAll()
    pump(2)


def click(viewer, point, modifier=NO_MODIFIER):
    QTest.mouseClick(viewer.viewport(), LEFT, modifier, point)
    pump(4)


def double_click(viewer, point):
    """What the mouse sends: press and release, then the double click and its release."""
    QTest.mouseClick(viewer.viewport(), LEFT, NO_MODIFIER, point)
    QTest.mouseDClick(viewer.viewport(), LEFT, NO_MODIFIER, point)
    pump(6)
    if viewer.scene().mouseGrabberItem() is not None:       # QTest sends no release after the double click
        QTest.mouseRelease(viewer.viewport(), LEFT, NO_MODIFIER, point)
        pump(4)


# ---------------------------------------------------------------------------------------- clicking names
def test_clicking_the_name_of_a_step_shows_its_file_in_the_workspace_panel(window, workflow):
    _document, graph, viewer = workflow
    echo, upper = graph.graph.get_node_by_name('echo').view, graph.graph.get_node_by_name('uppercase').view
    assert echo.labelClickable and 'echo.cwl' in echo.labelToolTip
    window.sidebar.tabs.setCurrentIndex(1)                  # the Recent page: the click brings the Workspace page back
    reset_selection(window)
    folder = window.workspace.currentFolder()
    click(viewer, graph_point(graph, 'echo'))
    assert selected(window) == str(FIXTURES / 'echo.cwl') and window.sidebar.tabs.currentIndex() == 0
    import os
    assert window.workspace.currentFolder() == folder and os.getcwd() == folder, "navigation does not change the current folder"

    # only the name counts: not the circle, not a drag
    reset_selection(window)
    before = selected(window)
    click(viewer, graph_point(graph, 'uppercase', 'circle'))
    assert selected(window) == before
    start, position = graph_point(graph, 'uppercase'), upper.pos()
    QTest.mousePress(viewer.viewport(), LEFT, NO_MODIFIER, start)
    for dx, dy in ((10, 5), (30, 20), (60, 40)):
        QTest.mouseMove(viewer.viewport(), start + QPoint(dx, dy))
        pump(2)
    QTest.mouseRelease(viewer.viewport(), LEFT, NO_MODIFIER, start + QPoint(60, 40))
    pump(4)
    assert upper.pos() != position and selected(window) == before, "a drag from the name moves the node"


def test_double_clicking_a_node_opens_the_inspector_from_the_circle_and_from_the_name(window, workflow):
    document, graph, viewer = workflow
    inspector = document.workflow_editor.step_inspector
    assert not inspector.isVisible()
    double_click(viewer, graph_point(graph, 'echo', 'circle'))
    assert inspector.isVisible() and inspector._node_name == 'echo'
    inspector.close_inspector()
    pump(3)
    reset_selection(window)
    double_click(viewer, graph_point(graph, 'uppercase'))
    assert inspector.isVisible() and inspector._node_name == 'uppercase'


def test_the_search_and_missing_workspace_folders(window, workflow):
    _document, graph, viewer = workflow
    panel = window.sidebar.workspace_panel
    panel.search_box.setText('hello')
    panel.on_search_clicked()
    pump(3)
    assert panel._showing_search
    click(viewer, graph_point(graph, 'echo'))
    assert not panel._showing_search and panel.search_box.text() == '' and selected(window) == str(FIXTURES / 'echo.cwl')
    window.workspace.addFolder(str(FIXTURES.parent / 'docs'))
    window.workspace.removeFolder(str(FIXTURES))
    window.updateWorkspaceViews()
    pump(4)
    click(viewer, graph_point(graph, 'echo'))
    assert 'not in a workspace folder' in window.statusBar().currentMessage()


def test_a_workflow_in_a_detached_window_reveals_in_that_windows_panel(window, workflow):
    document, graph, viewer = workflow
    window.tabs.detachTab(document)
    pump(12)
    detached = window.detached_windows[0]
    detached.show()
    pump(8)
    before = selected(window)
    reset_selection(detached)
    click(graph.graph.viewer(), graph_point(graph, 'echo'))
    assert selected(detached) == str(FIXTURES / 'echo.cwl') and selected(window) == before


def test_ctrl_click_opens_the_step(window, workflow):
    document, graph, viewer = workflow
    click(viewer, graph_point(graph, 'echo'), CTRL)
    pump(10)
    assert 'echo.cwl' in titles(window.tabs) and Path(str(window.tabs.currentWidget().file_path)).name == 'echo.cwl'
    window.tabs.setCurrentWidget(document)
    pump(4)
    click(viewer, graph_point(graph, 'echo'), CTRL)
    assert titles(window.tabs).count('echo.cwl') == 1, "an open file is brought forward"

    # a step defined inside the workflow: its definition in the Code tab
    inline = open_documents(window, ['51-workflow.cwl'])['51-workflow.cwl']
    pump(6)
    graph2 = inline.workflow_editor.graph
    click(graph2.graph.viewer(), graph_point(graph2, 'uppercase'), CTRL)
    pump(20)
    assert inline.tabs.currentWidget() is inline.code_editor
    assert inline.code_editor.editor.selectedText().strip() in ('uppercase:', '- id: uppercase')


@pytest.mark.parametrize('fmt, text, step, expected', [
    ('YAML', "cwlVersion: v1.2\nclass: Workflow\ninputs:\n  echo: string\nsteps:\n  - id: echo\n    run: a.cwl\n"
             "  - id: up\n    run: b.cwl\noutputs:\n  echo:\n    type: string\n", 'up', (True, 7)),
    ('YAML', "cwlVersion: v1.2\nclass: Workflow\ninputs:\n  echo: string\nsteps:\n  - id: echo\n    run: a.cwl\n"
             "  - id: up\n    run: b.cwl\noutputs:\n  echo:\n    type: string\n", 'echo', (True, 5)),
    ('YAML', "steps:\n  - id: a\n", 'nope', (False, None)),
    ('JSON', '{\n "inputs": {"echo": {}},\n "steps": {\n  "echo": {"run": "a.cwl"},\n  "up": {}\n }\n}', 'echo', (True, 3)),
    ('JSON', '{\n "inputs": {"echo": {}},\n "steps": {\n  "echo": {"run": "a.cwl"},\n  "up": {}\n }\n}', 'up', (True, 4)),
])
def test_finding_a_step_in_the_code(fmt, text, step, expected):
    from TabCodeEditor import CodeWindow
    cursor = {}

    class Editor:
        def text(self): return text
        def ensureLineVisible(self, line): pass
        def setCursorPosition(self, line, index): cursor['line'] = line
        def setSelection(self, *args): pass
        def setFocus(self): pass

    fake = type('Fake', (), {})()
    fake.editor, fake.format = Editor(), fmt
    assert (CodeWindow.showStep(fake, step), cursor.get('line')) == expected


def test_a_nested_lazily_loaded_folder_is_expanded_and_names_are_matched_loosely(make_window, tmp_path):
    (tmp_path / 'flows').mkdir()
    (tmp_path / 'tools' / 'deep' / 'deeper').mkdir(parents=True)
    shutil.copy(FIXTURES / 'echo.cwl', tmp_path / 'tools' / 'deep' / 'deeper' / 'echo.cwl')
    shutil.copy(FIXTURES / 'uppercase.cwl', tmp_path / 'Tools-Upper.cwl')
    (tmp_path / 'flows' / 'wf.cwl').write_text(
        "cwlVersion: v1.2\nclass: Workflow\ninputs:\n  message: string\noutputs:\n  out:\n    type: string\n"
        "    outputSource: up/uppercase_message\nsteps:\n  echo:\n    run: ../tools/deep/deeper/echo.cwl\n"
        "    in:\n      message: message\n    out: [out]\n  up:\n    run: ../tools-upper.cwl\n    in:\n      message:\n"
        "        source: echo/out\n    out: [uppercase_message]\n")
    window = make_window(tmp_path)
    park_cursor()
    window.openDocument(str(tmp_path / 'flows' / 'wf.cwl'))
    pump(15)
    document = list(window.open_windows.values())[-1]
    graph = document.workflow_editor.graph
    viewer = graph.graph.viewer()
    pump(8)
    click(viewer, graph_point(graph, 'echo'))
    root = str(tmp_path.resolve())
    assert selected(window) == root + '/tools/deep/deeper/echo.cwl'
    click(viewer, graph_point(graph, 'up'))
    assert selected(window) == root + '/Tools-Upper.cwl', "the step names it in lower case"

    # pointing at the name underlines it and shows a tooltip, pointing at the circle does not
    echo = graph.graph.get_node_by_name('echo').view
    QTest.mouseMove(viewer.viewport(), graph_point(graph, 'echo'))
    pump(4)
    assert echo._label_hovered and 'echo.cwl' in echo.toolTip()
    QTest.mouseMove(viewer.viewport(), graph_point(graph, 'echo', 'circle'))
    pump(4)
    assert not echo._label_hovered and echo.toolTip() == ''


# ---------------------------------------------------------------------------------------- moving around
def empty_point(viewer) -> QPoint:
    """A viewport position with no node, edge or label within the viewer's pick area."""
    viewport = viewer.viewport()
    for y in range(viewport.height() - 30, 30, -20):
        for x in range(30, viewport.width() - 30, 20):
            if not viewer._items_near(viewer.mapToScene(QPoint(x, y)), None, 40, 40):
                return QPoint(x, y)
    raise AssertionError('no empty canvas point')


def test_dragging_the_empty_canvas_moves_it(window, workflow):
    _document, graph, viewer = workflow
    viewport = viewer.viewport()
    viewer._set_viewer_zoom(400, pos=QPoint(viewport.width() // 2, viewport.height() // 2))       # magnified
    pump(4)
    echo_before, upper_before = graph_point(graph, 'echo', 'circle'), graph_point(graph, 'uppercase', 'circle')
    position = graph.graph.get_node_by_name('echo').view.pos()
    start = empty_point(viewer)
    QTest.mousePress(viewport, LEFT, NO_MODIFIER, start)
    for step in (QPoint(4, 3), QPoint(30, 12), QPoint(80, 25), QPoint(120, 40)):
        QTest.mouseMove(viewport, start + step)
        pump(2)
    assert not viewer._rubber_band.isVisible() and QApplication.overrideCursor() is not None
    QTest.mouseRelease(viewport, LEFT, NO_MODIFIER, start + QPoint(120, 40))
    pump(4)
    moved = graph_point(graph, 'echo', 'circle') - echo_before
    assert near(moved, QPoint(120, 40), 0)
    assert graph_point(graph, 'uppercase', 'circle') - upper_before == moved
    assert graph.graph.get_node_by_name('echo').view.pos() == position, "the nodes keep their place in the workflow"
    assert QApplication.overrideCursor() is None and not viewer.LMB_state
    for dx, dy in ((-60, 10), (25, -35)):               # repeated strokes follow the mouse
        base, start = graph_point(graph, 'echo', 'circle'), empty_point(viewer)
        QTest.mousePress(viewport, LEFT, NO_MODIFIER, start)
        QTest.mouseMove(viewport, start + QPoint(dx // 2, dy // 2))
        QTest.mouseMove(viewport, start + QPoint(dx, dy))
        QTest.mouseRelease(viewport, LEFT, NO_MODIFIER, start + QPoint(dx, dy))
        pump(4)
        assert near(graph_point(graph, 'echo', 'circle') - base, QPoint(dx, dy))


def test_the_other_mouse_actions_on_the_canvas_are_unchanged(window, workflow):
    _document, graph, viewer = workflow
    viewport = viewer.viewport()
    # a node is dragged, not the canvas
    view_before = viewer.mapToScene(QPoint(0, 0))
    item = graph.graph.get_node_by_name('uppercase').view
    position, start = item.pos(), graph_point(graph, 'uppercase', 'circle')
    QTest.mousePress(viewport, LEFT, NO_MODIFIER, start)
    for step in (QPoint(20, 10), QPoint(50, 30)):
        QTest.mouseMove(viewport, start + step)
        pump(2)
    QTest.mouseRelease(viewport, LEFT, NO_MODIFIER, start + QPoint(50, 30))
    pump(4)
    assert item.pos() != position and viewer.mapToScene(QPoint(0, 0)) == view_before
    # Shift + drag selects with a rectangle
    QTest.mousePress(viewport, LEFT, Qt.KeyboardModifier.ShiftModifier, QPoint(10, 10))
    viewer.SHIFT_state = True
    QTest.mouseMove(viewport, QPoint(200, 200))
    QTest.mouseMove(viewport, QPoint(viewport.width() - 10, viewport.height() - 10))
    pump(2)
    assert viewer._rubber_band.isVisible() and viewer.mapToScene(QPoint(0, 0)) == view_before
    QTest.mouseRelease(viewport, LEFT, Qt.KeyboardModifier.ShiftModifier, QPoint(viewport.width() - 10, viewport.height() - 10))
    viewer.SHIFT_state = False
    pump(4)
    # a click on the empty canvas clears the selection and does not move it
    graph.graph.get_node_by_name('echo').set_selected(True)
    pump(2)
    click(viewer, empty_point(viewer))
    assert not graph.graph.get_node_by_name('echo').selected() and viewer.mapToScene(QPoint(0, 0)) == view_before
    # Alt + drag still pans
    base, start = graph_point(graph, 'echo', 'circle'), empty_point(viewer)
    viewer.ALT_state = True
    QTest.mousePress(viewport, LEFT, Qt.KeyboardModifier.AltModifier, start)
    QTest.mouseMove(viewport, start + QPoint(20, 10))
    QTest.mouseMove(viewport, start + QPoint(40, 20))
    QTest.mouseRelease(viewport, LEFT, Qt.KeyboardModifier.AltModifier, start + QPoint(40, 20))
    viewer.ALT_state = False
    pump(4)
    assert near(graph_point(graph, 'echo', 'circle') - base, QPoint(40, 20))


def wheel(viewport, pixel, angle, modifiers=NO_MODIFIER, phase=Qt.ScrollPhase.NoScrollPhase, position=QPoint(200, 200)):
    event = QWheelEvent(QPointF(position), QPointF(viewport.mapToGlobal(position)), pixel, angle,
                        Qt.MouseButton.NoButton, modifiers, phase, False)
    QApplication.sendEvent(viewport, event)
    pump(3)


def test_trackpad_pinch_wheel_and_keys(window, workflow):
    _document, graph, viewer = workflow
    viewport = viewer.viewport()
    scale = lambda: GraphItems.viewScale(viewer)
    # two-finger scroll moves the canvas (the content follows the fingers) and does not zoom
    before, zoom = graph_point(graph, 'echo', 'circle'), scale()
    wheel(viewport, QPoint(30, -20), QPoint(0, 0), phase=Qt.ScrollPhase.ScrollUpdate)
    assert near(graph_point(graph, 'echo', 'circle') - before, QPoint(30, -20)) and abs(scale() - zoom) < 1e-9
    # Cmd/Ctrl + scroll zooms around the cursor; a mouse wheel zooms too
    at = QPoint(300, 250)
    anchor = viewer.mapToScene(at)
    wheel(viewport, QPoint(0, 0), QPoint(0, 120), modifiers=CTRL, position=at)
    assert scale() > zoom * 1.05 and near(viewer.mapFromScene(anchor), at)
    zoom = scale()
    wheel(viewport, QPoint(0, 0), QPoint(0, 120))
    assert scale() != zoom
    for _ in range(60):
        wheel(viewport, QPoint(0, 0), QPoint(0, 400), modifiers=CTRL)
    assert scale() <= GraphItems.MAX_SCALE + 1e-6
    for _ in range(120):
        wheel(viewport, QPoint(0, 0), QPoint(0, -400), modifiers=CTRL)
    assert scale() >= GraphItems.MIN_SCALE - 1e-6
    GraphItems.fitToViewport(graph.graph)
    pump(3)
    # pinch
    zoom, local = scale(), QPointF(250, 250)
    event = QNativeGestureEvent(Qt.NativeGestureType.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(), 2,
                                local, local, QPointF(viewport.mapToGlobal(QPoint(250, 250))), 0.25, QPointF(), 0)
    QApplication.sendEvent(viewport, event)
    pump(3)
    assert abs(scale() / zoom - 1.25) < 0.02
    # keys: arrows move (Shift: four times as far), + and - zoom, 0 fits
    GraphItems.fitToViewport(graph.graph)
    pump(3)
    base = graph_point(graph, 'echo', 'circle')
    QTest.keyClick(viewer, Qt.Key.Key_Left)
    assert near(graph_point(graph, 'echo', 'circle') - base, QPoint(60, 0))
    QTest.keyClick(viewer, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert near(graph_point(graph, 'echo', 'circle') - base, QPoint(60, -240))
    zoom = scale()
    QTest.keyClick(viewer, Qt.Key.Key_Plus)
    assert scale() > zoom
    QTest.keyClick(viewer, Qt.Key.Key_Minus)
    assert abs(scale() - zoom) < 1e-6
    QTest.keyClick(viewer, Qt.Key.Key_Plus)
    QTest.keyClick(viewer, Qt.Key.Key_Plus)
    QTest.keyClick(viewer, Qt.Key.Key_0)
    pump(3)
    assert scale() <= 1.0


def test_holding_space_moves_the_canvas_from_anywhere(window, workflow):
    _document, graph, viewer = workflow
    viewport = viewer.viewport()
    GraphItems.fitToViewport(graph.graph)
    pump(3)
    item = graph.graph.get_node_by_name('echo').view
    position, base = item.pos(), graph_point(graph, 'echo', 'circle')
    QTest.keyPress(viewer, Qt.Key.Key_Space)
    start = graph_point(graph, 'echo', 'circle')
    QTest.mousePress(viewport, LEFT, NO_MODIFIER, start)
    for dx, dy in ((10, 8), (40, 20), (90, 35)):
        QTest.mouseMove(viewport, start + QPoint(dx, dy))
        pump(2)
    QTest.mouseRelease(viewport, LEFT, NO_MODIFIER, start + QPoint(90, 35))
    QTest.keyRelease(viewer, Qt.Key.Key_Space)
    pump(3)
    assert near(graph_point(graph, 'echo', 'circle') - base, QPoint(90, 35)) and item.pos() == position
    assert QApplication.overrideCursor() is None and not viewer.LMB_state


def test_linked_views_pan_and_zoom_together(window, workflow):
    document, graph, viewer = workflow
    window.tabs.detachTab(document)
    pump(10)
    other = open_documents(window, ['51-workflow.cwl'], host=window)['51-workflow.cwl']
    detached = window.detached_windows[0]
    detached.show()
    pump(10)
    graph2 = other.workflow_editor.graph
    viewer2 = graph2.graph.viewer()
    assert viewer.isVisible() and viewer2.isVisible()
    GraphItems.fitToViewport(graph.graph)
    GraphItems.fitToViewport(graph2.graph)
    pump(3)
    first, second = graph_point(graph, 'echo', 'circle'), graph_point(graph2, 'echo', 'circle')
    GraphItems.panViewer(viewer, 25, 10)                    # not linked: the other graph stays
    pump(2)
    assert graph_point(graph2, 'echo', 'circle') == second
    GraphItems.LINK.setEnabled(True)
    pump(3)
    first, second = graph_point(graph, 'echo', 'circle'), graph_point(graph2, 'echo', 'circle')
    GraphItems.panViewer(viewer, 40, -15)
    pump(2)
    assert near(graph_point(graph, 'echo', 'circle') - first, QPoint(40, -15))
    assert near(graph_point(graph2, 'echo', 'circle') - second, QPoint(40, -15))
    zoom1, zoom2 = GraphItems.viewScale(viewer), GraphItems.viewScale(viewer2)
    GraphItems.zoomViewer(viewer, 1.3, QPoint(250, 250))
    pump(2)
    assert abs(GraphItems.viewScale(viewer) / zoom1 - 1.3) < 1e-3 and abs(GraphItems.viewScale(viewer2) / zoom2 - 1.3) < 1e-3
    # the Window menu follows the setting; turning it off unlinks
    def link_action():
        menu = [a.menu() for a in window.menuBar().actions() if a.text().replace('&', '') == 'Window'][0]
        return [a for a in menu.actions() if a.text() == 'Link Workflow Views'][0]
    assert link_action().isChecked()
    GraphItems.LINK.setEnabled(False)
    pump(3)
    assert not link_action().isChecked()
    second = graph_point(graph2, 'echo', 'circle')
    GraphItems.panViewer(viewer, 30, 30)
    pump(2)
    assert graph_point(graph2, 'echo', 'circle') == second


# ---------------------------------------------------------------------------------------- the editor layout
def test_the_canvas_fills_the_workflow_editor_and_still_takes_dropped_files(window, workflow, tmp_path):
    """The toolbar above the canvas (Add Step, Duplicate Step, legend, drop area) is gone; files dropped on the canvas become steps."""
    import shutil
    from PyQt6.QtCore import QMimeData, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDropEvent
    document, graph, viewer = workflow
    editor = document.workflow_editor
    for name in ('add_step_btn', 'duplicate_step_btn', 'drop_zone'):
        assert not hasattr(editor, name), name
    assert editor.layout().count() == 1 and editor.layout().itemAt(0).widget() is editor.splitter, "nothing above the canvas"
    assert editor.splitter.geometry().top() == 0
    from PyQt6.QtWidgets import QLabel
    assert not [label.text() for label in editor.findChildren(QLabel) if label.text() in ('Drop CWL files here', 'Inputs:', 'Outputs:', 'Steps:')]

    # a document dropped on the canvas becomes a step
    shutil.copy(FIXTURES / '01-hello-world.cwl', tmp_path / 'hello.cwl')
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / 'hello.cwl'))])
    point = QPointF(200, 200)
    steps = len(graph.graph.get_nodes_by_type('cwled.step.StepNode'))
    enter = QDragEnterEvent(point.toPoint(), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewer.viewport(), enter)
    assert enter.isAccepted(), "the canvas accepts a CWL file"
    drop = QDropEvent(point, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewer.viewport(), drop)
    pump(15)
    assert len(graph.graph.get_nodes_by_type('cwled.step.StepNode')) == steps + 1
    # something that is not a CWL file is refused
    text = QMimeData()
    text.setText('not a file')
    refused = QDragEnterEvent(point.toPoint(), Qt.DropAction.CopyAction, text, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewer.viewport(), refused)
    assert not refused.isAccepted()


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
