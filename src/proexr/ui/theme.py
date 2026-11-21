from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QApplication

from . import palette


def _hex(color) -> str:
    return color.name()


def stylesheet() -> str:
    p = {name: _hex(getattr(palette, name)) for name in (
        "BACKGROUND", "SURFACE", "SURFACE_RAISED", "SURFACE_HOVER", "BORDER", "BORDER_STRONG", "TEXT",
        "TEXT_MUTED", "TEXT_FAINT", "ACCENT", "ACCENT_SOFT", "ACCENT_TEXT")}
    return f"""
QMainWindow, QDialog {{ background: {p['BACKGROUND']}; }}
QWidget {{ color: {p['TEXT']}; font-size: 10pt; }}
QMainWindow::separator {{ background: {p['BACKGROUND']}; width: 4px; height: 4px; }}
QMainWindow::separator:hover {{ background: {p['ACCENT']}; }}
QDockWidget {{ color: {p['TEXT_MUTED']}; }}
QDockWidget::title {{ background: {p['SURFACE']}; padding: 6px 10px; }}
QToolBar {{ background: {p['SURFACE']}; border: none; border-bottom: 1px solid {p['BORDER']}; spacing: 6px; padding: 4px 8px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 8px; min-height: 24px; }}
QToolButton:hover {{ background: {p['SURFACE_HOVER']}; border-color: {p['BORDER']}; }}
QToolButton:checked {{ background: {p['ACCENT_SOFT']}; border-color: {p['ACCENT']}; color: {p['ACCENT_TEXT']}; }}
QToolButton:focus, QPushButton:focus, QComboBox:focus, QAbstractSpinBox:focus {{ border-color: {p['ACCENT']}; }}
QPushButton {{ background: {p['SURFACE_RAISED']}; border: 1px solid {p['BORDER']}; border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ background: {p['SURFACE_HOVER']}; }}
QComboBox, QAbstractSpinBox, QLineEdit {{ background: {p['BACKGROUND']}; border: 1px solid {p['BORDER']};
    border-radius: 6px; padding: 3px 8px; min-height: 22px; selection-background-color: {p['ACCENT']}; }}
QComboBox:hover, QAbstractSpinBox:hover {{ border-color: {p['BORDER_STRONG']}; }}
QComboBox QAbstractItemView {{ background: {p['SURFACE_RAISED']}; border: 1px solid {p['BORDER']};
    selection-background-color: {p['ACCENT_SOFT']}; selection-color: {p['ACCENT_TEXT']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {p['BORDER']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p['ACCENT']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p['TEXT']}; width: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: {p['ACCENT_TEXT']}; }}
QListWidget, QTreeWidget {{ background: {p['SURFACE']}; border: none; alternate-background-color: {p['SURFACE_RAISED']}; }}
QListWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {p['BORDER']}; }}
QListWidget::item:hover {{ background: {p['SURFACE_HOVER']}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {p['ACCENT_SOFT']}; color: {p['ACCENT_TEXT']}; }}
QHeaderView::section {{ background: {p['SURFACE_RAISED']}; color: {p['TEXT_MUTED']}; border: none; padding: 5px; }}
QStatusBar {{ background: {p['SURFACE']}; color: {p['TEXT_MUTED']}; border-top: 1px solid {p['BORDER']}; }}
QMenuBar {{ background: {p['SURFACE']}; color: {p['TEXT_MUTED']}; }}
QMenuBar::item:selected {{ background: {p['SURFACE_HOVER']}; color: {p['TEXT']}; }}
QMenu {{ background: {p['SURFACE_RAISED']}; border: 1px solid {p['BORDER']}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {p['ACCENT_SOFT']}; color: {p['ACCENT_TEXT']}; }}
QScrollBar:vertical {{ background: {p['SURFACE']}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p['BORDER_STRONG']}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {p['SURFACE_RAISED']}; color: {p['TEXT']}; border: 1px solid {p['BORDER']}; padding: 4px; }}
QLabel[role="muted"] {{ color: {p['TEXT_MUTED']}; }}
QLabel[role="section"] {{ color: {p['TEXT_FAINT']}; font-size: 9pt; padding-top: 10px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    colors = QPalette()
    colors.setColor(QPalette.Window, palette.BACKGROUND)
    colors.setColor(QPalette.WindowText, palette.TEXT)
    colors.setColor(QPalette.Base, palette.BACKGROUND)
    colors.setColor(QPalette.AlternateBase, palette.SURFACE_RAISED)
    colors.setColor(QPalette.Text, palette.TEXT)
    colors.setColor(QPalette.Button, palette.SURFACE_RAISED)
    colors.setColor(QPalette.ButtonText, palette.TEXT)
    colors.setColor(QPalette.Highlight, palette.ACCENT)
    colors.setColor(QPalette.HighlightedText, palette.TEXT)
    colors.setColor(QPalette.ToolTipBase, palette.SURFACE_RAISED)
    colors.setColor(QPalette.ToolTipText, palette.TEXT)
    colors.setColor(QPalette.Disabled, QPalette.Text, palette.TEXT_FAINT)
    colors.setColor(QPalette.Disabled, QPalette.ButtonText, palette.TEXT_FAINT)
    app.setPalette(colors)
    font = QFont()
    font.setFamilies([f.strip() for f in palette.FONT_FAMILY.split(",")])
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet())
