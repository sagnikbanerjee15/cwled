from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout
from .qButtons import QAddButton
import data
import theme


class HeaderWithAddButton(QWidget):
    """
    A reusable header widget that consists of a label and an add button.
    
    This class standardizes the appearance of group widget headers
    across the application for UI/UX consistency.
    """
    
    # Signal emitted when the add button is clicked
    addButtonClicked = pyqtSignal()
    
    def __init__(
        self,
        title: str,
        parent=None,
        show_add_button: bool = True
    ):
        """
        Initialize the header widget.
        
        Args:
            title: The text to display in the header
            parent: Parent widget
            show_add_button: Whether to show the add button
        """
        super().__init__(parent)
        
        # Initialize the UI
        self._title = title
        self._show_add_button = show_add_button
        self.initUI()
    
    def initUI(self):
        """Initialize the user interface."""
        # Create header layout
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)  # Consistent spacing
        
        # Create and configure the label
        self.label = theme.styleTitle(QLabel(self._title, self))
        label_width = data.configuration.get('label_width', 100)
        self.label.setFixedWidth(label_width)
        header_layout.addWidget(self.label)
        
        # Create and configure the add button if needed
        if self._show_add_button:
            self.add_button = QAddButton(self)
            header_layout.addWidget(self.add_button)
            
            # Connect the button's clicked signal to our signal
            self.add_button.clicked.connect(self.addButtonClicked.emit)
        
        # Add stretch to push everything to the left
        header_layout.addStretch(1)
        
        # Set the layout for this widget
        self.setLayout(header_layout)
    
    def setTitle(self, title: str):
        """
        Set the header title.
        
        Args:
            title: The new title text
        """
        self._title = title
        self.label.setText(title)
    
    def title(self) -> str:
        """
        Get the current header title.
        
        Returns:
            The current title text
        """
        return self._title
    
    def addButton(self) -> QAddButton:
        """
        Get the add button widget.
        
        Returns:
            The QAddButton instance or None if not shown
        """
        return self.add_button if self._show_add_button else None
