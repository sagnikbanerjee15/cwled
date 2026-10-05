"""
The window with the logo that shows while CWLed starts.

Starting takes a few seconds, most of it importing the libraries, so the window has to be there *before*
that: ``cwled.py`` calls ``start()`` first, and only then imports ``main`` (which imports everything). The
module is kept light for that reason (Qt and the logo, nothing else). ``main.main()`` reports how far it is
with ``progress()`` and closes the window with ``finish()`` when the main window is there.

It does not show with ``--no-splash`` (or ``--version``/``--help``), with the environment variable
``CWLED_NO_SPLASH`` set, on Qt's ``offscreen`` platform (the tests) or when ``show_splash`` is false in the
configuration of the user (Configuration > General).
"""
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable, Mapping, Optional

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QGuiApplication, QLinearGradient, QPainter, QPen,
                         QPixmap, QRadialGradient)
from PyQt6.QtWidgets import QApplication, QSplashScreen

import logo
from helperFunctions import getResourcePath

SIZE = QSize(560, 340)
MIN_SECONDS = 1.0               # the logo stays at least this long, so that it can be seen when the start is quick
FADE_MILLISECONDS = 160
OFF_FLAGS = ('--no-splash', '--version', '-h', '--help')

BACKGROUND_TOP = '#262a32'
BACKGROUND_BOTTOM = '#0f1115'
TEXT = '#f4f5f7'
MUTED = '#8f98a8'
FAINT = '#5f6673'
TRACK = '#2f343d'
FAMILY = 'Montserrat'


def _version() -> str:
    try:
        from version import __version__
        return str(__version__)
    except Exception:
        return ''


def loadFonts() -> bool:
    """Register the bundled Montserrat fonts (the application does it again, with the theme, later)."""
    found = False
    for name in ('Montserrat-Regular.ttf', 'Montserrat-Light.ttf'):
        path = getResourcePath() / 'fonts' / name
        if path.is_file() and QFontDatabase.addApplicationFont(str(path)) >= 0:
            found = True
    return found


def _font(size: float, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    font = QFont(FAMILY)
    font.setPointSizeF(size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def paintCard(painter: QPainter, size: QSize, version: str = ''):
    """The part of the window that does not change: the card, the mark, the name and the line below it."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    width, height = size.width(), size.height()
    card = QRectF(0.5, 0.5, width - 1, height - 1)
    background = QLinearGradient(0, 0, 0, height)
    background.setColorAt(0, QColor(BACKGROUND_TOP))
    background.setColorAt(1, QColor(BACKGROUND_BOTTOM))
    painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
    painter.setBrush(QBrush(background))
    painter.drawRoundedRect(card, 18, 18)

    # a soft raspberry light behind the mark
    centre = QPointF(width / 2, 116)
    glow = QRadialGradient(centre, 150)
    glow.setColorAt(0, QColor(255, 95, 143, 46))
    glow.setColorAt(1, QColor(255, 95, 143, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(centre, 150, 150)

    mark = 150
    logo.paintMark(painter, QRectF((width - mark) / 2, 38, mark, mark), tile=False)

    # CWLed: "CWL" in the regular weight, "ed" in the light one, as in the title of the side panel
    painter.setPen(QColor(TEXT))
    regular, light = _font(36, QFont.Weight.Normal, 1.0), _font(36, QFont.Weight.Light, 1.0)
    painter.setFont(regular)
    advance_cwl = painter.fontMetrics().horizontalAdvance('CWL')
    painter.setFont(light)
    advance_ed = painter.fontMetrics().horizontalAdvance('ed')
    left = (width - advance_cwl - advance_ed) / 2
    baseline = 246
    painter.setFont(regular)
    painter.drawText(QPointF(left, baseline), 'CWL')
    painter.setFont(light)
    painter.drawText(QPointF(left + advance_cwl, baseline), 'ed')

    painter.setPen(QColor(MUTED))
    painter.setFont(_font(8.5, QFont.Weight.Normal, 2.6))
    painter.drawText(QRectF(0, baseline + 12, width, 20), Qt.AlignmentFlag.AlignHCenter, 'COMMON WORKFLOW LANGUAGE EDITOR')

    # the track of the progress bar
    track = _trackRect(size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(TRACK))
    painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
    if version:
        painter.setPen(QColor(FAINT))
        painter.setFont(_font(8.5))
        painter.drawText(QRectF(0, height - 30, width - 22, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         f"version {version}")


def _trackRect(size: QSize) -> QRectF:
    return QRectF((size.width() - 240) / 2, size.height() - 62, 240, 3)


def paintProgress(painter: QPainter, size: QSize, message: str, fraction: float):
    """The part that changes: the filled part of the bar and what is being done."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    track = _trackRect(size)
    fraction = max(0.0, min(1.0, fraction))
    if fraction > 0:
        filled = QRectF(track.left(), track.top(), max(track.height(), track.width() * fraction), track.height())
        gradient = QLinearGradient(track.left(), 0, track.right(), 0)
        gradient.setColorAt(0, QColor(logo.EDGE_START))
        gradient.setColorAt(1, QColor(logo.EDGE_END))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(filled, track.height() / 2, track.height() / 2)
    if message:
        painter.setPen(QColor(MUTED))
        painter.setFont(_font(9.5))
        painter.drawText(QRectF(0, track.bottom() + 8, size.width(), 20), Qt.AlignmentFlag.AlignHCenter, message)


def cardPixmap(device_pixel_ratio: float = 1.0, version: str = '') -> QPixmap:
    pixmap = QPixmap(round(SIZE.width() * device_pixel_ratio), round(SIZE.height() * device_pixel_ratio))
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paintCard(painter, SIZE, version)
    painter.end()
    return pixmap


class LaunchSplash(QSplashScreen):
    """The logo, the name, and a bar that fills as CWLed starts."""

    def __init__(self, version: str = ''):
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        super().__init__(cardPixmap(ratio, version))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._message = ''
        self._fraction = 0.0
        self.started = time.monotonic()

    def drawContents(self, painter: QPainter):
        paintProgress(painter, SIZE, self._message, self._fraction)

    def setProgress(self, message: str, fraction: Optional[float] = None):
        self._message = message
        if fraction is not None:
            self._fraction = fraction
        self.repaint()
        QApplication.processEvents()

    @property
    def fraction(self) -> float:
        return self._fraction

    @property
    def message(self) -> str:
        return self._message


# ------------------------------------------------------------------------------------------------ the one window
_splash: Optional[LaunchSplash] = None
_app = None                      # the application, kept: it is gone (with every window) when its last reference is


def _enabledInUserConfig() -> bool:
    """False if the configuration of the user says ``show_splash: false`` (read as text: the splash comes first)."""
    try:
        from platformdirs import user_config_path
        text = (Path(user_config_path(appname='cwled')) / 'cwled.yaml').read_text(encoding='utf-8', errors='replace')
    except Exception:
        return True
    return not re.search(r'^\s*show_splash\s*:\s*(false|no|off|0)\s*(#.*)?$', text, re.IGNORECASE | re.MULTILINE)


def wanted(argv: Optional[Iterable[str]] = None, environ: Optional[Mapping[str, str]] = None, check_config: bool = True) -> bool:
    """Whether the window shows for these arguments, this environment and the configuration of the user."""
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    if any(argument in OFF_FLAGS for argument in argv):
        return False
    if environ.get('CWLED_NO_SPLASH') or environ.get('QT_QPA_PLATFORM', '').lower() in ('offscreen', 'minimal'):
        return False
    return _enabledInUserConfig() if check_config else True


def start(argv: Optional[list] = None) -> Optional[LaunchSplash]:
    """Show the window now (creating the application if there is none yet). None if it is not wanted."""
    global _splash, _app
    if _splash is not None:
        return _splash
    if not wanted():
        return None
    try:
        _app = app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
        loadFonts()
        _splash = LaunchSplash(_version())
        _splash.show()
        app.processEvents()
        _splash.setProgress("Starting CWLed", 0.06)
    except Exception:                                   # the logo is a courtesy: never the reason not to start
        _splash = None
    return _splash


def current() -> Optional[LaunchSplash]:
    return _splash


def progress(message: str, fraction: Optional[float] = None):
    """Say what is being done (and how far along; 0 to 1). Does nothing without the window."""
    if _splash is not None:
        _splash.setProgress(message, fraction)


def finish(window=None, wait: bool = True):
    """Close the window once ``window`` is shown; it stays long enough to be seen, and fades out."""
    global _splash
    splash, _splash = _splash, None
    if splash is None:
        return
    splash.setProgress("Ready", 1.0)
    if wait:
        while time.monotonic() - splash.started < MIN_SECONDS:
            QApplication.processEvents()
            time.sleep(0.02)
        steps = max(1, FADE_MILLISECONDS // 20)
        for step in range(steps - 1, -1, -1):
            splash.setWindowOpacity(step / steps)
            QApplication.processEvents()
            time.sleep(0.02)
    if window is not None:
        splash.finish(window)
    else:
        splash.close()
    splash.deleteLater()
