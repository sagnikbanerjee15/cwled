"""The logo of CWLed and the window that shows it while the application starts."""
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QLabel

import SplashScreen
import logo
from conftest import REPO
from qt_helpers import pump

LOGO_FILES = REPO / 'resources' / 'logo'


def pixel(image: QImage, x: int, y: int) -> QColor:
    return image.pixelColor(x, y)


def close_to(colour: QColor, expected: str, tolerance: int = 40) -> bool:
    other = QColor(expected)
    return all(abs(a - b) <= tolerance for a, b in ((colour.red(), other.red()), (colour.green(), other.green()),
                                                    (colour.blue(), other.blue())))


# ------------------------------------------------------------------------------------------------ the mark
def test_the_mark_is_well_formed_svg_that_qt_renders(qapp):
    for tile in (True, False):
        svg = logo.markSvg(tile)
        ET.fromstring(svg)                                           # well formed
        assert QSvgRenderer(svg.encode()).isValid()
    assert 'rx="58"' in logo.markSvg(True) and 'rx="58"' not in logo.markSvg(False)


def test_the_mark_draws_a_w_of_five_nodes(qapp):
    image = logo.markImage(512)
    scale = 512 / logo.SIZE

    def at(point):
        return pixel(image, round(point[0] * scale), round(point[1] * scale))

    points = logo.POINTS
    assert close_to(at(points[2]), logo.PURPLE), "the apex is a purple step"
    assert close_to(at(points[1]), logo.TEAL) and close_to(at(points[3]), logo.TEAL), "the lower nodes are teal steps"
    assert close_to(at(points[0]), logo.LIGHT) and close_to(at(points[4]), logo.LIGHT), "the ends are light ports"
    middle_of_edge = ((points[0][0] + points[1][0]) / 2, (points[0][1] + points[1][1]) / 2)
    assert at(middle_of_edge).red() > 180 and at(middle_of_edge).green() < 140, "the edges are raspberry"
    assert pixel(image, 0, 0).alpha() == 0, "the corners of the rounded square are transparent"
    assert pixel(image, 256, 8).alpha() == 255 and pixel(image, 256, 8).red() < 80, "the square is dark"
    plain = logo.markImage(512, tile=False)
    assert pixel(plain, 256, 8).alpha() == 0, "without the tile only the W is drawn"
    assert close_to(pixel(plain, round(points[2][0] * scale), round(points[2][1] * scale)), logo.PURPLE)


def test_the_pixmap_is_sharp_on_a_screen_with_a_higher_pixel_ratio(qapp):
    pixmap = logo.markPixmap(26, device_pixel_ratio=2.0)
    assert pixmap.width() == 52 and pixmap.devicePixelRatio() == 2.0 and not pixmap.isNull()


def test_the_files_of_the_logo_are_the_ones_that_the_code_describes(qapp):
    """Forgetting to run resources/logo/make_logo.py after changing cwled/logo.py is caught here."""
    assert (LOGO_FILES / 'cwled-mark.svg').read_text(encoding='utf-8') == logo.markSvg(True) + '\n'
    assert (LOGO_FILES / 'cwled-mark-plain.svg').read_text(encoding='utf-8') == logo.markSvg(False) + '\n'
    for name in ('cwled-logo-dark.svg', 'cwled-logo-light.svg'):
        text = (LOGO_FILES / name).read_text(encoding='utf-8')
        ET.fromstring(text)
        assert QSvgRenderer(text.encode()).isValid() and '<text' not in text, "the name is drawn as outlines"
    assert 'fill="#f4f5f7"' in (LOGO_FILES / 'cwled-logo-dark.svg').read_text() and \
        'fill="#14161a"' in (LOGO_FILES / 'cwled-logo-light.svg').read_text()
    icon = QImage(str(REPO / 'resources' / 'icons' / 'cwled.png'))
    assert (icon.width(), icon.height()) == (1024, 1024) and icon.pixelColor(0, 0).alpha() == 0
    expected = logo.markImage(1024).convertToFormat(QImage.Format.Format_ARGB32)
    icon = icon.convertToFormat(QImage.Format.Format_ARGB32)
    for x in range(0, 1024, 37):
        for y in range(0, 1024, 41):
            a, b = icon.pixelColor(x, y), expected.pixelColor(x, y)
            assert max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()),
                       abs(a.alpha() - b.alpha())) <= 3, f"the icon of the application is not the mark at {x},{y}"
    header = (REPO / 'resources' / 'icons' / 'cwled.icns').read_bytes()[:8]
    assert header[:4] == b'icns' and struct.unpack('>I', header[4:])[0] == (REPO / 'resources' / 'icons' / 'cwled.icns').stat().st_size


def test_the_side_panel_shows_the_mark_before_the_name(window):
    title_bar = window.sidebar.findChild(object, 'titleBar')
    labels = title_bar.findChildren(QLabel)
    assert not labels[0].pixmap().isNull(), "the first label of the title bar is the mark"
    assert labels[1].objectName() == 'appTitle'


# ------------------------------------------------------------------------------------------------ the window
@pytest.fixture
def user_config(tmp_path, monkeypatch):
    """A folder for the configuration of the user; ``write(text)`` puts a cwled.yaml in it."""
    import platformdirs
    monkeypatch.setattr(platformdirs, 'user_config_path', lambda *args, **kwargs: tmp_path)

    def write(text):
        (tmp_path / 'cwled.yaml').write_text(text)
    return write


def test_when_the_logo_shows(user_config):
    assert SplashScreen.wanted([], {}), "no configuration yet: it shows"
    for off in ('--no-splash', '--version', '-h', '--help'):
        assert not SplashScreen.wanted(['somefile.cwl', off], {}), off
    assert not SplashScreen.wanted([], {'CWLED_NO_SPLASH': '1'})
    assert not SplashScreen.wanted([], {'QT_QPA_PLATFORM': 'offscreen'}), "the tests start without it"
    assert SplashScreen.wanted([], {'QT_QPA_PLATFORM': 'cocoa'})
    user_config("title: Input\nshow_splash: true\n")
    assert SplashScreen.wanted([], {})
    for false in ('false', 'False', 'no', 'off', '0'):
        user_config(f"title: Input\nshow_splash: {false}   # not today\nworkspace: null\n")
        assert not SplashScreen.wanted([], {}), false
    user_config("title: Input\n# show_splash: false\n")
    assert SplashScreen.wanted([], {}), "a comment is not the setting"
    assert SplashScreen.wanted([], {}, check_config=False)


def test_the_window_shows_what_is_done_and_how_far(qapp):
    splash = SplashScreen.LaunchSplash('1.2-3')
    try:
        splash.show()
        splash.setProgress("Loading the configuration", 0.5)
        assert (splash.message, splash.fraction) == ("Loading the configuration", 0.5)
        image = splash.grab().toImage()
        track = SplashScreen._trackRect(SplashScreen.SIZE)
        y = round(track.center().y())
        left, right = round(track.left() + 10), round(track.right() - 10)
        assert close_to(pixel(image, left, y), logo.EDGE_START, 70), "the filled half of the bar is raspberry"
        assert close_to(pixel(image, right, y), SplashScreen.TRACK, 20), "the rest is the track"
        text_row = round(track.bottom() + 20)
        row = [pixel(image, x, text_row) for x in range(150, 410)]
        assert any(colour.lightness() > 100 for colour in row), "the message is written under the bar"
        splash.setProgress("Ready", 1.0)
        assert close_to(pixel(splash.grab().toImage(), right, y), logo.EDGE_END, 70), "the bar is full"
        assert pixel(image, 280, 60).lightness() < 60 and pixel(image, 280, 60).alpha() == 255, "a dark card"
    finally:
        splash.close()


def test_the_window_is_not_started_by_the_tests_and_its_calls_do_nothing_then(qapp):
    assert SplashScreen.start() is None and SplashScreen.current() is None
    SplashScreen.progress("nothing is shown", 0.3)
    SplashScreen.finish(object())            # without a window of the logo there is nothing to close


def test_finish_closes_the_window_and_forgets_it(qapp, monkeypatch):
    monkeypatch.setattr(SplashScreen, 'MIN_SECONDS', 0)
    splash = SplashScreen.LaunchSplash('')
    splash.show()
    SplashScreen._splash = splash
    SplashScreen.finish(wait=False)
    pump(2)
    assert SplashScreen.current() is None
    assert sip.isdeleted(splash) or not splash.isVisible()


def test_the_option_that_turns_the_logo_off_exists(monkeypatch):
    import main
    monkeypatch.setattr('sys.argv', ['cwled', '--no-splash'])
    assert main.parseArgs().no_splash is True
    monkeypatch.setattr('sys.argv', ['cwled'])
    assert main.parseArgs().no_splash is False


def test_the_configuration_dialog_has_the_setting(window, cwled_config):
    from ConfigDialog import ConfigDialog
    assert cwled_config.get('show_splash') is True, "on by default"
    dialog = ConfigDialog(window)
    assert dialog.show_splash_check.isChecked()
    cwled_config['show_splash'] = False
    assert not ConfigDialog(window).show_splash_check.isChecked()


def test_the_logo_shows_first_reports_the_steps_and_goes_when_the_window_is_there():
    import json
    import subprocess
    import sys
    from conftest import FIXTURES
    probe = Path(__file__).resolve().parent / 'run_launch_probe.py'
    process = subprocess.run([sys.executable, str(probe), '--workspace', str(FIXTURES)], capture_output=True, text=True,
                             timeout=180, cwd=str(FIXTURES.parent))
    lines = [line for line in process.stdout.splitlines() if line.startswith('RESULT ')]
    assert lines, f"the application did not start:\n{process.stdout[-1500:]}\n{process.stderr[-1500:]}"
    result = json.loads(lines[-1][len('RESULT '):])
    messages = [event[0] for event in result['events']]
    assert messages[:2] == ['Starting CWLed', 'started'] and result['events'][1][1] is True, \
        "the logo window was there (and told so) before main was imported"
    steps = messages[2:]
    assert steps == ['Loading the configuration', 'Applying the theme', 'Preparing the workspace',
                     'Checking the CWL tools', 'Opening the window', 'Ready'], steps
    fractions = [event[1] for event in result['events'][2:]]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0, "the bar only goes forward, to the end"
    assert result['splash_left'] is False, "the logo window is closed once the main window is there"
    assert result['windows'] == ['MainWindow']
