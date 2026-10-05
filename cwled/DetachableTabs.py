"""
Document tabs that can be torn off into their own window and dragged back.

``DetachableTabWidget`` is a tab widget whose tabs can be dragged away from
its tab bar. The tab then leaves for a window of its own (created by the
function given to ``setWindowFactory``) that follows the mouse until the button
is released:

* released over the tab strip of another window (or of the same one), the tab
  is *reattached* there, at the position of the mouse, and the window that
  carried it goes away;
* released anywhere else, the window stays where it is.

The only tab of a window that is not the main one (``windowFollowsLastTab``)
is not torn off again: its whole window is moved instead.

There is no window management beyond that: the tab widgets only know the
factory and emit ``emptied`` when their last tab is gone and ``tabTransferred``
when they take over a tab from another tab widget, so the application decides
what a window is and what is merged when tabs move.

The same moves are available without the mouse from the context menu of a tab.
"""
import itertools
import logging
import weakref
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter
from PyQt6.QtWidgets import QApplication, QMenu, QTabBar, QTabWidget, QWidget

import theme

logger = logging.getLogger(__name__)

# How far (px) the pointer has to leave the tab bar before the tab is torn off
TEAR_OFF_DISTANCE = 30
# Widgets with this property set to False stay in their tab widget
DETACHABLE_PROPERTY = 'cwledDetachable'
# Opacity of the window that follows the mouse, and when it is over a tab strip that would take the tab
# (it hides the strip and the mark of where the tab would land)
DRAG_OPACITY = 0.8
DROP_OPACITY = 0.35
# Where the pointer is held on the tab of a window that was just created (from the left of its tab bar)
TAB_GRAB_X = 70
# A window dropped with the pointer this close (px) to the left or right edge of the screen fills that half of it
SNAP_MARGIN = 20

# A factory gets the tab widget the tab comes from and the tab, and returns the
# (empty) tab widget of the new window, which it keeps track of.
WindowFactory = Callable[['DetachableTabWidget', QWidget], Optional['DetachableTabWidget']]

_registry: List[weakref.ref] = []
# Qt does not tell the stacking order of windows. The window that was activated last is the one on top,
# so every tab widget notes when its window was (see DetachableTabWidget.activation).
_activations = itertools.count(1)


def allTabWidgets() -> List['DetachableTabWidget']:
    """Every live detachable tab widget, i.e. every window tabs can move to."""
    live = []
    for reference in list(_registry):
        tabs = reference()
        if tabs is None or sip.isdeleted(tabs):
            _registry.remove(reference)
        else:
            live.append(tabs)
    return live


def moveTab(widget: QWidget, target: 'DetachableTabWidget', index: int = -1) -> bool:
    """
    Move the tab of ``widget`` to the tab widget ``target`` (at ``index``, by
    default at the end), keeping its title, icon and tool tip, and select it.

    Returns:
        True if the tab moved (or was reordered).
    """
    source = DetachableTabWidget.tabsOf(widget)
    if source is None or source.indexOf(widget) < 0:
        return False
    if source is target:
        # reorder within the tab bar
        position = source.indexOf(widget)
        index = source.count() - 1 if index < 0 or index >= source.count() else index
        if index > position:
            index -= 1
        if index != position:
            source.tabBar().moveTab(position, index)
        source.setCurrentWidget(widget)
        return True
    state = source.takeTab(widget)
    target.putTab(widget, state, index)
    target.setCurrentWidget(widget)
    target.tabTransferred.emit(widget, source)
    return True


class DetachableTabBar(QTabBar):
    """The tab bar of a ``DetachableTabWidget``: tears tabs off and marks where a tab would land."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_widget: Optional[QWidget] = None   # the page of the tab under the mouse button
        self._session: Optional[_TearOffSession] = None
        self._drop_index = -1                          # insertion mark while a tab is dragged over

    def tabWidget(self) -> Optional['DetachableTabWidget']:
        parent = self.parentWidget()
        return parent if isinstance(parent, DetachableTabWidget) else None

    # -- drag ------------------------------------------------------------------
    def mousePressEvent(self, event):
        self._press_widget = None
        tabs = self.tabWidget()
        if tabs is not None and event.button() == Qt.MouseButton.LeftButton:
            index = self.tabAt(event.position().toPoint())
            if index >= 0:
                self._press_widget = tabs.widget(index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._session is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._session.move(event.globalPosition().toPoint())
            else:
                # the release was missed (e.g. another application took the mouse)
                self._endSession(event.globalPosition().toPoint())
            event.accept()
            return
        if (self._press_widget is not None and event.buttons() & Qt.MouseButton.LeftButton
                and self._farFromBar(event.position().toPoint()) and self._tearOff(event)):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._session is not None:
            self._endSession(event.globalPosition().toPoint())
            event.accept()
            return
        self._press_widget = None
        super().mouseReleaseEvent(event)

    def _farFromBar(self, position: QPoint) -> bool:
        margin = TEAR_OFF_DISTANCE
        return not self.rect().adjusted(-margin, -margin, margin, margin).contains(position)

    def _tearOff(self, event: QMouseEvent) -> bool:
        tabs = self.tabWidget()
        widget = self._press_widget
        if tabs is None or widget is None or sip.isdeleted(widget) or not tabs.isDetachable(widget):
            return False
        # The tab bar is dragging the tab to reorder it: let it finish (the tab
        # goes back to its slot) before the tab leaves.
        release = QMouseEvent(QEvent.Type.MouseButtonRelease, event.position(), event.globalPosition(),
                              Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, event.modifiers())
        super().mouseReleaseEvent(release)
        self._press_widget = None
        self._session = tabs.beginTearOff(widget, event.globalPosition().toPoint())
        return self._session is not None

    def _endSession(self, global_position: QPoint):
        session, self._session = self._session, None
        self._press_widget = None
        if session is not None:
            session.finish(global_position)

    # -- insertion mark ----------------------------------------------------------
    def insertionIndexAt(self, position: QPoint) -> int:
        """The index a tab dropped at ``position`` (in this bar) would get."""
        for index in range(self.count()):
            if position.x() < self.tabRect(index).center().x():
                return index
        return self.count()

    def setDropIndex(self, index: int):
        if index != self._drop_index:
            self._drop_index = index
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_index < 0:
            return
        if self._drop_index < self.count():
            x = self.tabRect(self._drop_index).left()
        elif self.count():
            x = self.tabRect(self.count() - 1).right()
        else:
            x = 0
        painter = QPainter(self)
        painter.fillRect(QRect(x - 1, 0, 3, self.height()), QColor(theme.SKY))

    # -- menu --------------------------------------------------------------------
    def contextMenuEvent(self, event):
        tabs = self.tabWidget()
        index = self.tabAt(event.pos())
        if tabs is None or index < 0:
            super().contextMenuEvent(event)
            return
        tabs.showTabMenu(index, event.globalPos())


class DetachableTabWidget(QTabWidget):
    """A tab widget whose tabs can be torn off into their own window and dragged back."""

    emptied = pyqtSignal()                          # the last tab left or was closed
    tabTransferred = pyqtSignal(QWidget, QWidget)   # (page, tab widget it came from)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(DetachableTabBar(self))
        self.setMovable(True)
        self._factory: Optional[WindowFactory] = None
        # called with (page, menu) when the menu of a tab is shown, to add entries to it
        self.menuHook: Optional[Callable[[QWidget, QMenu], None]] = None
        # The window of this tab widget is the one a tab was torn off into: its
        # only tab is not torn off again, the window is moved instead.
        self.windowFollowsLastTab = False
        self.activation = next(_activations)   # when the window was last activated; a new window is on top
        _registry.append(weakref.ref(self))

    def setWindowFactory(self, factory: Optional[WindowFactory]):
        self._factory = factory

    # -- tabs ----------------------------------------------------------------------
    @staticmethod
    def tabsOf(widget: Optional[QWidget]) -> Optional['DetachableTabWidget']:
        """The detachable tab widget that shows ``widget`` as a page, or None."""
        parent = widget.parentWidget() if widget is not None else None
        while parent is not None:
            if isinstance(parent, DetachableTabWidget):
                return parent
            parent = parent.parentWidget()
        return None

    def isDetachable(self, widget: QWidget) -> bool:
        return widget.property(DETACHABLE_PROPERTY) is not False

    def widgets(self) -> List[QWidget]:
        return [self.widget(index) for index in range(self.count())]

    def takeTab(self, widget: QWidget) -> Dict:
        """Remove the tab of ``widget`` (the page lives on) and return how it looked."""
        index = self.indexOf(widget)
        state = {
            'icon': self.tabIcon(index),
            'text': self.tabText(index),
            'tooltip': self.tabToolTip(index),
            'enabled': self.isTabEnabled(index),
            'data': self.tabBar().tabData(index),
        }
        self.removeTab(index)
        return state

    def putTab(self, widget: QWidget, state: Dict, index: int = -1) -> int:
        """Insert ``widget`` as a tab that looks like ``state`` (see ``takeTab``)."""
        if index < 0 or index > self.count():
            index = self.count()
        index = self.insertTab(index, widget, state['icon'], state['text'])
        self.setTabToolTip(index, state['tooltip'])
        self.setTabEnabled(index, state['enabled'])
        self.tabBar().setTabData(index, state['data'])
        return index

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.activation = next(_activations)
        super().changeEvent(event)

    def tabRemoved(self, index: int):
        super().tabRemoved(index)
        if self.count() == 0:
            self.emptied.emit()

    def windowLabel(self) -> str:
        """How the window of this tab widget is named in the tab menu."""
        window = self.window()
        label = getattr(window, 'tabWindowLabel', None)
        return label() if callable(label) else window.windowTitle()

    # -- tear off ------------------------------------------------------------------
    def beginTearOff(self, widget: QWidget, global_position: QPoint) -> Optional['_TearOffSession']:
        """
        Start dragging the tab of ``widget`` away: it moves to a window that
        follows the mouse. Returns None if the tab cannot be torn off.
        """
        if not self.isDetachable(widget):
            return None
        if self.windowFollowsLastTab and self.count() == 1:
            window = self.window()
            offset = global_position - window.frameGeometry().topLeft()
            return _TearOffSession(self, window, widget, offset, origin=(None, -1, window.pos()))
        origin_index = self.indexOf(widget)
        window = self.detachTab(widget, activate=False)
        if window is None:
            return None
        new_tabs = DetachableTabWidget.tabsOf(widget)
        # place the window so that the pointer is on the tab, as it was in the old bar
        bar = new_tabs.tabBar()
        inside = bar.mapTo(window, QPoint(TAB_GRAB_X, bar.height() // 2))
        frame = window.geometry().topLeft() - window.frameGeometry().topLeft()
        offset = inside + frame
        window.move(global_position - offset)
        return _TearOffSession(new_tabs, window, widget, offset, origin=(self, origin_index, None))

    def detachTab(self, widget: QWidget, activate: bool = True) -> Optional[QWidget]:
        """
        Move the tab of ``widget`` to a new window, shown where the window
        factory placed it. Returns the window, or None if there is no window
        factory.
        """
        if self._factory is None:
            return None
        target = self._factory(self, widget)
        if target is None:
            return None
        moveTab(widget, target)
        window = target.window()
        # While the tab is dragged the mouse belongs to the tab bar it was pressed in: do not
        # let the new window take the focus from the window of that tab bar.
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate)
        window.show()
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        if activate:
            window.raise_()
            window.activateWindow()
        return window

    # -- menu ----------------------------------------------------------------------
    def showTabMenu(self, index: int, global_position: QPoint):
        widget = self.widget(index)
        if widget is None:
            return
        menu = QMenu(self)
        if self.isDetachable(widget):
            alone = self.windowFollowsLastTab and self.count() == 1
            if self._factory is not None and not alone:
                menu.addAction("Move to New Window", lambda: self.detachTab(widget))
            for other in allTabWidgets():
                if other is self or not other.window().isVisible():
                    continue
                menu.addAction(f"Move to {other.windowLabel()}",
                               lambda _checked=False, other=other: self._moveTo(widget, other))
        if self.menuHook is not None:
            if not menu.isEmpty():
                menu.addSeparator()
            self.menuHook(widget, menu)
        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction("Close", lambda: self.tabCloseRequested.emit(self.indexOf(widget)))
        menu.exec(global_position)

    @staticmethod
    def _moveTo(widget: QWidget, target: 'DetachableTabWidget'):
        if moveTab(widget, target):
            window = target.window()
            window.raise_()
            window.activateWindow()


class _EscapeFilter(QObject):
    """Application wide: Escape cancels the drag of a tab."""

    def __init__(self, session):
        super().__init__()
        self._session = session

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._session.cancel()
            return True
        return False


class _TearOffSession:
    """
    A tab that is being dragged by the mouse: ``window`` follows the pointer
    until the mouse button is released, or Escape cancels the drag.

    ``own_tabs`` is the tab widget of ``window``. It is never a drop target.
    ``origin`` says where to go back to when the drag is cancelled: (the tab widget
    the tab was torn off, its index there, None) for a window that was created
    for the tab, and (None, -1, the position of the window) for a window that was
    moved with its only tab.
    """

    def __init__(self, own_tabs: DetachableTabWidget, window: QWidget, widget: QWidget, offset: QPoint,
                 origin=(None, -1, None)):
        self.own_tabs = own_tabs
        self.window = window
        self.widget = widget
        self.offset = offset          # pointer position in the window frame
        self.origin = origin
        self.done = False             # finished or cancelled
        self._target: Optional[DetachableTabWidget] = None
        window.setWindowOpacity(DRAG_OPACITY)
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        self._escape = _EscapeFilter(self)
        QApplication.instance().installEventFilter(self._escape)

    def _end(self):
        """Undo what the drag changed in the interface."""
        self.done = True
        QApplication.instance().removeEventFilter(self._escape)
        self._mark(None, -1)
        QApplication.restoreOverrideCursor()
        self.window.setWindowOpacity(1.0)

    def _dropTarget(self, global_position: QPoint) -> Tuple[Optional[DetachableTabWidget], int]:
        """The tab widget whose tab strip is under the pointer, and the index a tab would get there."""
        # windows may overlap: the one on top gets the tab
        for tabs in sorted(allTabWidgets(), key=lambda tabs: tabs.activation, reverse=True):
            if tabs is self.own_tabs or tabs.window() is self.window or not tabs.isVisible():
                continue
            bar = tabs.tabBar()
            strip = QRect(tabs.mapToGlobal(QPoint(0, bar.y())), QSize(tabs.width(), bar.height()))
            if strip.contains(global_position):
                return tabs, bar.insertionIndexAt(bar.mapFromGlobal(global_position))
        return None, -1

    def _mark(self, target: Optional[DetachableTabWidget], index: int):
        if self._target is not target and self._target is not None and not sip.isdeleted(self._target):
            self._target.tabBar().setDropIndex(-1)
        self._target = target
        if target is not None:
            target.tabBar().setDropIndex(index)
        if not self.done:
            self.window.setWindowOpacity(DROP_OPACITY if target is not None else DRAG_OPACITY)

    def move(self, global_position: QPoint):
        if self.done:
            return
        self.window.move(global_position - self.offset)
        self._mark(*self._dropTarget(global_position))

    def cancel(self):
        """Escape: the tab goes back where it was torn off."""
        if self.done:
            return
        self._end()
        source, index, position = self.origin
        if source is not None and not sip.isdeleted(source):
            # the window that was made for the tab is empty then and goes away
            moveTab(self.widget, source, index)
            window = source.window()
            window.raise_()
            window.activateWindow()
        elif position is not None:
            self.window.move(position)

    def finish(self, global_position: QPoint):
        if self.done:
            return      # cancelled: the button is released now
        target, index = self._dropTarget(global_position)
        self._end()
        if target is not None:
            # reattach: the window that carried the tab is empty now and goes away
            moveTab(self.widget, target, index)
            window = target.window()
            window.raise_()
            window.activateWindow()
        else:
            if not self._snap(global_position):
                self._keepTitleBarReachable()
            self.window.raise_()
            self.window.activateWindow()

    def _snap(self, global_position: QPoint) -> bool:
        """A window dropped at the left or right edge of the screen fills that half of it."""
        screen = QGuiApplication.screenAt(global_position)
        if screen is None:
            return False
        available = screen.availableGeometry()
        if global_position.x() <= available.left() + SNAP_MARGIN:
            half = QRect(available.left(), available.top(), available.width() // 2, available.height())
        elif global_position.x() >= available.right() - SNAP_MARGIN:
            width = available.width() // 2
            half = QRect(available.right() + 1 - width, available.top(), width, available.height())
        else:
            return False
        placeWindow(self.window, half, within=available)
        return True

    def _keepTitleBarReachable(self):
        """Do not leave the window with its title bar above the screen, where it cannot be grabbed."""
        screen = self.window.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.window.frameGeometry()
        if frame.top() < available.top():
            self.window.move(frame.left(), available.top())


def placeWindow(window: QWidget, frame: QRect, within: Optional[QRect] = None):
    """
    Put a window (its frame, with the title bar) at ``frame``, e.g. half of a screen.
    A window cannot be made smaller than its minimum size: with ``within`` (the
    screen) it is then moved so that it stays inside it, instead of hanging out.
    """
    window.showNormal()
    border = window.frameGeometry().size() - window.geometry().size()
    window.setGeometry(frame.x() + (window.geometry().x() - window.frameGeometry().x()),
                       frame.y() + (window.geometry().y() - window.frameGeometry().y()),
                       max(200, frame.width() - border.width()), max(200, frame.height() - border.height()))
    if within is not None:
        actual = window.frameGeometry()
        if actual.right() > within.right():
            window.move(window.x() - (actual.right() - within.right()), window.y())
        actual = window.frameGeometry()
        if actual.left() < within.left():
            window.move(window.x() + (within.left() - actual.left()), window.y())
