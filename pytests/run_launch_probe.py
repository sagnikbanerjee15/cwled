"""
Starts the application the way ``cwled.py`` does, with the logo window forced on (the tests run on the offscreen platform,
where it is off), and prints what happened as a JSON line: the order of the things the logo window was told, whether it was
gone at the end and which windows are on the screen. Started by pytests/test_logo.py (``main()`` creates the application
itself, so it cannot run in the process of the tests).
"""
import json
import sys

import conftest  # noqa: F401  (redirects the user's directories, polls files, offscreen)
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import SplashScreen

SplashScreen.wanted = lambda *args, **kwargs: True
SplashScreen.MIN_SECONDS = 0.2
events = []
original = SplashScreen.LaunchSplash.setProgress


def spy(self, message, fraction=None):
    events.append([message, fraction])
    return original(self, message, fraction)


SplashScreen.LaunchSplash.setProgress = spy
started = SplashScreen.start()                  # before main is imported, as in cwled.py
events.append(['started', started is not None])
import main as cwled_main  # noqa: E402


def inspect(app):
    for _ in range(10):
        app.processEvents()
        QTest.qWait(10)
    print('RESULT ' + json.dumps({
        'events': events,
        'splash_left': SplashScreen.current() is not None,
        'windows': sorted({type(w).__name__ for w in app.topLevelWidgets() if w.isVisible()}),
    }))
    return 0


QApplication.exec = inspect
sys.argv = ['cwled'] + sys.argv[1:]
cwled_main.main()
