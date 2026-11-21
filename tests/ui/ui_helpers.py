from PySide6.QtWidgets import QApplication


def settle(app: QApplication, rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()
