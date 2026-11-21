"""Entry point: ``python -m proexr [files or folders...]``."""
import os
import sys


def main(argv=None):
    argv = sys.argv if argv is None else argv
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    from .ui import theme
    from .ui.viewer import default_format

    QSurfaceFormat.setDefaultFormat(default_format())
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(argv)
    app.setApplicationName("ProEXR Viewer")
    app.setOrganizationName("PROEXR_MORU")
    theme.apply(app)

    from .ui.mainwindow import MainWindow
    win = MainWindow()
    win.show()
    paths = [a for a in argv[1:] if not a.startswith("-")]
    if paths:
        win.open_paths(paths)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
