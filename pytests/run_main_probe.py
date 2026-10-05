"""
Runs ``main.main()`` with the arguments it is given, without the event loop, and prints what the
application shows as a JSON line. It is started by pytests/test_command_line.py (``main()`` creates
the application itself, so it cannot run in the process of the tests).
"""
import json
import sys

import conftest  # noqa: F401  (redirects the user's directories, polls files, offscreen)
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import main as cwled_main


def inspect(app):
    for _ in range(30):
        app.processEvents()
        QTest.qWait(10)
    window = next(w for w in app.topLevelWidgets() if type(w).__name__ == 'MainWindow')
    document = window.active_window
    result = {
        'tabs': [window.tabs.tabText(i) for i in range(window.tabs.count())],
        'id': str(document.cwl_tool.id) if document is not None else None,
        'class': document.cwl_tool.class_ if document is not None else None,
        'changed': bool(document.hasChanged) if document is not None else None,
        'title': document.windowTitle() if document is not None else None,
        'workspace': window.workspace.folders(),
    }
    print('RESULT ' + json.dumps(result))
    return 0


QApplication.exec = inspect
sys.argv = ['cwled', '--no-splash'] + sys.argv[1:]
cwled_main.main()
