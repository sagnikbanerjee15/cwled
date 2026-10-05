from PyQt6 import sip
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction, QIcon, QFont, QColor,QFontMetrics
import json
import builtins
import data
import theme
import logging
from sanitizeName import sanitize
from typing import Union, Any
from helperFunctions import addArrayItem
from nested_lookup import nested_lookup, nested_update




class QLabelLineEditWidget(QWidget):
    # Define a custom signal that emits the text as a string
    editingFinished = pyqtSignal()
    textChanged=pyqtSignal()
    def __init__(self, 
                 label_text="", 
                 placeholder_text="", 
                 objectName="",
                 labelWidth=None,
                 parent=None,
                 stacked=False):
        super().__init__(parent)
        # Initialize the QLabel and QLineEdit
        if not labelWidth:
            labelWidth=builtins.labelWidth
        self.stacked = stacked
        self.label = QLabel(label_text, self)
        if not stacked:
            self.label.setFixedWidth(labelWidth)
        self.line_edit = QLineEdit(self)
        if placeholder_text:
            self.setPlaceholderText( placeholder_text=placeholder_text)
        if objectName:
            self.setObjectName(objectName)
        self.initUI()
        
    def initUI( self ):   
        # Create a layout and add the QLabel and QLineEdit to it
        # (stacked: label above the field, as in Composer forms)

        if self.stacked:
            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
        else:
            layout = QHBoxLayout()
        
        layout.addWidget(self.label)
        
        layout.addWidget(self.line_edit)
        
        # Set the layout for the custom widget
        self.setLayout(layout)
        if not self.stacked:
            # no side margins, so labels line up with section titles
            margins = layout.contentsMargins()
            layout.setContentsMargins(0, margins.top(), 0, margins.bottom())
        # Connect the textChanged signal of QLineEdit to a custom slot
        self.line_edit.editingFinished.connect(self.on_text_finished)
        self.line_edit.textChanged.connect(self.on_text_changed)

    def attachButton(self, button: QPushButton) -> QWidget:
        """Attach ``button`` (e.g. the </> expression button) to the right
        end of the field, as a Composer input group."""
        layout = self.layout()
        index = layout.indexOf(self.line_edit)
        group = theme.InputGroup(self.line_edit, button, parent=self)
        layout.insertWidget(index, group)
        return group

    def setLabel(self, label:str):
        self.label.setText( label )
    def setPlaceholderText( self, placeholder_text:str):
        self.line_edit.setPlaceholderText(placeholder_text)
    def setText( self, text:Any):
        self.line_edit.setText(str(text))
    def setCursorPosition( self, position:int):
        self.line_edit.setCursorPosition(position)
    def text(self):
        return self.line_edit.text()

    @pyqtSlot()
    def on_text_finished(self):
        # This slot will be called whenever the text in QLineEdit changes
        self.editingFinished.emit()
    @pyqtSlot()
    def on_text_changed(self):
        # This slot will be called whenever the text in QLineEdit changes
        self.textChanged.emit()


class QLabelTextEditWidget(QWidget):
    # Define a custom signal that emits the text as a string
    editingFinished = pyqtSignal()
    textChanged = pyqtSignal()
    
    def __init__(self, 
                 label_text="", 
                 placeholder_text="", 
                 objectName="",
                 labelWidth=None,
                 parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Initialize the QLabel and QTextEdit
        self.label = QLabel(label_text, self)
        if not labelWidth:
            labelWidth = builtins.labelWidth
        self.label.setFixedWidth(labelWidth)
        self.text_edit = QTextEdit(self)
        
        # Track the previous text to detect actual changes
        self._previous_text = ""
        
        if placeholder_text:
            self.setPlaceholderText(placeholder_text=placeholder_text)
        if objectName:
            self.setObjectName(objectName)
        self.initUI()
        
    def initUI(self):   
        # Create a layout and add the QLabel and QTextEdit to it
        layout = QHBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.text_edit)
        
        # Set the layout for the custom widget
        self.setLayout(layout)
        # no side margins, so labels line up with section titles
        margins = layout.contentsMargins()
        layout.setContentsMargins(0, margins.top(), 0, margins.bottom())
        
        # Connect the textChanged signal
        self.text_edit.textChanged.connect(self.on_text_changed)
        
        # Install event filter to detect focus changes
        self.text_edit.installEventFilter(self)

    def eventFilter(self, obj, event):
        if sip.isdeleted(self):
            # being destroyed: Qt still delivers its dying children's events here
            return False
        """
        Event filter to detect when QTextEdit loses focus.
        This allows us to emit editingFinished similar to QLineEdit.
        """
        if obj == self.text_edit:
            if event.type() == QEvent.Type.FocusOut:
                # Check if text actually changed before emitting
                current_text = self.text_edit.toPlainText()
                if current_text != self._previous_text:
                    self._previous_text = current_text
                    self.on_text_finished()
        return super().eventFilter(obj, event)

    def setLabel(self, label: str):
        self.label.setText(label)
        
    def setPlaceholderText(self, placeholder_text: str):
        self.text_edit.setPlaceholderText(placeholder_text)
        
    def setText(self, text: str):
        self.text_edit.setText(text)
        # Update previous text to prevent false change detection
        self._previous_text = text
        
    def toPlainText(self):
        """Get the plain text from the QTextEdit."""
        return self.text_edit.toPlainText()
    
    def text(self):
        """Alias for toPlainText() for consistency with QLineEdit interface."""
        return self.text_edit.toPlainText()

    @pyqtSlot()
    def on_text_finished(self):
        """Emit editingFinished signal when editing is complete."""
        self.logger.debug(f"Emitting editingFinished for {self.label.text()}")
        self.editingFinished.emit()
        
    @pyqtSlot()
    def on_text_changed(self):
        """Emit textChanged signal when text changes."""
        self.textChanged.emit()