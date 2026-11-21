import pytest
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from proexr.ui.viewer import surface_format


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    QSurfaceFormat.setDefaultFormat(surface_format())
    app = QApplication.instance() or QApplication([])
    yield app
