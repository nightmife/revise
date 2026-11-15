"""Thème sombre de l'application."""

SURFACE = "#13141a"
PANEL = "#1b1d26"
PANEL_2 = "#252836"
BORDER = "#313548"
TEXT = "#eceef5"
MUTED = "#9aa1b6"
ACCENT = "#6c8cff"
ACCENT_HOVER = "#8aa3ff"
ACCENT_DIM = "#2a3663"
GOOD = "#3ecf8e"
BAD = "#f0616d"
WARN = "#f5b84a"

# Notes de révision : couleur + libellé + raccourci (jamais la couleur seule)
RATING_COLORS = {1: "#d9434e", 2: "#e0803f", 3: "#2f9e6b", 4: "#4f7df0"}
# Rampe séquentielle (une teinte, du faible au fort) sur fond sombre
HEAT = ["#252836", "#2c3f7a", "#3f5cc0", "#6c8cff", "#b0c0ff"]

QSS = f"""
* {{ font-size: 11pt; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#page, QStackedWidget {{ background: {SURFACE}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QLabel#appname {{ font-size: 21pt; font-weight: 800; color: {ACCENT}; padding: 22px 18px 2px 18px; }}
QLabel#tagline {{ color: {MUTED}; padding: 0 18px 18px 18px; font-size: 9.5pt; }}
QPushButton#nav {{ text-align: left; padding: 11px 16px; border: none; border-radius: 9px; margin: 2px 10px;
                   background: transparent; color: {MUTED}; font-size: 11.5pt; font-weight: 500; }}
QPushButton#nav:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {ACCENT_DIM}; color: white; font-weight: 700; }}
QPushButton#nav:disabled {{ color: #5d6276; background: transparent; }}
QPushButton#side {{ text-align: left; padding: 7px 16px; border: none; border-radius: 9px; margin: 2px 10px;
                    background: transparent; color: {MUTED}; font-size: 10pt; }}
QPushButton#side:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton#update {{ text-align: left; padding: 9px 12px; border: 1px solid {ACCENT}; border-radius: 9px;
                      margin: 2px 10px 8px 10px; background: {ACCENT_DIM}; color: white; font-size: 10pt;
                      font-weight: 700; }}
QPushButton#update:hover {{ background: {ACCENT}; color: #0d1020; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {PANEL_2}; border-radius: 9px; }}
QCalendarWidget QToolButton {{ background: transparent; border: none; padding: 6px 10px; font-weight: 700; }}
QCalendarWidget QToolButton:hover {{ background: {ACCENT_DIM}; border-radius: 6px; }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
QCalendarWidget QAbstractItemView {{ background: {PANEL}; border: none; outline: 0; padding: 4px;
    alternate-background-color: {PANEL}; selection-background-color: {ACCENT}; selection-color: #0d1020; }}
QCalendarWidget QAbstractItemView:disabled {{ color: #5d6276; }}
QLabel#title {{ font-size: 22pt; font-weight: 800; }}
QLabel#subtitle, QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ font-size: 12.5pt; font-weight: 700; }}
QLabel#big {{ font-size: 30pt; font-weight: 800; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 16px; }}
QPushButton:hover {{ background: #2e3244; border-color: #444a63; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:disabled {{ color: #5d6276; background: {PANEL}; border-color: {PANEL_2}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; font-weight: 700; color: #0d1020; padding: 10px 22px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {ACCENT_DIM}; color: #8f9bc4; }}
QPushButton#danger {{ color: {BAD}; }}
QPushButton#danger:hover {{ border-color: {BAD}; }}
QTreeWidget, QListWidget, QTableWidget, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QLineEdit {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 9px; padding: 4px;
    selection-background-color: {ACCENT_DIM}; selection-color: white; }}
QComboBox, QSpinBox, QLineEdit {{ padding: 6px 10px; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {BORDER}; outline: none;
    selection-background-color: {ACCENT_DIM}; }}
QTreeWidget::item, QListWidget::item {{ padding: 6px 4px; border-radius: 6px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {PANEL_2}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {ACCENT_DIM}; color: white; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 7px; font-weight: 600; }}
QTableWidget {{ gridline-color: {BORDER}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#kpi {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QLabel#kpiValue {{ font-size: 21pt; font-weight: 800; color: {ACCENT_HOVER}; }}
QFrame#choice {{ background: {PANEL}; border: 2px solid {BORDER}; border-radius: 12px; }}
QFrame#choice:hover {{ border-color: {ACCENT}; background: {PANEL_2}; }}
QFrame#choice[state="good"] {{ border-color: {GOOD}; background: #173527; }}
QFrame#choice[state="bad"] {{ border-color: {BAD}; background: #3a1c22; }}
QFrame#choice[state="off"] {{ border-color: {BORDER}; background: {PANEL}; }}
QFrame#choice QLabel {{ background: transparent; border: none; }}
QLabel#choiceKey {{ color: {MUTED}; font-weight: 700; }}
QFrame#action {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#action:hover, QFrame#action:focus {{ border-color: {ACCENT}; background: #2e3244; }}
QFrame#action[primary="true"] {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QFrame#action[primary="true"]:hover, QFrame#action[primary="true"]:focus {{ background: #34437c; }}
QFrame#action:disabled {{ background: {PANEL}; border-color: {PANEL_2}; }}
QFrame#action QLabel {{ background: transparent; border: none; }}
QLabel#actionTitle {{ font-size: 12.5pt; font-weight: 700; }}
QLabel#actionText {{ color: {MUTED}; font-size: 10pt; }}
QLabel#actionTitle:disabled, QLabel#actionText:disabled {{ color: #5d6276; }}
QFrame#drop {{ background: {PANEL}; border: 2px dashed #4a5070; border-radius: 14px; }}
QFrame#drop[active="true"] {{ border-color: {ACCENT}; background: {PANEL_2}; }}
QFrame#drop QLabel {{ background: transparent; border: none; }}
QFrame#note {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#note QLabel {{ background: transparent; border: none; }}
QLabel#step {{ font-size: 12pt; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QRadioButton, QCheckBox {{ spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator, QTreeWidget::indicator, QListWidget::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 2px solid #747b94; background: {SURFACE}; border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator:hover, QTreeWidget::indicator:hover, QListWidget::indicator:hover,
QRadioButton::indicator:hover {{ border-color: {ACCENT_HOVER}; }}
QCheckBox::indicator:checked, QTreeWidget::indicator:checked, QListWidget::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: none; }}
QTreeWidget::indicator:indeterminate {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{ width: 8px; height: 8px; background: white; border: 6px solid {ACCENT};
    border-radius: 10px; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ border-color: #454a5e; }}
QRadioButton:disabled {{ color: #5d6276; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a5070; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px; border-radius: 6px; }}
"""


def app_icon(size: int = 256):
    """Icône de l'application, dessinée ici pour ne dépendre d'aucun fichier : deux cartes superposées."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    u = size / 100
    p.setBrush(QColor(SURFACE))
    p.drawRoundedRect(QRectF(4 * u, 4 * u, 92 * u, 92 * u), 21 * u, 21 * u)
    p.setBrush(QColor(ACCENT_DIM))
    p.drawRoundedRect(QRectF(32 * u, 20 * u, 46 * u, 56 * u), 8 * u, 8 * u)
    p.setBrush(QColor(ACCENT))
    p.drawRoundedRect(QRectF(22 * u, 28 * u, 46 * u, 56 * u), 8 * u, 8 * u)
    p.setBrush(QColor(SURFACE))
    for y, w in ((42, 30), (53, 30), (64, 18)):
        p.drawRoundedRect(QRectF(30 * u, y * u, w * u, 5 * u), 2.5 * u, 2.5 * u)
    p.end()
    return QIcon(pix)
