import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLineEdit, QLabel, QPushButton, QHBoxLayout, QScrollArea, QLayout,QMessageBox
)
from PyQt6.QtCore import Qt, QSize, QRect, QPoint , QTimer
import theme
import logging
logger = logging.getLogger(__name__)

class Tag(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.init_ui()

    def init_ui(self):
        # Create a horizontal layout for the tag
        layout = QHBoxLayout()

        # Create the label to display the tag text
        self.label = QLabel(self.text)
        layout.addWidget(self.label)

        # Create the remove button with an "x"
        self.remove_button = QPushButton("x")
        self.remove_button.setFixedSize(16, 16)
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.clicked.connect(self.remove_self)
        layout.addWidget(self.remove_button)

        # Set layout and appearance
        self.setLayout(layout)
        # Composer tag: blue pill with white text (theme.STYLE_SHEET, "Tag")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def remove_self(self):
        # Remove this tag from the parent widget (the tag list)
        parent=self.parent()
        widget_parent = None
        while parent:
            if isinstance(parent, QTagWidget):
                widget_parent = parent
                break
            parent = parent.parent()

        
        self.setParent(None)
        self.deleteLater()
        if widget_parent:
            widget_parent.tag_removed()

    def get_text(self):
        return self.text

    def __str__(self):
        return f"Tag(text='{self.get_text()}')"
    def __repr__(self):
        """Return a formal string representation of the Tag object."""
        return self.__str__()
    
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=0):  # Set default spacing to 2
        super().__init__(parent)
        self.itemList = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0

        for item in self.itemList:
            wid = item.widget()
            spaceX = self.spacing()
            spaceY = self.spacing()
            nextX = x + wid.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + wid.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), wid.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, wid.sizeHint().height())

        return y + lineHeight - rect.y()

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.widget().minimumSizeHint())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

class QTagWidget(QWidget):
    def __init__(self, max_tags=float('inf'), parent=None):
        super().__init__(parent=parent)
        self.max_tags=max_tags
        self.tag_counter=0
        self.init_ui()



    def init_ui(self):
        # Main layout
        main_layout = QVBoxLayout()
        self.enum_table_label=QLabel("Values:")
        main_layout.addWidget(self.enum_table_label)
        # Input field for tags
        self.tag_input = QLineEdit(self)
        self.tag_input.setPlaceholderText("Enter a value and press Shift + Enter")
        self.tag_input.returnPressed.connect(self.add_tag)
        main_layout.addWidget(self.tag_input)

        # Flow layout for tags
        self.flow_layout = FlowLayout(spacing=2)  # Set spacing to 2 pixels
        tag_container = QWidget()
        tag_container.setLayout(self.flow_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(tag_container)
        scroll_area.setStyleSheet("border: none;")

        main_layout.addWidget(scroll_area)

        # Set the main layout
        self.setLayout(main_layout)
        self.setWindowTitle('Tag Input Widget with Removable Tags')
        self.resize(400, 300)

    def setTags( self, tags:list):
        '''
        add the tags 
        '''
        if isinstance( tags, list):
            for tag in tags:
                self.add_tag( tag )
        if isinstance( tags, str):
            self.add_tag(tags)



    def add_tag(self, text:str=None):
        # Get the tag from the input field
        logger.debug(f"In add_tag {text}")
        if self.tag_counter >= self.max_tags:
            msg_box=QMessageBox(self)
            msg_box.setWindowTitle("Information")
            msg_box.setText(f"These {self.tag_counter} tags exceeded the maximum allowed number {self.max_tags}.")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.setIcon(QMessageBox.Icon.Information)
            response = msg_box.exec()
            if response == QMessageBox.StandardButton.Ok:
                return

        if text :
            tag_text=text
        else:
            tag_text = self.tag_input.text().strip()
        if tag_text:
            # Create and add the tag widget to the flow layout
            tag = Tag(tag_text)
            self.flow_layout.addWidget(tag)
            self.tag_input.clear()
            self._updateCounter()

            logger.debug(f"Added new tag { tag }")
 

    def tag_removed(self):
        """Update tag counter when a tag is removed"""
        logger.debug(f"Notified that a tag has been deleted. We start with { len(self.getTags() )} tags")
        QTimer.singleShot(0, self._updateCounter )  # Process the deletion event
        logger.debug(f"After processing with have { len(self.getTags() ) } tags")
        logger.debug(self)

    def _updateCounter(self):

        self.tag_counter= len( self.getTags() )


    def getTags(self):
        # Retrieve the text of all tags
        tag_values = []
        for i in range(self.flow_layout.count()):
            item = self.flow_layout.itemAt(i)
            if item:
                tag_widget = item.widget()
                if isinstance(tag_widget, Tag):
                    tag_values.append(tag_widget.get_text())
        return tag_values
    
    def __str__(self):
        ret=f"Tags: There are {len(self.getTags())} tags"
        tag_counter=1
        for tags in self.getTags():
            ret=f"{ret}\n{tag_counter}\tTag(text={tags})"
            tag_counter +=1
        return ret
    

# Application setup
if __name__ == "__main__" :
    app = QApplication(sys.argv)
    tag_widget = QTagWidget()
    tag_widget.show()

    tag_widget.setTags(['test1','test2','test3'])

    # Example usage to get tag values
    def print_tag_values():
        print("Tag values:", tag_widget.getTags())

    # Print tag values after adding some tags
    import time
    time.sleep(2)  # Allow some time for user interaction
    print_tag_values()

    sys.exit(app.exec())
