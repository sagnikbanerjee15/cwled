#!/usr/bin/env python3
"""
Makes the files of the logo of CWLed from its description in ``cwled/logo.py``:

    uv run python resources/logo/make_logo.py

writes into ``resources/logo``:

    cwled-mark.svg         the mark on its rounded square (the icon of the application)
    cwled-mark-plain.svg   the mark alone, for a background of your own
    cwled-logo-dark.svg    mark and name, the name in white, for dark backgrounds
    cwled-logo-light.svg   mark and name, the name dark, for light backgrounds
    cwled-mark-1024.png    the mark on its square, as an image

and also ``docs/splash.png`` (the window that shows while the application starts, for the User Guide) and the
icon of the application, ``resources/icons/cwled.png`` and ``cwled.icns``. The names are drawn with the Montserrat
fonts of ``resources/fonts`` and written as outlines, so the SVG files need no font. Run it again after changing
``cwled/logo.py``.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'cwled'))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPainterPath
from PyQt6.QtWidgets import QApplication

import logo
import SplashScreen

OUT = ROOT / 'resources' / 'logo'
ICONS = ROOT / 'resources' / 'icons'
DARK_TEXT = '#14161a'


def outline(path: QPainterPath) -> str:
    """The outline of a painter path as the data of an SVG path."""
    commands, index = [], 0
    count = path.elementCount()
    open_subpath = False
    while index < count:
        element = path.elementAt(index)
        if element.type == QPainterPath.ElementType.MoveToElement:
            if open_subpath:
                commands.append('Z')
            commands.append(f'M {element.x:.2f} {element.y:.2f}')
            open_subpath = True
        elif element.type == QPainterPath.ElementType.LineToElement:
            commands.append(f'L {element.x:.2f} {element.y:.2f}')
        elif element.type == QPainterPath.ElementType.CurveToElement:
            c1, c2 = path.elementAt(index + 1), path.elementAt(index + 2)
            commands.append(f'C {element.x:.2f} {element.y:.2f} {c1.x:.2f} {c1.y:.2f} {c2.x:.2f} {c2.y:.2f}')
            index += 2
        index += 1
    if open_subpath:
        commands.append('Z')
    return ' '.join(commands)


def nameOutline(size: float):
    """(path data, width) of "CWLed": CWL regular, ed light, at the given pixel size, with its top at y = 0."""
    regular = QFont(SplashScreen.FAMILY)
    regular.setPixelSize(round(size))
    regular.setWeight(QFont.Weight.Normal)
    regular.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.028)
    light = QFont(regular)
    light.setWeight(QFont.Weight.Light)
    from PyQt6.QtGui import QFontMetricsF
    ascent = QFontMetricsF(regular).ascent()
    path = QPainterPath()
    path.addText(0, ascent, regular, 'CWL')
    advance = QFontMetricsF(regular).horizontalAdvance('CWL')
    path.addText(advance, ascent, light, 'ed')
    width = advance + QFontMetricsF(light).horizontalAdvance('ed')
    return outline(path), width


def wordmarkSvg(text_colour: str) -> str:
    """The mark on its square, with the name to the right of it."""
    mark = logo.markSvg(tile=True)
    inner = mark[mark.index('>') + 1:mark.rindex('</svg>')]
    size = 118
    path, width = nameOutline(size)
    gap = 44
    total = logo.SIZE + gap + width + 12
    top = (logo.SIZE - size * 0.73) / 2 - size * 0.04                  # the capitals centred on the mark
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total:.0f} {logo.SIZE}" width="{total:.0f}" '
            f'height="{logo.SIZE}">{inner}'
            f'<g transform="translate({logo.SIZE + gap} {top:.1f})"><path d="{path}" fill="{text_colour}" '
            f'fill-rule="evenodd"/></g></svg>')


def writeIcns(target: Path):
    """
    cwled.icns, the icon of the macOS application: a header and one PNG per size (written here, so that it needs
    no macOS tool). The type codes are those of the icns format: icp4-icp6, ic07-ic10 and ic11-ic14 (the @2x sizes).
    """
    import struct
    sizes = {'icp4': 16, 'icp5': 32, 'icp6': 64, 'ic07': 128, 'ic08': 256, 'ic09': 512, 'ic10': 1024,
             'ic11': 32, 'ic12': 64, 'ic13': 256, 'ic14': 512}
    chunks = []
    for code, size in sizes.items():
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        logo.markImage(size).save(buffer, 'PNG')
        png = bytes(buffer.data())
        chunks.append(code.encode('ascii') + struct.pack('>I', len(png) + 8) + png)
    body = b''.join(chunks)
    target.write_bytes(b'icns' + struct.pack('>I', len(body) + 8) + body)
    print(f"wrote {target.relative_to(ROOT)} ({len(sizes)} sizes)")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    SplashScreen.loadFonts()
    OUT.mkdir(exist_ok=True)
    (OUT / 'cwled-mark.svg').write_text(logo.markSvg(tile=True) + '\n', encoding='utf-8')
    (OUT / 'cwled-mark-plain.svg').write_text(logo.markSvg(tile=False) + '\n', encoding='utf-8')
    (OUT / 'cwled-logo-dark.svg').write_text(wordmarkSvg('#f4f5f7') + '\n', encoding='utf-8')
    (OUT / 'cwled-logo-light.svg').write_text(wordmarkSvg(DARK_TEXT) + '\n', encoding='utf-8')
    logo.markImage(1024).save(str(OUT / 'cwled-mark-1024.png'))
    # the window of the start, as it looks half way
    splash = SplashScreen.LaunchSplash(SplashScreen._version())
    splash.show()
    app.processEvents()
    splash.setProgress("Loading the configuration", 0.55)
    splash.grab().save(str(ROOT / 'docs' / 'splash.png'))
    splash.close()
    # the icon of the application
    logo.markImage(1024).save(str(ICONS / 'cwled.png'))
    writeIcns(ICONS / 'cwled.icns')
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir() if p.name != 'make_logo.py')), "and docs/splash.png")


if __name__ == '__main__':
    main()
