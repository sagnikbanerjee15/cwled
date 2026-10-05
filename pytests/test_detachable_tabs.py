"""Tabs torn off into windows of their own, dragged back, merged workspaces, session restore."""
import shutil
from pathlib import Path

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import data
import workspaceFolders
from conftest import FIXTURES
from qt_helpers import LEFT, NO_MODIFIER, documents_by_name, drag, open_documents, pump, tab_center, titles


def tear_off(window, index, to=QPoint(300, 160)):
    """Drag a tab of the main window out of its tab bar and leave the mouse button down."""
    bar = window.tabs.tabBar()
    start = tab_center(window.tabs, index)
    QTest.mousePress(bar, LEFT, NO_MODIFIER, bar.mapFromGlobal(start))
    pump(2)
    for step in (QPoint(10, 5), QPoint(60, 60), QPoint(150, 120), to):
        QTest.mouseMove(bar, bar.mapFromGlobal(start + step))
        pump(2)
    return bar, start + to


def release(bar, point):
    QTest.mouseRelease(bar, LEFT, NO_MODIFIER, bar.mapFromGlobal(point))
    pump(8)


def test_a_tab_dragged_out_gets_a_window_with_its_own_workspace_panel(window):
    open_documents(window, ['echo.cwl', 'uppercase.cwl'])
    bar, point = tear_off(window, 1)
    assert len(window.detached_windows) == 1
    detached = window.detached_windows[0]
    assert titles(detached.tabs) == ['echo.cwl'] and titles(window.tabs) == ['Welcome', 'uppercase.cwl']
    assert detached.sidebar.isVisible(), "the workspace panel shows in the new window"
    assert QApplication.overrideCursor() is not None
    release(bar, point)
    assert QApplication.overrideCursor() is None and detached.isVisible()
    assert detached.workspace is not workspaceFolders.PRIMARY
    assert detached.workspace.folders() == workspaceFolders.folders()
    assert detached.menuBar().actions(), "a detached window has its own menu bar"


def test_the_workspaces_are_independent_and_merge_when_the_tab_returns(window, tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    open_documents(window, ['echo.cwl', 'uppercase.cwl'])
    bar, point = tear_off(window, 1)
    release(bar, point)
    detached = window.detached_windows[0]
    detached.addWorkspaceFolder(str(other))
    assert str(other.resolve()) in detached.workspace.folders() and str(other.resolve()) not in workspaceFolders.folders()

    # drag it back onto the tab strip of the main window: it lands there and the folders are merged
    dbar = detached.tabs.tabBar()
    start = tab_center(detached.tabs, 0)
    target = tab_center(window.tabs, 1) + QPoint(5, 0)
    window.show()
    drag(dbar, start, [start + QPoint(5, 3), QPoint((start.x() + target.x()) // 2, (start.y() + target.y()) // 2), target])
    pump(10)
    assert sorted(titles(window.tabs)) == ['Welcome', 'echo.cwl', 'uppercase.cwl']
    assert not window.detached_windows, "the emptied window goes away"
    assert str(other.resolve()) in workspaceFolders.folders(), "the workspace of the window was merged"


def test_the_welcome_tab_stays_and_a_click_does_not_detach(window):
    open_documents(window, ['echo.cwl'])
    bar = window.tabs.tabBar()
    start = tab_center(window.tabs, 0)
    drag(bar, start, [start + QPoint(5, 5), start + QPoint(40, 200)])
    assert not window.detached_windows
    start = tab_center(window.tabs, 1)
    drag(bar, start, [start + QPoint(20, 2), start + QPoint(60, 3)])
    assert not window.detached_windows


def test_the_only_tab_of_a_detached_window_moves_the_window(window):
    docs = open_documents(window, ['echo.cwl', 'uppercase.cwl'])
    window.tabs.detachTab(docs['echo.cwl'])
    pump(8)
    detached = window.detached_windows[0]
    detached.move(100, 100)
    pump(3)
    before = detached.pos()
    bar = detached.tabs.tabBar()
    start = tab_center(detached.tabs, 0)
    drag(bar, start, [start + QPoint(10, 40), start + QPoint(80, 120), start + QPoint(200, 160)])
    assert len(window.detached_windows) == 1, "no second window"
    moved = detached.pos() - before
    # the window follows the pointer from where the drag started (the second move)
    assert (moved.x(), moved.y()) == (120, 40)


def test_files_open_in_the_window_that_is_used(window):
    docs = open_documents(window, ['echo.cwl', 'uppercase.cwl', '01-hello-world.cwl'])
    window.tabs.detachTab(docs['echo.cwl'])
    pump(8)
    detached = window.detached_windows[0]
    detached.openFile(str(FIXTURES / '01-hello-world.cwl'))      # already open in the main window: brought forward
    pump(6)
    assert titles(detached.tabs) == ['echo.cwl'] and titles(window.tabs).count('01-hello-world.cwl') == 1
    detached.openFile(str(FIXTURES / '05-input.cwl'))
    pump(10)
    assert '05-input.cwl' in titles(detached.tabs)
    window.activeHost = lambda: detached         # the menu of the detached window: new documents go there
    window.onMenuNewWorkflow()
    pump(10)
    assert len(detached.tabs.widgets()) == 3


def test_reattach_all_and_closing(window):
    docs = open_documents(window, ['echo.cwl', 'uppercase.cwl', '01-hello-world.cwl'])
    window.tabs.detachTab(docs['echo.cwl'])
    pump(8)
    detached = window.detached_windows[0]
    labels = []
    from DetachableTabs import allTabWidgets
    labels = [tabs.windowLabel() for tabs in allTabWidgets()]
    assert 'Main Window' in labels
    detached.reattachAll()
    pump(10)
    assert not window.detached_windows and 'echo.cwl' in titles(window.tabs)
    # closing the last tab of a detached window closes the window
    window.tabs.detachTab(docs['echo.cwl'])
    pump(8)
    detached = window.detached_windows[0]
    count = len(window.open_windows)
    detached.tabs.tabCloseRequested.emit(0)
    pump(10)
    assert not window.detached_windows and len(window.open_windows) == count - 1
    # closing the main window closes everything
    window.tabs.detachTab(docs['uppercase.cwl'])
    pump(8)
    window.close()
    pump(10)
    assert not window.detached_windows and not window.open_windows


def test_two_detached_windows_overlap_and_the_one_on_top_gets_the_drop(window, tmp_path):
    other, third = tmp_path / 'one', tmp_path / 'two'
    other.mkdir()
    third.mkdir()
    docs = open_documents(window, ['echo.cwl', 'uppercase.cwl', '01-hello-world.cwl', '05-input.cwl'])
    window.tabs.detachTab(docs['echo.cwl'])
    window.tabs.detachTab(docs['uppercase.cwl'])
    pump(8)
    d1, d2 = window.detached_windows
    d1.move(50, 50)
    d2.move(700, 50)
    d1.addWorkspaceFolder(str(other))
    d2.addWorkspaceFolder(str(third))
    d1.openFile(str(FIXTURES / '07-record.cwl'))
    pump(10)
    # tear 07-record off d1: the new window is seeded from d1's workspace, not from the main one
    bar = d1.tabs.tabBar()
    start = tab_center(d1.tabs, 1)
    drag(bar, start, [start + QPoint(0, 60), start + QPoint(40, 140), start + QPoint(300, 400)])
    assert len(window.detached_windows) == 3
    d3 = window.detached_windows[2]
    assert titles(d3.tabs) == ['07-record.cwl']
    assert str(other.resolve()) in d3.workspace.folders() and str(third.resolve()) not in d3.workspace.folders()
    # d2 overlaps d1 and was activated last: dropping on the shared area goes to d2, and only d2's workspace changes
    d2.show()
    d2.activateWindow()
    pump(6)
    dbar = d3.tabs.tabBar()
    start = tab_center(d3.tabs, 0)
    target = tab_center(d2.tabs, 0) + QPoint(-30, 0)
    drag(dbar, start, [start + QPoint(3, 3), QPoint((start.x() + target.x()) // 2, (start.y() + target.y()) // 2), target])
    assert titles(d2.tabs)[0] == '07-record.cwl' and len(window.detached_windows) == 2
    assert str(other.resolve()) in d2.workspace.folders() and str(third.resolve()) in d2.workspace.folders()
    assert str(other.resolve()) not in workspaceFolders.folders(), "the main workspace is untouched"
    window.reattachAllWindows()
    pump(10)
    assert not window.detached_windows
    assert {str(other.resolve()), str(third.resolve())} <= set(workspaceFolders.folders())


def test_escape_cancels_a_drag(window):
    open_documents(window, ['echo.cwl', 'uppercase.cwl', '01-hello-world.cwl'])
    before = titles(window.tabs)
    bar, point = tear_off(window, 2, QPoint(200, 180))
    assert len(window.detached_windows) == 1
    QTest.keyClick(window, __import__('PyQt6.QtCore', fromlist=['Qt']).Qt.Key.Key_Escape)
    pump(8)
    assert titles(window.tabs) == before and not window.detached_windows and QApplication.overrideCursor() is None
    QTest.mouseMove(bar, bar.mapFromGlobal(point + QPoint(100, 20)))
    release(bar, point + QPoint(100, 20))
    assert titles(window.tabs) == before and not window.detached_windows

    # the window of a lone tab goes back where it was
    docs = documents_by_name(window)
    window.tabs.detachTab(docs['echo.cwl'])
    pump(8)
    detached = window.detached_windows[0]
    detached.move(120, 90)
    pump(3)
    origin = detached.pos()
    dbar = detached.tabs.tabBar()
    start = tab_center(detached.tabs, 0)
    QTest.mousePress(dbar, LEFT, NO_MODIFIER, dbar.mapFromGlobal(start))
    for step in (QPoint(5, 40), QPoint(60, 80), QPoint(150, 120)):
        QTest.mouseMove(dbar, dbar.mapFromGlobal(start + step))
        pump(2)
    assert detached.pos() != origin
    QTest.keyClick(detached, __import__('PyQt6.QtCore', fromlist=['Qt']).Qt.Key.Key_Escape)
    pump(4)
    QTest.mouseRelease(dbar, LEFT, NO_MODIFIER, dbar.mapFromGlobal(start + QPoint(150, 120)))
    pump(4)
    assert detached.pos() == origin


def test_dropping_at_a_screen_edge_snaps_and_windows_can_be_tiled(window):
    docs = open_documents(window, ['echo.cwl', 'uppercase.cwl'])
    window.tabs.detachTab(docs['echo.cwl'])
    pump(8)
    detached = window.detached_windows[0]
    available = QGuiApplication.primaryScreen().availableGeometry()

    def drop_at(point):
        bar = detached.tabs.tabBar()
        start = tab_center(detached.tabs, 0)
        QTest.mousePress(bar, LEFT, NO_MODIFIER, bar.mapFromGlobal(start))
        for k in (1, 2, 3):
            middle = QPoint(start.x() + (point.x() - start.x()) * k // 3, start.y() + (point.y() - start.y()) * k // 3 + 40 * k)
            QTest.mouseMove(bar, bar.mapFromGlobal(middle))
            pump(2)
        QTest.mouseMove(bar, bar.mapFromGlobal(point))
        QTest.mouseRelease(bar, LEFT, NO_MODIFIER, bar.mapFromGlobal(point))
        pump(6)

    half = max(available.width() // 2, detached.minimumSizeHint().width())     # not narrower than the window can be
    drop_at(QPoint(available.left() + 3, available.top() + 200))
    frame = detached.frameGeometry()
    assert frame.left() == available.left() and abs(frame.width() - half) <= 6 and frame.height() == available.height()
    drop_at(QPoint(available.right() - 3, available.top() + 200))
    assert detached.frameGeometry().right() == available.right()
    detached.resize(500, 400)
    detached.move(200, 120)
    pump(3)
    drop_at(QPoint(available.center().x(), available.top() + 200))
    assert detached.frameGeometry().width() != half, "not near an edge: not snapped"

    window.show()
    window.tabs.detachTab(docs['uppercase.cwl'])
    pump(8)
    window.tileWindows()
    pump(5)
    frames = [w.frameGeometry() for w in (window, *window.detached_windows)]
    assert frames[0].left() == available.left() and frames[-1].right() == available.right()
    assert all(f.left() >= available.left() and f.right() <= available.right() for f in frames), "on the screen"
    assert frames[0].left() < frames[1].left() < frames[2].left()
    assert 'Tile Windows Side by Side' in [a.text() for a in
                                           [m.menu() for m in window.menuBar().actions() if m.text().replace('&', '') == 'Window'][0].actions()]


