"""Small helpers to drive the interface with (simulated) mouse and keys."""
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

LEFT = Qt.MouseButton.LeftButton
NO_MODIFIER = Qt.KeyboardModifier.NoModifier


def park_cursor():
    """
    Move the mouse pointer away from the windows: a simulated mouse leaves the pointer
    where it last was, over whatever the test opens next.
    """
    QCursor.setPos(0, 0)


def pump(count: int = 5):
    """Let the event loop run (timers, layouts, queued signals)."""
    for _ in range(count):
        QApplication.processEvents()
        QTest.qWait(10)


def wait_until(condition, timeout: float = 15.0, message: str = "the condition did not become true"):
    """Let the event loop run until ``condition()`` is true (work done in other threads reports back through it)."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        QApplication.processEvents()
        QTest.qWait(10)
    assert condition(), message


def titles(tabs):
    return [tabs.tabText(index) for index in range(tabs.count())]


def tab_center(tabs, index: int) -> QPoint:
    """The centre of a tab, in screen coordinates."""
    bar = tabs.tabBar()
    return bar.mapToGlobal(bar.tabRect(index).center())


def drag(widget, start: QPoint, path, release: bool = True):
    """
    Press the left button on ``widget`` at the screen position ``start``, move through
    ``path`` (screen positions) and release at the last one. The positions are converted
    each time: a window that follows the mouse moves under it.
    """
    QTest.mousePress(widget, LEFT, NO_MODIFIER, widget.mapFromGlobal(start))
    pump(2)
    for point in path:
        QTest.mouseMove(widget, widget.mapFromGlobal(point))
        pump(2)
    if release:
        QTest.mouseRelease(widget, LEFT, NO_MODIFIER, widget.mapFromGlobal(path[-1]))
        pump(8)


def near(a: QPoint, b: QPoint, tolerance: int = 1) -> bool:
    """Positions that differ by a pixel of rounding are the same."""
    return abs(a.x() - b.x()) <= tolerance and abs(a.y() - b.y()) <= tolerance


def open_documents(window, names, host=None):
    """Open documents of the test directory (by file name) and return them by file name."""
    from conftest import FIXTURES
    park_cursor()
    for name in names:
        window.openDocument(str(FIXTURES / name), host=host or window)
        pump(12)
    return documents_by_name(window)


def documents_by_name(window):
    from pathlib import Path
    return {Path(str(doc.file_path)).name: doc for doc in window.open_windows.values() if doc.file_path}


def graph_point(graph, step: str, where: str = 'name') -> QPoint:
    """The position, in the viewport of the graph, of the name or of the circle of a node."""
    item = graph.graph.get_node_by_name(step).view
    viewer = graph.graph.viewer()
    if where == 'name':
        scene = item.mapToScene(item._label_rect.center())
    else:
        scene = item.mapToScene(QPointF(item._radius, item._radius))
    return viewer.mapFromScene(scene)
