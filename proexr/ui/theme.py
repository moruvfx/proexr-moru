from PySide6.QtGui import QColor, QPalette

STYLE = """
* { font-size: 9pt; }
QMainWindow, QDialog { background: #1c1c1f; }
QMainWindow::separator { background: #121214; width: 3px; height: 3px; }
QMainWindow::separator:hover { background: #ff8c32; }
QDockWidget { color: #9a9aa2; titlebar-close-icon: none; }
QDockWidget::title { background: #232327; padding: 5px 8px; text-transform: uppercase; }
QToolBar { background: #202023; border: none; border-bottom: 1px solid #131315; spacing: 6px; padding: 3px 6px; }
QToolButton { color: #d0d0d6; background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 3px 7px; }
QToolButton:hover { background: #2e2e33; border-color: #3a3a40; }
QToolButton:checked { background: #3a2a1c; border-color: #ff8c32; color: #ffb37a; }
QPushButton { background: #2c2c31; border: 1px solid #3a3a40; border-radius: 4px; padding: 4px 10px; color: #ddd; }
QPushButton:hover { background: #36363c; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #151517; border: 1px solid #333338;
    border-radius: 4px; padding: 2px 6px; color: #e2e2e6; selection-background-color: #ff8c32; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #4a4a52; }
QComboBox QAbstractItemView { background: #1d1d20; border: 1px solid #333; selection-background-color: #3a2a1c; }
QSlider::groove:horizontal { height: 4px; background: #333338; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #8a5a30; border-radius: 2px; }
QSlider::handle:horizontal { background: #e6e6ea; width: 12px; margin: -5px 0; border-radius: 6px; }
QListWidget, QTreeWidget, QTableWidget { background: #18181b; border: none; color: #d6d6dc; alternate-background-color: #1c1c20; }
QListWidget::item { padding: 5px 6px; border-bottom: 1px solid #222226; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #3a2a1c; color: #ffcc9a; }
QHeaderView::section { background: #222226; color: #8a8a92; border: none; padding: 4px; }
QStatusBar { background: #161618; color: #9a9aa2; border-top: 1px solid #111; }
QStatusBar QLabel { padding: 0 8px; font-family: Consolas, "DejaVu Sans Mono", monospace; }
QMenuBar { background: #1a1a1d; color: #c8c8ce; }
QMenuBar::item:selected { background: #2e2e33; }
QMenu { background: #1f1f23; border: 1px solid #333; color: #ddd; }
QMenu::item:selected { background: #3a2a1c; color: #ffcc9a; }
QLabel#section { color: #7d7d86; font-size: 8pt; text-transform: uppercase; padding-top: 8px; }
QScrollBar:vertical { background: #18181b; width: 10px; }
QScrollBar::handle:vertical { background: #3a3a40; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QToolTip { background: #2a2a2e; color: #eee; border: 1px solid #444; }
"""


def apply(app):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(28, 28, 31))
    pal.setColor(QPalette.WindowText, QColor(214, 214, 220))
    pal.setColor(QPalette.Base, QColor(21, 21, 23))
    pal.setColor(QPalette.AlternateBase, QColor(30, 30, 34))
    pal.setColor(QPalette.Text, QColor(226, 226, 230))
    pal.setColor(QPalette.Button, QColor(44, 44, 49))
    pal.setColor(QPalette.ButtonText, QColor(220, 220, 226))
    pal.setColor(QPalette.Highlight, QColor(255, 140, 50))
    pal.setColor(QPalette.HighlightedText, QColor(20, 20, 20))
    pal.setColor(QPalette.ToolTipBase, QColor(42, 42, 46))
    pal.setColor(QPalette.ToolTipText, QColor(238, 238, 238))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(100, 100, 106))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(100, 100, 106))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)
