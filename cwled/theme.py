"""
Rabix Composer look and feel for CWLed.

Colours, typography and widget styling follow the Rabix Composer design
(https://github.com/rabix/composer, ``src/assets/sass/modern/_variables.scss``),
the Ace "idle_fingers" theme used by its code editor and the "rabix-dark"
theme of cwl-svg used by its workflow graph.

Everything that defines the look of the application lives here:
  - the colour palette (module level constants),
  - ``applyTheme()`` which installs the fonts, palette and style sheet,
  - ``icon()`` which renders Font Awesome glyphs (the icon set used by Composer),
  - small helpers to build Composer-style UI elements (titles, form sections).
"""
import sys
from pathlib import Path
from typing import Callable, Optional

from platformdirs import user_cache_path
from PyQt6 import sip
from PyQt6.QtCore import (QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QIconEngine,
                         QPainter, QPalette, QPixmap)
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from helperFunctions import getResourcePath

# ---------------------------------------------------------------------------
# Palette (Composer: modern/_variables.scss)
# ---------------------------------------------------------------------------
BLACK = "#232323"
DARK_GRAY = "#303030"
GRAY = "#3c3c3c"
LIGHT_GRAY = "#999999"
SMOKE = "#eeeeee"
WHITE = "#ffffff"
BLUE = "#337cb9"
SKY = "#6aaaf0"
ORANGE = "#dc8400"
CARROT = "#e29834"
RED = "#dd4a38"
PURPLE = "#a184dc"
GREEN = "#7ac24d"
SUCCESS = "#5ca711"

BODY_BG = DARK_GRAY            # $body-bg
PANEL_BG = GRAY                # $panel-bg / $sidebar-panel-bg
TITLE_BAR_BG = BLACK           # $toolbar-header-bg
INPUT_BG = "#333333"           # $input-bg
INPUT_BORDER = BLACK           # $input-border-color
INPUT_BG_DISABLED = GRAY       # $input-bg-disabled
STATUS_BAR_BG = "#333333"      # $layout-section-background
TERMINAL_BG = "#1f1f1f"        # $layout-section-terminal-background
SELECTED_BG = "#455c7d"        # $editor-panel-selected-background
HOVER_BORDER = "#6d6d6d"       # control-button hover border
BTN_PRIMARY_BORDER = "#296394"
TEXT = SMOKE                   # $text-color
TEXT_MUTED = LIGHT_GRAY        # $text-muted
TEXT_DISABLED = "#777777"

# Command line preview (Composer: command-line-preview.component.scss)
CODE_BASE_CMD = PURPLE
CODE_INPUTS = GREEN
CODE_ARGS = "#fda365"
CODE_STREAM = "#dddddd"
CODE_WARNING = ORANGE
CODE_ERROR = RED

# Code editor colours (Ace "idle_fingers", Composer's code editor theme)
EDITOR = {
    'background': "#323232",
    'foreground': "#ffffff",
    'gutter_background': "#3b3b3b",
    'gutter_foreground': "#999999",
    'caret': "#91ff00",
    'caret_line': "#353637",
    'selection': "#5a647e",
    'keyword': "#cc7833",
    'constant': "#6c99bb",
    'string': "#a5c261",
    'regexp': "#cccc33",
    'comment': "#bc9458",
    'tag': "#ffe5bb",
    'entity': "#ffc66d",
    'function': "#b83426",
    'invalid': "#ff0000",
    'fold': "#cc7833",
}

# Workflow graph colours (cwl-svg "rabix-dark" theme), RGB(A) tuples
GRAPH = {
    'background': (48, 48, 48),
    'grid': (58, 58, 58),
    'edge': (154, 154, 154, 255),
    'step': (17, 167, 167),
    'step_conditional': (161, 132, 220),
    'io': (195, 195, 195),
    'io_optional': (120, 120, 120),
    'port': (195, 195, 195),
    'port_hover': (255, 255, 255),
    'primary': (17, 167, 167),          # $color-primary: selection, hovered edges
    'label': (255, 255, 255),
    # selection fading (cwl-svg selection plugin, dark theme)
    'faded': (68, 67, 67),
    'faded_step': (33, 107, 107),
    'faded_io': (131, 131, 131),
    'faded_label': (126, 125, 125),
}

TITLE_FONT_FAMILY = "Montserrat"
ICON_FONT_FAMILY = "FontAwesome"
ACTION_BAR_HEIGHT = 36          # $action-bar-height / $layout-title-bar-height
STATUS_BAR_HEIGHT = 28          # $layout-stripe-width

# ---------------------------------------------------------------------------
# Font Awesome 4.7 (the icon font bundled with Composer)
# ---------------------------------------------------------------------------
FA = {
    'angle-down': '\uf107', 'angle-right': '\uf105',
    'archive': '\uf187', 'arrow-down': '\uf063', 'arrow-up': '\uf062',
    'bolt': '\uf0e7', 'book': '\uf02d', 'caret-down': '\uf0d7',
    'caret-right': '\uf0da', 'caret-up': '\uf0d8', 'check': '\uf00c',
    'check-circle-o': '\uf05d', 'chevron-down': '\uf078', 'clock-o': '\uf017',
    'cloud-download': '\uf0ed', 'cloud-upload': '\uf0ee', 'code': '\uf121',
    'code-fork': '\uf126', 'cog': '\uf013', 'compress': '\uf066', 'ellipsis-h': '\uf141',
    'eye': '\uf06e', 'file-code-o': '\uf1c9', 'file-image-o': '\uf1c5',
    'file-o': '\uf016', 'files-o': '\uf0c5',
    'floppy-o': '\uf0c7', 'folder': '\uf07b', 'folder-open': '\uf07c',
    'history': '\uf1da', 'info-circle': '\uf05a', 'magic': '\uf0d0',
    'minus': '\uf068', 'paint-brush': '\uf1fc', 'pencil': '\uf040', 'plus': '\uf067',
    'question-circle': '\uf059', 'refresh': '\uf021', 'search': '\uf002',
    'share-alt': '\uf1e0', 'sign-in': '\uf090', 'sign-out': '\uf08b',
    'sort': '\uf0dc', 'sort-alpha-asc': '\uf15d', 'terminal': '\uf120',
    'times': '\uf00d', 'times-circle': '\uf057', 'trash': '\uf1f8',
    'warning': '\uf071',
    'columns': '\uf0db', 'crosshairs': '\uf05b', 'eye-slash': '\uf070',
}

# Glyphs mirrored horizontally, as Composer does for its workflow icon
_MIRRORED = {'share-alt'}

# Configuration icon keys (resources/config/cwled.yaml) -> (glyph, colour)
# A colour of None means "use the default control colour".
ICON_KEYS = {
    'programming': ('code', None),
    'remove': ('trash', None),
    'add': ('plus', SKY),
    'edit': ('pencil', None),
    'info': ('info-circle', SKY),
    'ai': ('magic', None),
    'workflow': ('share-alt', CARROT),
    'tool': ('terminal', PURPLE),
    'expressiontool': ('code', SKY),
    'uparrow': ('arrow-up', None),
    'downarrow': ('arrow-down', None),
    'save': ('floppy-o', None),
    'repackage': ('archive', None),
    'reload': ('refresh', None),
    'gitcommit': ('code-fork', None),
    'gitpush': ('cloud-upload', None),
    'gitpull': ('cloud-download', None),
    'sort': ('sort', None),
    'sync': ('refresh', None),
    'view': ('eye', None),
}


class _GlyphIconEngine(QIconEngine):
    """Icon engine painting a single Font Awesome glyph at any size."""

    def __init__(self, glyph: str, color: str, active_color: str,
                 disabled_color: str, mirrored: bool = False, scale: float = 0.86):
        super().__init__()
        self._glyph = glyph
        self._colors = {
            QIcon.Mode.Normal: color,
            QIcon.Mode.Active: active_color,
            QIcon.Mode.Selected: active_color,
            QIcon.Mode.Disabled: disabled_color,
        }
        self._mirrored = mirrored
        self._scale = scale

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(ICON_FONT_FAMILY)
        font.setPixelSize(max(1, round(min(rect.width(), rect.height()) * self._scale)))
        painter.setFont(font)
        painter.setPen(QColor(self._colors.get(mode, self._colors[QIcon.Mode.Normal])))
        if self._mirrored:
            painter.translate(2 * rect.x() + rect.width(), 0)
            painter.scale(-1, 1)
        painter.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, self._glyph)
        painter.restore()

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        scale = max(1.0, scale)
        pixmap = QPixmap(QSize(round(size.width() * scale), round(size.height() * scale)))
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(scale)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(QPoint(0, 0), size), mode, state)
        painter.end()
        return pixmap

    def clone(self) -> QIconEngine:
        return _GlyphIconEngine(self._glyph, self._colors[QIcon.Mode.Normal],
                                self._colors[QIcon.Mode.Active],
                                self._colors[QIcon.Mode.Disabled],
                                self._mirrored, self._scale)


def icon(name: str, color: Optional[str] = None, active_color: Optional[str] = None,
         disabled_color: str = "#5f5f5f") -> QIcon:
    """
    Return a Composer-style icon.

    Args:
        name: a configuration icon key (e.g. 'save', 'tool') or a Font Awesome
              glyph name (e.g. 'folder', 'search').
        color: colour of the glyph; defaults to the key's colour or the muted
               control colour.
        active_color: colour on hover/selection; defaults to ``color`` for
              coloured icons and to the text colour otherwise.
        disabled_color: colour when the control is disabled.
    """
    key_color = None
    glyph_name = name
    if name in ICON_KEYS:
        glyph_name, key_color = ICON_KEYS[name]
    glyph = FA.get(glyph_name)
    if glyph is None:
        # Not a themed icon; fall back to the configured image, if any
        try:
            import data
            path = data.configuration.get('icons', {}).get(name)
        except Exception:
            path = None
        return QIcon(path) if path else QIcon()
    color = color or key_color or TEXT_MUTED
    if active_color is None:
        active_color = color if (key_color or color != TEXT_MUTED) else TEXT
    return QIcon(_GlyphIconEngine(glyph, color, active_color, disabled_color,
                                  mirrored=glyph_name in _MIRRORED))


def _cacheDir() -> Path:
    directory = user_cache_path(appname='cwled') / 'theme'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def iconFile(name: str, color: Optional[str] = None, size: int = 64) -> str:
    """Render an icon to a PNG file (for APIs that need a path) and return its path."""
    glyph_name, key_color = ICON_KEYS.get(name, (name, None))
    color = color or key_color or TEXT_MUTED
    path = _cacheDir() / f"{glyph_name}-{color.lstrip('#')}-{size}.png"
    if not path.exists():
        icon(glyph_name, color=color, active_color=color).pixmap(QSize(size, size)).save(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
# Composer's body font is Bootstrap 4's system font stack at 13px:
# -apple-system (San Francisco), "Segoe UI", Roboto, "Helvetica Neue", Arial.
UI_FONT_FALLBACKS = ["Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"]
FONT_SIZE = 13
# 'Arial' is the font shipped in the default configuration; any other
# configured family is an explicit user choice and takes precedence.
_DEFAULT_CONFIGURED_FAMILY = "Arial"


def loadFonts():
    """Register the bundled Montserrat (titles) and Font Awesome (icons) fonts."""
    fonts_dir = getResourcePath() / 'fonts'
    for file_name in ('Montserrat-Regular.ttf', 'Montserrat-Light.ttf', 'fontawesome-webfont.ttf'):
        QFontDatabase.addApplicationFont(str(fonts_dir / file_name))


def uiFont(configured_family: Optional[str] = None, point_size: float = FONT_SIZE) -> QFont:
    """Composer body font: the system UI font (San Francisco on macOS)."""
    families = []
    if configured_family and configured_family != _DEFAULT_CONFIGURED_FAMILY:
        families.append(configured_family)
    if sys.platform == 'darwin':
        families.append(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family())
    font = QFont()
    font.setFamilies(families + UI_FONT_FALLBACKS)
    font.setPointSizeF(point_size)
    return font


def titleFont(point_size: Optional[float] = None, light: bool = False) -> QFont:
    """
    Composer ``.text-title``: Montserrat, upper case, letter-spacing .5px,
    weight 600 (rendered as synthetic bold, Composer only ships the regular face).
    """
    font = QFont(TITLE_FONT_FAMILY)
    font.setWeight(QFont.Weight.Light if light else QFont.Weight.Bold)
    font.setPointSizeF(point_size or QApplication.font().pointSizeF())
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
    return font


def styleTitle(label: QLabel, point_size: Optional[float] = None) -> QLabel:
    """Turn a label into a Composer section title."""
    label.setFont(titleFont(point_size))
    label.setProperty('title', True)
    return label


def iconFont(pixel_size: int = FONT_SIZE) -> QFont:
    font = QFont(ICON_FONT_FAMILY)
    font.setPixelSize(pixel_size)
    return font


def monospaceFont(point_size: Optional[float] = None) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if point_size:
        font.setPointSizeF(point_size)
    return font


# CSS "monospace" at Composer's 13px base size, as Composer's Chromium draws
# it: Courier on macOS, Courier New on Windows, DejaVu Sans Mono on Linux.
MONOSPACE_FAMILIES = ["Courier", "Courier New", "DejaVu Sans Mono", "Liberation Mono"]
# configuration values meaning "Composer's font" (Monaco was the old default)
_DEFAULT_TERMINAL_FAMILIES = {None, '', 'monospace', 'Monaco'}


def _pixelFont(families, pixel_size: int) -> QFont:
    """A font as tall as Composer's CSS pixel size, given in points because
    QScintilla ignores pixel-sized fonts (1pt = 1px on macOS)."""
    font = QFont()
    # QScintilla only uses the first family name: start with an installed one
    installed = set(QFontDatabase.families())
    font.setFamilies([family for family in families if family in installed] or families)
    font.setStyleHint(QFont.StyleHint.Monospace)
    screen = QApplication.primaryScreen()
    dpi = screen.logicalDotsPerInchY() if screen is not None else 72.0
    font.setPointSizeF(pixel_size * 72.0 / dpi)
    return font


def cssMonospaceFont() -> QFont:
    """Composer text styled ``font-family: monospace`` (13px)."""
    return _pixelFont(MONOSPACE_FAMILIES, 13)


def terminalFont(configured_family: Optional[str] = None,
                 configured_size: Optional[float] = None) -> QFont:
    """
    Font of the command line preview: Composer's ``monospace`` unless the
    configuration names another font (``command_line_window.font_family``).
    """
    if configured_family in _DEFAULT_TERMINAL_FAMILIES:
        return cssMonospaceFont()
    font = QFont(configured_family)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(float(configured_size or FONT_SIZE))
    return font


# ---------------------------------------------------------------------------
# Composer building blocks
# ---------------------------------------------------------------------------
SECTION_PADDING = 12        # .form-section padding
SECTION_SPACING = 18        # gap between form sections
LIST_TEXT_INSET = 13        # .editor-list-item column padding (inside the 1px border)
LIST_ROW_SPACING = 10       # .input-list-items margin-bottom
ROW_ACTION_SPACING = 13     # .remove-icon margin-left (1em)
REMOVE_ICON_WIDTH = 15      # .remove-icon: fa-trash at the 13px body size


_FORM_CONTROL_HEIGHT = None


def formControlHeight() -> int:
    """Height of a themed input field (Composer .form-control)."""
    global _FORM_CONTROL_HEIGHT
    if _FORM_CONTROL_HEIGHT is None:
        _FORM_CONTROL_HEIGHT = QLineEdit().sizeHint().height()
    return _FORM_CONTROL_HEIGHT


class ListRow(QFrame):
    """
    Composer ``.editor-list-item``: a single bar summarising one list entry
    (argument, input, output) in columns. Clicking it opens the entry editor.
    """
    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName('listRow')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(formControlHeight())   # same height as an input field
        layout = QHBoxLayout(self)
        layout.setContentsMargins(LIST_TEXT_INSET, 0, LIST_TEXT_INSET, 0)
        layout.setSpacing(0)

    def addColumn(self, widget: QWidget, stretch: int):
        """Add a display column; widths follow the stretch factors (Bootstrap col-xs-N)."""
        widget.setParent(self)
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if isinstance(widget, QLineEdit):
            widget.setPlaceholderText("")
            widget.setFrame(False)
        widget.show()
        self.layout().addWidget(widget, stretch)

    def addSpacer(self, stretch: int):
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.layout().addWidget(spacer, stretch)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def listRowLayout(widget: QWidget, row: ListRow, remove_button: QWidget) -> QHBoxLayout:
    """Lay out a list entry like Composer: the bar, then the trash icon."""
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(ROW_ACTION_SPACING)
    layout.addWidget(row, 1)
    layout.addWidget(remove_button, 0, Qt.AlignmentFlag.AlignVCenter)
    widget.setLayout(layout)
    return layout


class ListHeader(QWidget):
    """Composer ``.editor-list-title``: column names above the list rows."""

    def __init__(self, columns, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        border = 1
        layout.setContentsMargins(LIST_TEXT_INSET + border, 0,
                                  LIST_TEXT_INSET + border + ROW_ACTION_SPACING + REMOVE_ICON_WIDTH, 0)
        layout.setSpacing(0)
        for title, stretch in columns:
            label = QLabel(title, self)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            layout.addWidget(label, stretch)


class FormSection(QFrame):
    """
    Composer ``ct-form-panel``: a collapsible panel with an upper-case title
    and a caret on the right, optionally a coloured stripe on the left
    (``cli-border``: base command, arguments, inputs), column names above a
    list and a "+ Add ..." link below it.

    Group widgets that carry a ``header`` (HeaderWithAddButton) have their
    title and add button moved into the panel. The panel follows the
    visibility of the wrapped widget, so code that hides/shows it keeps working.
    """

    STRIPE_WIDTH = 6

    def __init__(self, widget: QWidget, title: Optional[str] = None, add_text: Optional[str] = None,
                 stripe: Optional[str] = None, columns=None, collapsed: bool = False,
                 parent: Optional[QWidget] = None, borderless: bool = False,
                 empty_text: Optional[str] = None):
        """
        Args:
            borderless: no panel background or padding (Composer
                ``ct-form-panel.borderless``, used inside the inspector).
            empty_text: when the list is empty, show this text under a
                centered primary "add" button (Composer blank state).
        """
        super().__init__(parent)
        self.setObjectName('formSection')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if borderless:
            self.setProperty('borderless', True)
        self._widget = widget
        self._stripe = QColor(stripe) if stripe else None

        header = getattr(widget, 'header', None)
        if header is not None and hasattr(header, 'addButtonClicked'):
            title = title or header.title()
            header.hide()
        else:
            header = None
        # Composer list spacing inside the wrapped group widget
        widget_layout = QWidget.layout(widget)   # some widgets shadow layout()
        if widget_layout is not None:
            widget_layout.setContentsMargins(0, 0, 0, 0)
        container_layout = getattr(widget, 'container_layout', None)
        if container_layout is not None:
            container_layout.setSpacing(LIST_ROW_SPACING)

        layout = QVBoxLayout(self)
        padding = 0 if borderless else SECTION_PADDING
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self.title_label = styleTitle(QLabel(title or "", self))
        self.title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_label.installEventFilter(self)
        title_row.addWidget(self.title_label, 1)
        self.toggle_button = QToolButton(self)
        self.toggle_button.setObjectName('sectionToggle')
        self.toggle_button.setIconSize(QSize(16, 16))
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(lambda: self.setCollapsed(not self._collapsed))
        title_row.addWidget(self.toggle_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(title_row)

        self.body = QWidget(self)
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)
        self.list_header = ListHeader(columns, self.body) if columns else None
        if self.list_header is not None:
            body_layout.addWidget(self.list_header)
        body_layout.addWidget(widget)
        self.add_link = None
        self.blank_state = None
        if header is not None:
            self.add_link = QPushButton(add_text or "Add", self.body)
            self.add_link.setIcon(icon('plus', color=SKY))
            self.add_link.setIconSize(QSize(14, 14))
            self.add_link.setCursor(Qt.CursorShape.PointingHandCursor)
            setButtonRole(self.add_link, 'link')
            self.add_link.clicked.connect(header.addButtonClicked.emit)
            body_layout.addSpacing(4)
            body_layout.addWidget(self.add_link, 0, Qt.AlignmentFlag.AlignLeft)
            if empty_text:
                # Composer ct-blank-state: centered primary button and a message
                self.blank_state = QWidget(self.body)
                blank_layout = QVBoxLayout(self.blank_state)
                blank_layout.setContentsMargins(0, 0, 0, 0)
                blank_layout.setSpacing(8)
                add_button = QPushButton(add_text or "Add", self.blank_state)
                add_button.setCursor(Qt.CursorShape.PointingHandCursor)
                setButtonRole(add_button, 'primary')
                add_button.clicked.connect(header.addButtonClicked.emit)
                blank_layout.addWidget(add_button, 0, Qt.AlignmentFlag.AlignHCenter)
                message = QLabel(empty_text, self.blank_state)
                message.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                blank_layout.addWidget(message)
                body_layout.addWidget(self.blank_state)
        layout.addWidget(self.body)

        widget.installEventFilter(self)
        self._collapsed = False
        self.setCollapsed(collapsed)
        if widget.isHidden():
            self.hide()
        self._refreshListHeader()

    def setCollapsed(self, collapsed: bool):
        """Fold the panel to its title (Composer: caret-down open, caret-up folded)."""
        self._collapsed = collapsed
        self.body.setVisible(not collapsed)
        self.toggle_button.setIcon(icon('caret-up' if collapsed else 'caret-down',
                                        color=TEXT, active_color=TEXT))
        self.toggle_button.setToolTip("Expand" if collapsed else "Collapse")

    def _hasEntries(self) -> bool:
        if self._widget is None:
            return False
        entries = getattr(self._widget, 'widgets', None)
        if isinstance(entries, list):
            return bool(entries)
        return bool(self._widget.findChildren(ListRow))

    def _refreshListHeader(self):
        # Composer only shows the column names when the list has entries,
        # and a blank state instead of an empty list
        has_entries = self._hasEntries()
        if self.list_header is not None:
            self.list_header.setVisible(has_entries)
        if self.blank_state is not None:
            self.blank_state.setVisible(not has_entries)
            self.add_link.setVisible(has_entries)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        if watched is self._widget:
            if event.type() == QEvent.Type.HideToParent:
                self.hide()
            elif event.type() == QEvent.Type.ShowToParent:
                self.show()
            elif event.type() == QEvent.Type.LayoutRequest:
                self._refreshListHeader()
            elif event.type() == QEvent.Type.ParentChange and not self.isAncestorOf(watched):
                # taken back out by its dialog: let go of it (see _FollowVisibility)
                watched.removeEventFilter(self)
                self._widget = None
        elif watched is self.title_label and event.type() == QEvent.Type.MouseButtonRelease:
            self.setCollapsed(not self._collapsed)
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        self._refreshListHeader()
        super().showEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._stripe is not None:
            painter = QPainter(self)
            painter.fillRect(QRect(0, 0, self.STRIPE_WIDTH, self.height()), self._stripe)
            painter.end()


class _FollowVisibility(QWidget):
    """
    A wrapper built around widgets it borrows (usually from a dialog), shown
    and hidden together with the main one.

    When the owner takes a borrowed widget back out (``setParent(None)``) the
    wrapper lets go of it at once. Otherwise the wrapper would hold the last
    reference to it and Python would delete the widget from inside the
    wrapper's own destructor, while the widget still has the dying wrapper as
    an event filter, and the application would crash.
    """

    def _follow(self, widget: QWidget, *borrowed: Optional[QWidget]):
        self._followed = widget
        self._borrowed = [w for w in (widget, *borrowed) if w is not None]
        for w in self._borrowed:
            w.installEventFilter(self)
        if widget.isHidden():
            self.hide()

    def _release(self, widget: QWidget):
        """Let go of a borrowed widget: no filter, signals or references left."""
        widget.removeEventFilter(self)
        self._borrowed = [w for w in self._borrowed if w is not widget]
        for name, value in list(vars(self).items()):
            if value is widget:
                setattr(self, name, None)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        if watched is getattr(self, '_followed', None):
            if event.type() == QEvent.Type.HideToParent:
                self.hide()
            elif event.type() == QEvent.Type.ShowToParent:
                self.show()
        if event.type() == QEvent.Type.ParentChange and not self.isAncestorOf(watched) \
                and any(w is watched for w in getattr(self, '_borrowed', ())):
            self._release(watched)
        return super().eventFilter(watched, event)


class ToggleRow(_FollowVisibility):
    """
    Composer form-group with a ct-toggle-slider: the label on the left,
    "Yes"/"No" and the switch on the right. Wraps an existing QCheckBox.
    """

    def __init__(self, checkbox, text: Optional[str] = None, on: str = "Yes", off: str = "No",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.checkbox = checkbox
        self._on, self._off = on, off
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label = QLabel(text if text is not None else checkbox.text().rstrip(':'), self)
        self.label.setWordWrap(True)
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.installEventFilter(self)
        self.state_label = QLabel(self)
        checkbox.setText("")
        checkbox.setProperty('toggle', True)
        checkbox.style().unpolish(checkbox)
        checkbox.style().polish(checkbox)
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.state_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        checkbox.toggled.connect(self._updateState)
        self._updateState()
        self._follow(checkbox)

    def _updateState(self, *_):
        if self.checkbox is not None:
            self.state_label.setText(self._on if self.checkbox.isChecked() else self._off)

    def _release(self, widget: QWidget):
        if widget is self.checkbox:
            try:
                widget.toggled.disconnect(self._updateState)
            except TypeError:
                pass
        super()._release(widget)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        if watched is self.label and event.type() == QEvent.Type.MouseButtonRelease \
                and self.checkbox is not None and self.checkbox.isEnabled():
            self.checkbox.toggle()
        return super().eventFilter(watched, event)


class ExpressionInput(_FollowVisibility):
    """
    Composer ct-expression-input: a field with an attached button. A literal
    value is edited in place and the ``</>`` button opens the expression
    editor; an expression ($(...) or ${...}) is shown read-only and dull with
    a bold "E:" prefix, clicking it opens the editor and the button (×)
    clears it.

    ``validator(code, report)`` evaluates an expression and calls
    ``report(error or None)``: an expression that fails shows a red ✖ in
    place of "E:" and the error as a tooltip (Composer ct-validation-preview).
    """

    VALIDATION_DELAY_MS = 400

    def __init__(self, line_edit: QLineEdit, open_editor: Callable[[], None],
                 parent: Optional[QWidget] = None,
                 validator: Optional[Callable[[str, Callable], None]] = None):
        super().__init__(parent)
        self.line_edit = line_edit
        self._open_editor = open_editor
        self._validator = validator
        self._validation = 0            # the latest validation request
        self._error = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(line_edit, 1)
        self.button = QPushButton(self)
        self.button.setFixedSize(QSize(42, formControlHeight()))
        self.button.setIconSize(QSize(14, 14))
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        setButtonRole(self.button, 'addon')
        self.button.clicked.connect(self._onButton)
        layout.addWidget(self.button)
        self.prefix = QLabel("E:", line_edit)
        self.prefix.setObjectName('expressionPrefix')
        self.prefix.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._validation_timer = QTimer(self)
        self._validation_timer.setSingleShot(True)
        self._validation_timer.setInterval(self.VALIDATION_DELAY_MS)
        self._validation_timer.timeout.connect(self._validate)
        line_edit.installEventFilter(self)
        line_edit.textChanged.connect(self.refresh)
        self.refresh()
        self._follow(line_edit)

    @staticmethod
    def isExpression(text: str) -> bool:
        return '$(' in text or '${' in text

    def refresh(self, *_):
        line_edit = self.line_edit
        if line_edit is None:
            return
        expression = self.isExpression(line_edit.text())
        line_edit.setReadOnly(expression)
        line_edit.setProperty('expression', expression)
        line_edit.style().unpolish(line_edit)
        line_edit.style().polish(line_edit)
        line_edit.setCursor(Qt.CursorShape.PointingHandCursor if expression
                            else Qt.CursorShape.IBeamCursor)
        if expression:
            # show the start of long expressions (setText leaves the cursor at the end)
            QTimer.singleShot(0, lambda: sip.isdeleted(line_edit) or line_edit.setCursorPosition(0))
        self.prefix.setVisible(expression)
        self._placePrefix()
        self.button.setIcon(icon('times', color=TEXT, active_color=TEXT) if expression
                            else icon('code', color=TEXT_MUTED, active_color=TEXT))
        self.button.setToolTip("Clear the expression" if expression else "Edit JavaScript expression")
        self._validation += 1           # results of earlier texts no longer apply
        self._showError(None)
        if expression and self._validator is not None:
            self._validation_timer.start()

    def _validate(self):
        if self.line_edit is None or not self.isExpression(self.line_edit.text()):
            return
        request = self._validation
        self._validator(self.line_edit.text(), lambda error: self._onValidated(request, error))

    def _onValidated(self, request: int, error: Optional[str]):
        if not sip.isdeleted(self) and request == self._validation:
            self._showError(error)

    def _showError(self, error: Optional[str]):
        """Composer validation preview: a red ✖ instead of "E:", the error as tooltip."""
        if self.line_edit is None or error == self._error:
            return
        self._error = error
        line_edit = self.line_edit
        line_edit.setProperty('invalid', bool(error))
        line_edit.style().unpolish(line_edit)
        line_edit.style().polish(line_edit)
        line_edit.setToolTip(error or "")
        if error:
            self.prefix.setPixmap(icon('times-circle', color=RED).pixmap(QSize(14, 14)))
        else:
            self.prefix.setText("E:")
        self._placePrefix()

    def _placePrefix(self):
        if self.line_edit is None:
            return
        self.prefix.adjustSize()
        self.prefix.move(9, (self.line_edit.height() - self.prefix.height()) // 2)

    def _onButton(self):
        if self.line_edit is None:
            return
        if self.isExpression(self.line_edit.text()):
            self.line_edit.setText("")
            self.line_edit.editingFinished.emit()
        else:
            self._open_editor()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        if watched is self.line_edit and watched is not None:
            if event.type() == QEvent.Type.Resize:
                self._placePrefix()
            elif event.type() == QEvent.Type.MouseButtonRelease and \
                    self.isExpression(self.line_edit.text()):
                self._open_editor()
        return super().eventFilter(watched, event)

    def _release(self, widget: QWidget):
        if widget is self.line_edit:
            try:
                widget.textChanged.disconnect(self.refresh)
            except TypeError:
                pass
        super()._release(widget)


class FieldGroup(_FollowVisibility):
    """
    Composer form-group: a label above its field. The group is hidden
    whenever the field is hidden. ``addon`` is a button attached to the
    right of the field (Composer expression input).
    """

    def __init__(self, label, field: QWidget, addon: Optional[QWidget] = None,
                 parent: Optional[QWidget] = None,
                 open_editor: Optional[Callable[[], None]] = None,
                 validator: Optional[Callable[[str, Callable], None]] = None):
        """``open_editor`` turns the field into a Composer expression input
        (``validator``: see ExpressionInput)."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        borrowed_label = None if isinstance(label, str) else label
        if isinstance(label, str):
            label = QLabel(label, self)
        self.label = label
        layout.addWidget(label)
        if open_editor is not None:
            self.expression_input = ExpressionInput(field, open_editor, parent=self, validator=validator)
            layout.addWidget(self.expression_input)
        elif addon is None:
            layout.addWidget(field)
        else:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            row.addWidget(field, 1)
            row.addWidget(styleAddon(addon))
            layout.addLayout(row)
        self._follow(field, borrowed_label, addon)


def styleAddon(button: QPushButton) -> QPushButton:
    """Composer ``.input-group`` button: a box attached to the right end of a
    field, e.g. the ``</>`` expression button."""
    button.setFixedSize(QSize(42, formControlHeight()))
    button.setIconSize(QSize(14, 14))
    button.setProperty('iconButton', False)
    setButtonRole(button, 'addon')
    return button


class InputGroup(_FollowVisibility):
    """
    Composer ``.input-group``: ``field`` with ``button`` (usually the ``</>``
    expression button) attached to its right end. Put the group where the
    field would go; it is shown and hidden together with the field.
    """

    def __init__(self, field: QWidget, button: QPushButton, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(field, 1)
        layout.addWidget(styleAddon(button), 0, Qt.AlignmentFlag.AlignTop)
        self._follow(field, button)


def styleCodeEditor(editor, lexer=None):
    """
    Apply Composer's code editor colours (Ace "idle_fingers") to a
    QsciScintilla editor and, if given, to its lexer. Call it again after
    every ``setLexer()`` because a new lexer brings its own colours.
    """
    background = QColor(EDITOR['background'])
    foreground = QColor(EDITOR['foreground'])
    gutter = QColor(EDITOR['gutter_background'])
    editor.setPaper(background)
    editor.setColor(foreground)
    editor.setMarginsBackgroundColor(gutter)
    editor.setMarginsForegroundColor(QColor(EDITOR['gutter_foreground']))
    editor.setFoldMarginColors(gutter, gutter)
    editor.setMarkerBackgroundColor(QColor(EDITOR['gutter_foreground']))
    editor.setMarkerForegroundColor(gutter)
    editor.setCaretForegroundColor(QColor(EDITOR['caret']))
    editor.setCaretLineBackgroundColor(QColor(EDITOR['caret_line']))
    editor.setSelectionBackgroundColor(QColor(EDITOR['selection']))
    editor.setMatchedBraceBackgroundColor(QColor("#4a4a4a"))
    editor.setMatchedBraceForegroundColor(foreground)
    editor.setUnmatchedBraceForegroundColor(QColor(EDITOR['invalid']))
    editor.setIndentationGuidesForegroundColor(QColor("#4a4a4a"))
    editor.setIndentationGuidesBackgroundColor(background)
    if lexer is None:
        return

    is_yaml = lexer.language() == 'YAML'
    lexer.setDefaultPaper(background)
    lexer.setDefaultColor(foreground)
    lexer.setPaper(background, -1)
    for style in range(128):
        description = lexer.description(style).lower()
        if not description:
            continue
        italic = False
        if 'comment' in description:
            color, italic = EDITOR['comment'], True
        elif 'unclosed' in description or 'syntax error' in description:
            color = EDITOR['invalid']
        elif 'string' in description:
            color = EDITOR['string']
        elif 'number' in description:
            color = EDITOR['constant']
        elif 'regular expression' in description:
            color = EDITOR['regexp']
        elif 'reference' in description:
            color = EDITOR['entity']
        elif is_yaml and 'keyword' in description:
            color = EDITOR['constant']     # true / false / null
        elif any(word in description for word in ('keyword', 'delimiter', 'block marker', 'pre-processor')):
            color = EDITOR['keyword']
        elif is_yaml and 'identifier' in description:
            color = EDITOR['tag']          # mapping keys
        else:
            color = EDITOR['foreground']
        lexer.setColor(QColor(color), style)
        if italic:
            font = lexer.font(style)
            font.setItalic(True)
            lexer.setFont(font, style)


def setButtonRole(button: QWidget, role: str) -> QWidget:
    """
    Mark a button as 'primary' (blue), 'link' (text link), 'iconButton'
    (icon with a hover frame) or 'plainIcon' (bare glyph, e.g. the trash icon).
    """
    button.setProperty(role, True)
    button.style().unpolish(button)
    button.style().polish(button)
    return button


# ---------------------------------------------------------------------------
# Application wide theme
# ---------------------------------------------------------------------------
def _palette() -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BODY_BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: INPUT_BG,
        QPalette.ColorRole.AlternateBase: "#383838",
        QPalette.ColorRole.ToolTipBase: BLACK,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_MUTED,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: BODY_BG,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.BrightText: WHITE,
        QPalette.ColorRole.Light: "#4a4a4a",
        QPalette.ColorRole.Midlight: "#424242",
        QPalette.ColorRole.Mid: "#2a2a2a",
        QPalette.ColorRole.Dark: BLACK,
        QPalette.ColorRole.Shadow: "#141414",
        QPalette.ColorRole.Highlight: SELECTED_BG,
        QPalette.ColorRole.HighlightedText: WHITE,
        QPalette.ColorRole.Link: SKY,
        QPalette.ColorRole.LinkVisited: PURPLE,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(disabled, role, QColor(TEXT_DISABLED))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor(INPUT_BG_DISABLED))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor("#3a4558"))
    return palette


def _toggleImage(checked: bool, disabled: bool = False) -> str:
    """Composer ct-toggle-slider (40x20 pill with a 17px knob), saved at 1x and @2x."""
    name = f"toggle-{'on' if checked else 'off'}{'-disabled' if disabled else ''}"
    path = _cacheDir() / f"{name}.png"
    for scale, file_path in ((1, path), (2, _cacheDir() / f"{name}@2x.png")):
        if file_path.exists():
            continue
        pixmap = QPixmap(40 * scale, 20 * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        track = QColor(SKY if checked else INPUT_BG)
        if disabled:
            track = QColor(INPUT_BG_DISABLED)
        painter.setPen(QColor(SKY if checked and not disabled else INPUT_BORDER))
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0.5, 0.5, 39, 19), 9.5, 9.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TEXT if not disabled else TEXT_DISABLED))
        knob_x = 21 if checked else 2
        painter.drawEllipse(QRectF(knob_x, 1.5, 17, 17))
        painter.end()
        pixmap.save(str(file_path))
    return path.as_posix()


def _indicatorImages() -> dict:
    """Render the small images the style sheet needs (arrows, check marks...)."""
    images = {
        'select_arrows': ('sort', TEXT, 16),
        'angle_right': ('angle-right', TEXT, 16),
        'angle_down': ('angle-down', TEXT, 16),
        'select_arrows_disabled': ('sort', "#5f5f5f", 16),
        'caret_down': ('caret-down', TEXT_MUTED, 16),
        'caret_down_disabled': ('caret-down', "#5f5f5f", 16),
        'caret_up': ('caret-up', TEXT_MUTED, 16),
        'caret_right': ('caret-right', TEXT_MUTED, 16),
        'check': ('check', WHITE, 16),
        'minus': ('minus', WHITE, 16),
        'times': ('times', TEXT_MUTED, 16),
        'times_hover': ('times', WHITE, 16),
    }
    paths = {key: Path(iconFile(glyph, color, size * 2)).as_posix()
             for key, (glyph, color, size) in images.items()}
    paths.update(toggle_on=_toggleImage(True), toggle_off=_toggleImage(False),
                 toggle_on_disabled=_toggleImage(True, True),
                 toggle_off_disabled=_toggleImage(False, True))
    return paths


STYLE_SHEET = """
/* ---------- general ---------- */
QToolTip {{
    color: {TEXT}; background-color: {BLACK}; border: 1px solid {BLACK}; padding: 4px 6px;
}}
QDialog {{ background-color: {PANEL_BG}; }}
ChildWindow {{ background-color: {BODY_BG}; }}
QLabel {{ background: transparent; }}
QLabel[muted="true"] {{ color: {TEXT_MUTED}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---------- inputs (.form-control) ---------- */
QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {INPUT_BG}; color: {TEXT};
    border: 1px solid {INPUT_BORDER}; border-radius: 2px;
    selection-background-color: {BLUE}; selection-color: {WHITE};
}}
QLineEdit, QAbstractSpinBox, QComboBox {{ padding: 3px 7px; }}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {SKY}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled,
QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {INPUT_BG_DISABLED}; color: {TEXT_MUTED};
}}
QLineEdit[readOnly="true"] {{ color: {TEXT_MUTED}; }}
QComboBox {{ padding-right: 22px; }}
QComboBox QLineEdit {{ border: none; padding: 0; background: transparent; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 20px; border: none; background: transparent;
}}
QComboBox::down-arrow {{ image: url({select_arrows}); width: 9px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url({select_arrows_disabled}); }}
QComboBox QAbstractItemView {{
    background-color: {INPUT_BG}; color: {TEXT}; border: 1px solid {BLACK};
    selection-background-color: {SELECTED_BG}; selection-color: {WHITE}; outline: 0;
}}
QAbstractSpinBox {{ padding-right: 18px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 16px; border: none; background: transparent;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-arrow {{ image: url({caret_up}); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url({caret_down}); width: 9px; height: 9px; }}

/* ---------- buttons (.btn) ---------- */
QPushButton {{
    background-color: {BODY_BG}; color: {TEXT};
    border: 1px solid {BLACK}; border-radius: 2px; padding: 5px 14px;
}}
QPushButton:hover {{ background-color: #383838; }}
QPushButton:pressed, QPushButton:checked {{ background-color: #262626; }}
QPushButton:disabled {{ color: {TEXT_DISABLED}; background-color: {BODY_BG}; }}
QPushButton:flat {{ background: transparent; border: none; }}
QPushButton[primary="true"],
QDialogButtonBox QPushButton:default, QMessageBox QPushButton:default {{
    background-color: {BLUE}; border-color: {BTN_PRIMARY_BORDER}; color: {WHITE};
}}
QPushButton[primary="true"]:hover,
QDialogButtonBox QPushButton:default:hover, QMessageBox QPushButton:default:hover {{
    background-color: #3a88c9;
}}
QPushButton[primary="true"]:pressed {{ background-color: #2c6ca2; }}
QPushButton[link="true"] {{
    background: transparent; border: none; color: {SKY}; padding: 4px 0; text-align: left;
}}
QPushButton[link="true"]:hover {{ color: #9ac5f5; }}
QPushButton[iconButton="true"] {{
    background: transparent; border: 1px solid transparent; padding: 2px;
}}
QPushButton[iconButton="true"]:hover {{ background-color: {INPUT_BG}; border-color: {HOVER_BORDER}; }}
/* expression input addon button (input-group .btn-icon) */
QPushButton[addon="true"] {{
    background-color: {BODY_BG}; border: 1px solid {INPUT_BORDER}; border-radius: 2px; padding: 0;
}}
QPushButton[addon="true"]:hover {{ border-color: {SKY}; }}
QPushButton[plainIcon="true"], QPushButton[plainIcon="true"]:hover, QPushButton[plainIcon="true"]:pressed {{
    background: transparent; border: none; padding: 0;
}}
/* workflow graph canvas buttons (.svg-btns .btn-group .btn-sm) */
QPushButton[graphControl="only"], QPushButton[graphControl="first"],
QPushButton[graphControl="middle"], QPushButton[graphControl="last"] {{
    padding: 5px 7px; min-width: 11px; icon-size: 11px;
}}
QPushButton[graphControl="first"] {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
QPushButton[graphControl="middle"] {{ border-radius: 0; border-left: none; }}
QPushButton[graphControl="last"] {{ border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: none; }}

/* ---------- control buttons / toolbars (.control-button) ---------- */
QToolButton {{
    background: transparent; color: {TEXT};
    border: 1px solid transparent; border-radius: 2px; padding: 3px;
}}
QToolButton:hover {{ background-color: {INPUT_BG}; border-color: {HOVER_BORDER}; }}
QToolButton:pressed {{ background-color: #343434; }}
QToolButton:checked {{ background-color: {BLACK}; }}
QToolButton:disabled {{ color: {TEXT_DISABLED}; }}
QToolBar {{ background: transparent; border: none; spacing: 2px; padding: 0 4px; }}
QToolBar::separator {{ background-color: {BLACK}; width: 1px; margin: 8px 5px; }}

/* ---------- tabs (ct-tab-selector: text tabs with a blue underline) ---------- */
QTabWidget::pane {{ border: none; border-top: 1px solid {BLACK}; }}
QTabWidget::tab-bar {{ left: 0; }}
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_MUTED};
    border: none; border-bottom: 2px solid transparent;
    padding: 7px 14px 6px 14px; margin: 0;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {SKY}; }}
QTabBar::tab:disabled {{ color: #5f5f5f; }}

/* editor sub tabs (App Info / Visual Editor / Code) on the action bar */
QTabWidget#editorTabs {{ background-color: {PANEL_BG}; }}
QTabWidget#editorTabs::pane {{ background-color: {BODY_BG}; border: none; border-top: 1px solid {BLACK}; }}
QTabWidget#editorTabs > QTabBar::tab {{ min-height: 32px; padding: 0 14px; }}

/* document tabs (workbox) on the black title bar */
QTabWidget#workbox {{ background-color: {TITLE_BAR_BG}; }}
QTabWidget#workbox::pane {{ background-color: {BODY_BG}; border: none; }}
QTabWidget#workbox > QTabBar::tab {{
    background-color: {BODY_BG}; color: {TEXT_MUTED};
    border: none; border-left: 1px solid {BLACK};
    min-height: {ACTION_BAR_HEIGHT}px; max-height: {ACTION_BAR_HEIGHT}px;
    padding: 0 8px 0 12px; min-width: 80px;
}}
QTabWidget#workbox > QTabBar::tab:selected {{ background-color: {PANEL_BG}; color: {TEXT}; }}
QTabWidget#workbox > QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QTabWidget#workbox > QTabBar::close-button {{
    image: url({times}); subcontrol-position: right; width: 10px; height: 10px; margin-left: 6px;
}}
QTabWidget#workbox > QTabBar::close-button:hover {{ image: url({times_hover}); }}
QTabWidget#workbox > QTabBar QToolButton {{ background-color: {TITLE_BAR_BG}; border: none; }}

/* ---------- scroll bars (thin, rounded) ---------- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle {{ background-color: {LIGHT_GRAY}; border-radius: 4px; }}
QScrollBar::handle:vertical {{ min-height: 24px; }}
QScrollBar::handle:horizontal {{ min-width: 24px; }}
QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background-color: {SMOKE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QAbstractScrollArea::corner {{ background: transparent; }}

/* ---------- item views ---------- */
QAbstractItemView {{
    background-color: {INPUT_BG}; alternate-background-color: #383838; color: {TEXT};
    border: 1px solid {BLACK}; outline: 0;
    selection-background-color: {SELECTED_BG}; selection-color: {WHITE};
    gridline-color: {BLACK};
}}
QAbstractItemView::item {{ padding: 2px 4px; }}
QAbstractItemView::item:hover {{ background-color: {PANEL_BG}; }}
QAbstractItemView::item:selected {{ background-color: {SELECTED_BG}; color: {WHITE}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:closed {{ image: url({caret_right}); }}
QTreeView::branch:has-children:open {{ image: url({caret_down}); }}
QHeaderView {{ background-color: {BODY_BG}; border: none; }}
QHeaderView::section {{
    background-color: {BODY_BG}; color: {TEXT_MUTED}; padding: 4px 8px;
    border: none; border-right: 1px solid {BLACK}; border-bottom: 1px solid {BLACK};
}}
QTableCornerButton::section {{ background-color: {BODY_BG}; border: none; }}

/* ---------- menus (generic drop down menu) ---------- */
QMenuBar {{ background-color: {TITLE_BAR_BG}; color: {TEXT}; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background-color: {PANEL_BG}; }}
QMenu {{ background-color: {INPUT_BG}; color: {TEXT}; border: 1px solid {BLACK}; padding: 0; }}
QMenu::item {{ padding: 7px 24px 7px 14px; border-bottom: 1px solid {BLACK}; }}
QMenu::item:selected {{ background-color: {PANEL_BG}; }}
QMenu::item:disabled {{ color: {TEXT_DISABLED}; }}
QMenu::separator {{ height: 1px; background-color: {BLACK}; }}

/* ---------- check boxes / radio buttons / toggles ---------- */
QCheckBox, QRadioButton {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator, QGroupBox::indicator {{
    width: 13px; height: 13px; background-color: {INPUT_BG};
    border: 1px solid {HOVER_BORDER}; border-radius: 2px;
}}
QCheckBox::indicator:hover {{ border-color: {SKY}; }}
QCheckBox::indicator:checked, QGroupBox::indicator:checked {{
    background-color: {SKY}; border-color: {SKY}; image: url({check});
}}
QCheckBox::indicator:indeterminate {{ background-color: {SKY}; border-color: {SKY}; image: url({minus}); }}
QCheckBox::indicator:disabled {{ background-color: {PANEL_BG}; border-color: #4a4a4a; }}
/* ct-toggle-slider */
QCheckBox[toggle="true"] {{ spacing: 0; }}
QCheckBox[toggle="true"]::indicator {{
    width: 40px; height: 20px; border: none; background: transparent; image: url({toggle_off});
}}
QCheckBox[toggle="true"]::indicator:checked {{ image: url({toggle_on}); }}
QCheckBox[toggle="true"]::indicator:disabled {{ image: url({toggle_off_disabled}); }}
QCheckBox[toggle="true"]::indicator:checked:disabled {{ image: url({toggle_on_disabled}); }}
QRadioButton::indicator {{
    width: 13px; height: 13px; background-color: {INPUT_BG};
    border: 1px solid {HOVER_BORDER}; border-radius: 7px;
}}
QRadioButton::indicator:checked {{
    border-color: {SKY};
    background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {WHITE}, stop:0.32 {WHITE}, stop:0.42 {SKY}, stop:1 {SKY});
}}

/* ---------- containers ---------- */
QGroupBox {{
    background-color: {PANEL_BG}; border: 1px solid {BLACK}; border-radius: 2px;
    margin-top: 18px; padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 4px; padding: 0 2px;
    color: {TEXT};
}}
QFrame#formSection {{ background-color: {PANEL_BG}; border: none; border-radius: 2px; }}
QFrame#formSection[borderless="true"] {{ background: transparent; }}
QLabel[help="true"] {{ color: {TEXT_MUTED}; }}
QLineEdit[expression="true"] {{ padding-left: 30px; color: {TEXT_MUTED}; }}
QLabel#expressionPrefix {{ color: {TEXT_MUTED}; font-weight: bold; background: transparent; }}
QLineEdit[invalid="true"] {{ border-color: {RED}; }}
/* expression editor modal */
QFrame#modalFrame {{ background-color: {PANEL_BG}; border-radius: 2px; }}
QWidget#modalHeader {{ background-color: {TITLE_BAR_BG}; border-top-left-radius: 2px; border-top-right-radius: 2px; }}
QWidget#modalFooter {{ background-color: {PANEL_BG}; border-top: 1px solid {BLACK}; }}
QFrame#previewFrame {{ border: none; border-top: 1px solid {BLACK}; }}
QTreeView#contextTree {{
    background-color: {PANEL_BG}; border: none; border-left: 1px solid {BLACK}; padding: 0 10px 0 4px;
    selection-background-color: {BODY_BG};
}}
QTreeView#contextTree::branch:selected {{ background-color: {BODY_BG}; }}
QTreeView#contextTree::item {{ padding: 3px 2px; }}
QTreeView#contextTree::item:hover {{ background: transparent; }}
QTreeView#contextTree::item:selected {{ background-color: {BODY_BG}; color: {WHITE}; }}
QTreeView#contextTree::branch:has-children:closed {{ image: url({angle_right}); }}
QTreeView#contextTree::branch:has-children:open {{ image: url({angle_down}); }}
/* object inspector (ct-editor-inspector) */
QFrame#inspector {{ background-color: {PANEL_BG}; border: none; }}
QWidget#inspectorHeader {{ background-color: {PANEL_BG}; border-bottom: 1px solid {BLACK}; }}
QWidget#inspectorBody {{ background-color: {PANEL_BG}; }}
QSplitter#inspectorSplitter::handle {{ background-color: {PANEL_BG}; border-left: 1px solid {BLACK}; }}
QFrame#listRow[inspected="true"] {{ background-color: {SELECTED_BG}; border-color: {SKY}; }}
/* workflow step inspector (ct-workflow-step-inspector) */
QTabBar#stepInspectorTabs {{ background-color: {PANEL_BG}; }}
QTabBar#stepInspectorTabs::tab {{ min-height: 32px; padding: 0 6px; }}
QFrame#stepInputBox {{ background: transparent; border: none; border-bottom: 1px solid {BLACK}; }}
QLabel[dangerText="true"] {{ color: {RED}; }}
QLabel[warningText="true"] {{ color: {ORANGE}; }}
QLabel[small="true"] {{ font-size: 11px; }}
QPushButton#portOptionsButton {{
    background: transparent; border: none; padding: 0 2px; min-height: 0; color: {TEXT};
}}
QPushButton#portOptionsButton:hover {{ color: {WHITE}; }}
QFrame#portOptionsMenu {{ background-color: {INPUT_BG}; border: 1px solid {BLACK}; border-radius: 2px; }}
QFrame#portOption {{ background: transparent; border: none; border-bottom: 1px solid {BLACK}; }}
QFrame#portOption:hover, QFrame#portOption[active="true"] {{ background-color: {GRAY}; }}
QFrame#portOption QLabel {{ background: transparent; }}
QListWidget#scatterList {{
    background-color: {INPUT_BG}; border: 1px solid {INPUT_BORDER}; border-radius: 2px; padding: 2px 0;
}}
QListWidget#scatterList::item {{ padding: 3px 9px; color: {TEXT}; }}
QListWidget#scatterList::item:selected {{ background-color: {SELECTED_BG}; color: {WHITE}; }}
QToolButton#sectionToggle, QToolButton#sectionToggle:hover, QToolButton#sectionToggle:pressed {{
    background: transparent; border: none; padding: 0;
}}
/* list entries (.editor-list-item) */
QFrame#listRow {{ background-color: {INPUT_BG}; border: 1px solid {INPUT_BORDER}; border-radius: 2px; }}
QFrame#listRow:hover {{ border-color: {SKY}; }}
QFrame#listRow QLineEdit, QFrame#listRow QLabel {{
    background: transparent; border: none; padding: 0; margin: 0; color: {TEXT};
}}
QFrame#separator {{ background-color: {BLACK}; border: none; max-height: 1px; min-height: 1px; }}
QFrame#panelSeparator {{ background-color: {BODY_BG}; border: none; }}
QSplitter::handle {{ background-color: {BLACK}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}
QProgressBar {{
    background-color: {INPUT_BG}; border: 1px solid {BLACK}; border-radius: 2px;
    color: {TEXT}; text-align: center;
}}
QProgressBar::chunk {{ background-color: {SKY}; }}

/* ---------- application chrome (layout.component) ---------- */
QWidget#sidebar {{ background-color: {PANEL_BG}; }}
QWidget#titleBar {{ background-color: {TITLE_BAR_BG}; }}
QLabel#appTitle {{ color: {WHITE}; padding-left: 14px; }}
QWidget#sidebar QAbstractItemView {{ background-color: {PANEL_BG}; border: none; }}
QWidget#sidebar QAbstractItemView::item {{ padding: 3px 2px; }}
QWidget#sidebar QAbstractItemView::item:hover {{ background-color: #363636; }}
QWidget#sidebar QAbstractItemView::item:selected {{ background-color: {BODY_BG}; color: {WHITE}; }}
QWidget#sidebar QTabWidget::pane {{ border: none; }}
QWidget#sidebar QTabBar::tab {{ min-height: 32px; padding: 0 16px; }}
QWidget#welcome {{ background-color: {BODY_BG}; }}
QFrame#creationEntry {{
    background-color: {PANEL_BG}; border: 1px solid {INPUT_BORDER}; border-radius: 2px;
}}
QFrame#creationEntry:hover {{ border-color: {SKY}; }}
QWidget#actionBar {{ background-color: {PANEL_BG}; border-bottom: 1px solid {BLACK}; }}
QStatusBar {{ background-color: {STATUS_BAR_BG}; color: {TEXT}; border-top: 1px solid {BLACK}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {TEXT}; padding: 0 8px; }}

/* ---------- command line preview (ct-command-line-preview) ---------- */
CommandLine {{ background-color: {TERMINAL_BG}; border-top: 1px solid {BLACK}; }}
CommandLine QTextEdit {{ background-color: {TERMINAL_BG}; border: none; color: {CODE_STREAM}; }}
"""


def styleSheet() -> str:
    values = {name: value for name, value in globals().items()
              if name.isupper() and isinstance(value, (str, int))}
    values.update(_indicatorImages())
    return STYLE_SHEET.format(**values)


def applyTheme(app: QApplication):
    """Install the Composer look and feel on the application."""
    loadFonts()
    app.setStyle('Fusion')
    app.setPalette(_palette())
    app.setStyleSheet(styleSheet())
    # workflow graph edges are drawn as cwl-svg edges
    import GraphItems
    GraphItems.patchPipes()
