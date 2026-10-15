"""
The Problems panel of the Code tab: the messages of the last validation, one per line of the list.

The panel shows what it is given and reports a click on a message (``jumpRequested``) or a press of
the Check button (``checkRequested``); the rest is done by LiveValidation.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QToolButton, QVBoxLayout

from problems import Problem


class ProblemsPanel(QFrame):
    jumpRequested = pyqtSignal(int)     # the 1-based line of a problem that was clicked
    checkRequested = pyqtSignal()       # the Check button was pressed: validate now

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('problemsPanel')
        self.header = QToolButton()     # collapses and expands the panel; the text is the count
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.toggled.connect(self._onToggled)
        self.checkButton = QPushButton("Check")
        self.checkButton.setToolTip("Validate the document now")
        self.checkButton.clicked.connect(self._onCheck)
        self.note = QLabel()
        self.list = QListWidget()
        self.list.setMaximumHeight(120)
        self.list.itemClicked.connect(self._onItemClicked)
        self.list.itemActivated.connect(self._onItemClicked)

        headerLayout = QHBoxLayout()
        headerLayout.setContentsMargins(0, 0, 0, 0)
        headerLayout.addWidget(self.header)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.checkButton)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addLayout(headerLayout)
        layout.addWidget(self.note)
        layout.addWidget(self.list)
        self.setProblems([], note="Not checked yet.")

    def setProblems(self, problems: list[Problem], note: str = "No problems found.") -> None:
        """Show the problems (the header counts them); with none, the note says why the list is empty."""
        self.list.clear()
        for problem in problems:
            text = f"Line {problem.line}: {problem.message}" if problem.line is not None else problem.message
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, problem.line)
            self.list.addItem(item)
        self.header.setText(f"Problems ({len(problems)})")
        self.note.setText("" if problems else note)
        self._updateVisibility()

    def setChecking(self, checking: bool) -> None:
        """The Check button is busy while a validation runs."""
        self.checkButton.setEnabled(not checking)
        self.checkButton.setText("Checking..." if checking else "Check")

    def problemLines(self) -> list[int | None]:
        """The line of each entry of the list, in order (None for a message without a line)."""
        return [self.list.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.list.count())]

    def _onToggled(self, expanded: bool) -> None:
        self._updateVisibility()

    def _updateVisibility(self) -> None:
        expanded = self.header.isChecked()
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.list.setVisible(expanded and self.list.count() > 0)
        self.note.setVisible(expanded and self.list.count() == 0)

    def _onItemClicked(self, item: QListWidgetItem) -> None:
        line = item.data(Qt.ItemDataRole.UserRole)
        if line is not None:            # a message without a line has nowhere to jump to
            self.jumpRequested.emit(int(line))

    def _onCheck(self) -> None:
        self.checkRequested.emit()
