import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import apply_theme
from .ui.viewer import surface_format


def self_test(report_path: str) -> int:
    """Writes the versions of every native library to a file; used to check a packaged build starts."""
    import av
    import numpy
    import OpenImageIO
    import PyOpenColorIO
    from av.codec.hwaccel import hwdevices_available

    from . import __version__
    lines = [f"proexr {__version__}", f"numpy {numpy.__version__}", f"OpenImageIO {OpenImageIO.VERSION_STRING}",
             f"OpenColorIO {PyOpenColorIO.__version__}", f"PyAV {av.__version__}",
             f"hardware decoders {', '.join(hwdevices_available())}"]
    try:
        import sounddevice
        lines.append(f"PortAudio {sounddevice.get_portaudio_version()[1]}")
    except OSError as error:
        lines.append(f"PortAudio missing: {error}")
    PyOpenColorIO.Config.CreateFromFile("ocio://default")
    lines.append("OCIO builtin config ok")
    with open(report_path, "w", encoding="utf-8") as report:
        report.write("\n".join(lines) + "\n")
    return 0


def main() -> int:
    if "--version" in sys.argv:
        from . import __version__
        print(__version__)
        return 0
    if "--self-test" in sys.argv:
        return self_test(sys.argv[sys.argv.index("--self-test") + 1])
    QSurfaceFormat.setDefaultFormat(surface_format())
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("ProEXR Viewer")
    app.setOrganizationName("PROEXR_MORU")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "resources" / "proexr.png")))
    apply_theme(app)
    window = MainWindow()
    window.show()
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if paths:
        window.open_paths(paths)
    return app.exec()
