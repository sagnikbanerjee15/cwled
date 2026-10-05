"""
Fixtures for the GUI tests.

The application is run on Qt's ``offscreen`` platform, so no display is needed,
and in isolation: the user's configuration, logs and caches are never read or
written (they are redirected to a temporary directory), the file watcher polls
(the operating system's may not be available, e.g. in a sandbox) and the dialog
that shows logged errors is removed, so that an error fails a test instead of
waiting for someone to close it.
"""
import builtins
import logging
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / 'tests'              # the CWL documents the tests open (tests/ holds no test code)
sys.path.insert(0, str(REPO / 'cwled'))   # the modules import each other as top level names

import platformdirs  # noqa: E402  (must be patched before the application modules are imported)

_USER_DIRS = Path(tempfile.mkdtemp(prefix='cwled-tests-'))
for _name in ('logs', 'cache', 'config'):
    (_USER_DIRS / _name).mkdir()
platformdirs.user_log_path = lambda *args, **kwargs: _USER_DIRS / 'logs'
platformdirs.user_cache_path = lambda *args, **kwargs: _USER_DIRS / 'cache'
platformdirs.user_config_path = lambda *args, **kwargs: _USER_DIRS / 'config'

import watchdog.observers  # noqa: E402
import watchdog.observers.polling  # noqa: E402

watchdog.observers.Observer = watchdog.observers.polling.PollingObserver

import pytest  # noqa: E402


@pytest.fixture(scope='session')
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


@pytest.fixture
def cwled_config(qapp, tmp_path, monkeypatch):
    """A fresh configuration (never saved to the user's), with the theme applied."""
    import configuration
    import data
    import theme
    from helperFunctions import getResourcePath

    config_dir = tmp_path / 'user-config'
    config_dir.mkdir()
    monkeypatch.setattr(configuration, 'user_config_path', lambda *args, **kwargs: config_dir)
    builtins.labelWidth = 100
    data.script_directory = REPO / 'cwled'
    data.config_directory = getResourcePath() / 'config'
    manager = configuration.Configuration(configuration_directory=data.config_directory)
    manager.loadConfiguration('cwled.yaml')
    data.configuration = manager.getConfiguration()
    data.configuration_manager = None          # nothing is written; tests that need it set a stand-in
    data.datatypes = data.configuration.get('data_types')
    if not getattr(qapp, '_cwled_themed', False):
        font = data.configuration['main_window']
        qapp.setFont(theme.uiFont(font.get('font_family'), int(font.get('font_size'))))
        theme.applyTheme(qapp)
        qapp._cwled_themed = True
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).setLevel(logging.WARNING)
    return data.configuration


@pytest.fixture
def make_window(cwled_config, qapp):
    """Factory of main windows, on the workspace folder given (by default the test documents)."""
    import workspaceFolders
    from MainWindow import MainWindow
    windows = []

    def factory(workspace=FIXTURES):
        workspaceFolders.initialise(workspace)
        window = MainWindow()
        # an error that is logged must not open a modal dialog and wait for it
        root = logging.getLogger()
        for handler in list(root.handlers):
            if type(handler).__name__ == 'ErrorDialogHandler':
                root.removeHandler(handler)
        from PyQt6.QtGui import QCursor
        QCursor.setPos(0, 0)         # not over a workflow canvas (see pytests/qt_helpers.park_cursor)
        window.show()
        qapp.processEvents()
        windows.append(window)
        return window

    yield factory
    # A test may leave a document with unsaved changes: closing it must not open the "Save changes?"
    # dialog and wait for someone to answer it (which would hang the tests).
    from PyQt6.QtWidgets import QMessageBox
    from ChildWindow import ChildWindow
    answer = pytest.MonkeyPatch()
    answer.setattr(ChildWindow, 'questionCentered', lambda *args, **kwargs: QMessageBox.StandardButton.No)
    try:
        for window in windows:
            try:
                window.close()
            except Exception:       # a window that is already gone
                pass
        qapp.processEvents()
    finally:
        answer.undo()


@pytest.fixture
def window(make_window):
    return make_window()
