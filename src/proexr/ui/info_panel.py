from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class InfoPanel(QTreeWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(2)
        self.setHeaderLabels(["Property", "Value"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setColumnWidth(0, 120)

    def show_properties(self, properties: dict[str, str]) -> None:
        self.clear()
        for name, value in properties.items():
            item = QTreeWidgetItem([name, value])
            item.setToolTip(1, value)
            self.addTopLevelItem(item)
