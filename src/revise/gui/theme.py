"""Thème sombre de l'application."""

SURFACE = "#1a1a19"
PANEL = "#232321"
PANEL_2 = "#2b2b29"
BORDER = "#3a3936"
TEXT = "#f0efec"
MUTED = "#a8a69e"
ACCENT = "#3987e5"
ACCENT_HOVER = "#5598e7"

# Notes de révision : couleur + libellé + raccourci (jamais la couleur seule)
RATING_COLORS = {1: "#d03b3b", 2: "#ec835a", 3: "#0ca30c", 4: "#3987e5"}
# Rampe séquentielle bleue (une teinte, du faible au fort) sur fond sombre
HEAT = ["#2f2e2b", "#184f95", "#256abf", "#3987e5", "#86b6ef"]

QSS = f"""
* {{ font-size: 11pt; color: {TEXT}; }}
QMainWindow, QWidget#page, QStackedWidget {{ background: {SURFACE}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QLabel#appname {{ font-size: 18pt; font-weight: 700; padding: 18px 14px 4px 14px; }}
QLabel#tagline {{ color: {MUTED}; padding: 0 14px 16px 14px; font-size: 9.5pt; }}
QPushButton#nav {{ text-align: left; padding: 10px 18px; border: none; border-radius: 6px; margin: 2px 8px;
                   background: transparent; color: {MUTED}; font-size: 11.5pt; }}
QPushButton#nav:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {PANEL_2}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}
QLabel#title {{ font-size: 20pt; font-weight: 700; }}
QLabel#subtitle, QLabel.muted {{ color: {MUTED}; }}
QLabel#muted {{ color: {MUTED}; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 8px 14px; }}
QPushButton:hover {{ background: #34332f; }}
QPushButton:disabled {{ color: #6b6a65; background: {PANEL}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; font-weight: 600; color: white; padding: 10px 20px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #2b4a70; color: #9fb6d1; }}
QPushButton#danger {{ color: #ff8f8f; }}
QTreeWidget, QListWidget, QTableWidget, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QLineEdit {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; selection-background-color: #2b4a70; }}
QTreeWidget::item, QListWidget::item {{ padding: 5px 2px; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 6px; font-weight: 600; }}
QTableWidget {{ gridline-color: {BORDER}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#kpi {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#kpiValue {{ font-size: 20pt; font-weight: 700; }}
QProgressBar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 5px; height: 10px; text-align: center; }}
QProgressBar::chunk {{ background: #0ca30c; border-radius: 5px; }}
QRadioButton, QCheckBox {{ spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator, QTreeWidget::indicator, QListWidget::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 2px solid #8a8880; background: {SURFACE}; border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator:hover, QTreeWidget::indicator:hover, QListWidget::indicator:hover,
QRadioButton::indicator:hover {{ border-color: {ACCENT_HOVER}; }}
QCheckBox::indicator:checked, QTreeWidget::indicator:checked, QListWidget::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: none; }}
QTreeWidget::indicator:indeterminate {{ background: #2b4a70; border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 4px solid {SURFACE}; outline: none;
    border-radius: 10px; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ border-color: #4a4945; }}
QScrollBar:vertical {{ background: {SURFACE}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""
