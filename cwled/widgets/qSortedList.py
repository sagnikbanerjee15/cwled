from typing import Any, List, Optional, cast
from pathlib import Path
import sys
import logging

from PyQt6.QtCore import QSize, Qt, pyqtSlot
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)
import data

import theme
try:
    import data
    from configuration import Configuration
except ModuleNotFoundError:
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    import data
    from configuration import Configuration

try:
    from widgets.QCWLedWidget import QCWLedWidget
except ModuleNotFoundError:
    from widgets.QCWLedWidget import QCWLedWidget


class QSortList(QCWLedWidget):
    """
    Widget for editing the order of a list of strings.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        cwl_tool: Optional[List[str]] = None,
        cwl_version: Optional[str] = None,
    ):
        super().__init__(
            parent=cast(QWidget, parent),
            cwl_tool=cwl_tool,
            cwl_version=cwl_version,
        )

    def initUI(self):
        super().initUI()


        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Source", "", ""])
        vertical_header = self.table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        self.table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(
                2, QHeaderView.ResizeMode.ResizeToContents
            )

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )

        if self.getCWL():
            self.populateFromCWL(self.getCWL())
        else:
            self._update_content_height()

    def _update_content_height(self):
        total_height = self.table.frameWidth() * 2
        header = self.table.horizontalHeader()
        if header is not None and not header.isHidden():
            total_height += header.height()
        for row in range(self.table.rowCount()):
            total_height += self.table.rowHeight(row)
        self.table.setFixedHeight(total_height)
        self.setFixedHeight(total_height)

    def _set_row(self, row: int, value: str):
        value_item = QTableWidgetItem(value)
        self.table.setItem(row, 0, value_item)

        move_up_button = QPushButton(self)
        move_up_button.setIcon(theme.icon('uparrow'))
        move_up_button.setIconSize(QSize(14, 14))
        theme.setButtonRole(move_up_button, 'iconButton')
        move_up_button.setFixedSize(QSize(28, 28))
        move_up_button.setToolTip("Move Up")
        move_up_button.clicked.connect(lambda: self._move_up(row))
        self.table.setCellWidget(row, 1, move_up_button)

        move_down_button = QPushButton(self)
        move_down_button.setIcon(theme.icon('downarrow'))
        move_down_button.setIconSize(QSize(14, 14))
        theme.setButtonRole(move_down_button, 'iconButton')
        move_down_button.setFixedSize(QSize(28, 28))
        move_down_button.setToolTip("Move Down")
        move_down_button.clicked.connect(lambda: self._move_down(row))
        self.table.setCellWidget(row, 2, move_down_button)

    def _rebuild_table(self, values: List[str]):
        self.logger.debug("Rebuilding table with %d items", len(values))
        self.table.setRowCount(len(values))
        for index, value in enumerate(values):
            self._set_row(index, value)
        self._update_content_height()

    def _swap_rows(self, first: int, second: int):
        self.logger.debug("Swapping rows %d and %d", first, second)
        values = self.getData()
        values[first], values[second] = values[second], values[first]
        self._rebuild_table(values)
        self._emit_editing_finished()

    @pyqtSlot()
    def _move_up(self, row: int):
        if row <= 0:
            return
        self._swap_rows(row, row - 1)

    @pyqtSlot()
    def _move_down(self, row: int):
        if row >= self.table.rowCount() - 1:
            return
        self._swap_rows(row, row + 1)

    def setCWL(self, cwl_tool: Optional[Any] = None):
        self.logger.debug("Setting CWL data for QSortList")
        if cwl_tool is not None and not isinstance(cwl_tool, list):
            self.logger.critical(
                f"Expected list, got {type(cwl_tool).__name__}"
            )
            return
        if isinstance(cwl_tool, list) and not all(
            isinstance(item, str) for item in cwl_tool
        ):
            self.logger.critical("QSortList expects a list of strings")
            return
        super().setCWL(cwl_tool)

    def populateFromCWL(self, cwl_data: Optional[List[str]] = None):
        self.logger.debug("Populating QSortList from CWL data")
        super().populateFromCWL(cwl_data)
        if cwl_data is None:
            cwl_data = self.getCWL()
        if cwl_data is None:
            self.table.setRowCount(0)
            self._update_content_height()
            return

        self._rebuild_table(cwl_data)

    def getData(self, *args: Any, **kwargs: Any) -> List[str]:
        ordered_values: List[str] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            ordered_values.append(item.text() if item else "")
        return ordered_values


def main():
    logger = logging.getLogger('')
    logger.setLevel(logging.DEBUG)
    if not logger.hasHandlers():
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        )

    conf = Configuration()
    try:
        conf.loadConfiguration("commandLineWindow.yaml")
    except FileNotFoundError:
        conf.loadConfiguration("cwled.yaml")
    data.configuration = conf.getConfiguration()

    app = QApplication(sys.argv)
    widget = QSortList(
        cwl_tool=["first", "second", "third", "fourth"],
        cwl_version="v1.2",
    )
    widget.setWindowTitle("QSortList Debug")
    widget.resize(560, 300)
    widget.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
