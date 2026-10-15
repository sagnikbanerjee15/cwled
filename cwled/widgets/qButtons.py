from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor,QFontMetrics

from copy import deepcopy
from helperFunctions import addArrayItem
import unicodedata
import data
import re
import theme

class QLineSeparator(QFrame):
     def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('separator')
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Plain)


class QIconButton(QPushButton):
    """Small icon-only button (Composer .btn-icon: muted glyph, light on hover)."""
    def __init__(self, icon_key: str, tooltip: str, parent=None,
                 color: str = None, hover_color: str = theme.TEXT):
        super().__init__(parent=parent)
        self._icon = theme.icon(icon_key, color=color)
        self._hover_icon = theme.icon(icon_key, color=hover_color)
        self.setIcon(self._icon)
        self.setIconSize(QSize(16, 16))
        self.setFixedSize(QSize(26, 26))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.setButtonRole(self, 'iconButton')

    def enterEvent(self, event):
        self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self._icon)
        super().leaveEvent(event)


class QEditButton(QIconButton):
    def __init__(self, parent=None):
        super().__init__('edit', "Edit", parent=parent)

class QCodeButton(QIconButton):
    def __init__(self, parent=None):
        super().__init__('programming', "Edit JavaScript expression", parent=parent)
    
class QRemoveButton(QIconButton):
    """Composer delete icon (.remove-icon): a bare trash glyph, grey on hover."""
    def __init__(self, parent=None):
        super().__init__('remove', "Delete", parent=parent,
                         color=theme.TEXT, hover_color=theme.LIGHT_GRAY)
        self.setIconSize(QSize(theme.REMOVE_ICON_WIDTH, theme.REMOVE_ICON_WIDTH))
        self.setFixedSize(QSize(theme.REMOVE_ICON_WIDTH, theme.formControlHeight()))
        self.setProperty('iconButton', False)
        theme.setButtonRole(self, 'plainIcon')

class QAddButton(QPushButton):
    """Composer "+ Add" link button."""
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setText("Add")
        self.setIcon(theme.icon('add'))
        self.setIconSize(QSize(12, 12))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.setButtonRole(self, 'link')

class ErrorDialog(QDialog):
    def __init__(self, error_message, details, title="Error", actions=None):
        # actions: (label, callable) pairs, one button each above OK; the dialog closes, then the callable runs
        super().__init__()
        self.setWindowTitle(title)
        self.setModal(True)
        
        # Layout for the error dialog
        layout = QVBoxLayout(self)

        # Main error message label
        error_message= "".join(ch for ch in error_message if unicodedata.category(ch)[0]!="C")
        error_label = QLabel(error_message)
        if re.search('error' , title.lower()):
            error_label.setStyleSheet(f"color: {theme.RED}; font-size: 16px; font-weight: bold;")
        else:
            error_label.setStyleSheet(f"color: {theme.GREEN}; font-size: 16px; font-weight: bold;")
        layout.addWidget(error_label)

        # Scrollable area for detailed text
        detailed_text = QTextEdit()
        cleaned_details = self.remove_ansi_escape_codes(details)
        cleaned_details= "".join(ch for ch in cleaned_details if unicodedata.category(ch)[0]!="C")
        cleaned_details.replace("\n", "<br>")
        detailed_text.setHtml(cleaned_details)
        detailed_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        
        # Set HTML formatted detailed error message
        detailed_text.setPlainText(details)
        detailed_text.setStyleSheet(f"background-color: {theme.TERMINAL_BG}; padding: 5px;")
        
        # Add the QTextEdit to the layout
        layout.addWidget(detailed_text)

        for label, action in actions or []:
            action_button = QPushButton(label)
            action_button.clicked.connect(lambda _checked=False, action=action: self._runAction(action))
            layout.addWidget(action_button)

        # OK button to close the dialog
        close_button = QPushButton("OK")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    def _runAction(self, action):
        self.accept()
        action()

    @staticmethod
    def remove_ansi_escape_codes( text:str):
        # Regular expression pattern for ANSI escape codes
        ansi_escape_pattern = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
        return ansi_escape_pattern.sub('', text)