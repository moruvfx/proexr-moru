import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import apply_theme
from .ui.viewer import surface_format


def main() -> int:
    QSurfaceFormat.setDefaultFormat(surface_format())
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("ProEXR Viewer")
    app.setOrganizationName("PROEXR_MORU")
    apply_theme(app)
    window = MainWindow()
    window.show()
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if paths:
        window.open_paths(paths)
    return app.exec()
