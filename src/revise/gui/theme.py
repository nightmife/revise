"""Thème sombre de l'application : couleurs, feuille de style, icônes dessinées (aucun fichier image)."""

SURFACE = "#0f1117"
PANEL = "#171a24"
PANEL_2 = "#202433"
BORDER = "#2b3046"
TEXT = "#eef0f7"
MUTED = "#939bb5"
FAINT = "#5c6380"       # texte désactivé
ACCENT = "#7b8cff"
ACCENT_HOVER = "#9aa7ff"
ACCENT_DIM = "#2a3168"
VIOLET = "#a984ff"      # seconde teinte des dégradés
GOOD = "#3ecf8e"
BAD = "#f0616d"
WARN = "#f5b84a"
INK = "#0d1020"         # texte posé sur la couleur d'accent

# Notes de révision : couleur + libellé + raccourci (jamais la couleur seule)
RATING_COLORS = {1: "#d9434e", 2: "#e0803f", 3: "#2f9e6b", 4: "#4f7df0"}
# Rampe séquentielle (une teinte, du faible au fort) sur fond sombre
HEAT = ["#202433", "#2c3f7a", "#3f5cc0", "#7b8cff", "#b9c3ff"]

GRADIENT = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT}, stop:1 {VIOLET})"
GRADIENT_HOVER = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT_HOVER}, stop:1 #bca0ff)"
HERO = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #283070, stop:0.6 #2c2a6b, stop:1 #3a2a70)"

QSS = f"""
* {{ font-size: 11pt; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#page, QStackedWidget, QScrollArea, QWidget#scrollBody {{ background: {SURFACE}; }}
QScrollArea {{ border: none; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QLabel#appname {{ font-size: 22pt; font-weight: 800; color: {ACCENT_HOVER}; padding: 22px 20px 0 20px; }}
QLabel#tagline {{ color: {MUTED}; padding: 0 20px 18px 20px; font-size: 9.5pt; }}
QPushButton#nav {{ text-align: left; padding: 11px 14px; border: none; border-radius: 11px; margin: 2px 10px;
                   background: transparent; color: {MUTED}; font-size: 11.5pt; font-weight: 500; }}
QPushButton#nav:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {ACCENT_DIM}; color: white; font-weight: 700; }}
QPushButton#nav:disabled {{ color: {FAINT}; background: transparent; }}
QPushButton#side {{ text-align: left; padding: 7px 16px; border: none; border-radius: 9px; margin: 1px 10px;
                    background: transparent; color: {MUTED}; font-size: 10pt; }}
QPushButton#side:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton#update {{ text-align: left; padding: 9px 12px; border: 1px solid {ACCENT}; border-radius: 11px;
                      margin: 2px 10px 8px 10px; background: {ACCENT_DIM}; color: white; font-size: 10pt;
                      font-weight: 700; }}
QPushButton#update:hover {{ background: {ACCENT}; color: {INK}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {PANEL_2}; border-radius: 9px; }}
QCalendarWidget QToolButton {{ background: transparent; border: none; padding: 6px 10px; font-weight: 700; }}
QCalendarWidget QToolButton:hover {{ background: {ACCENT_DIM}; border-radius: 6px; }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
QCalendarWidget QAbstractItemView {{ background: {PANEL}; border: none; outline: 0; padding: 4px;
    alternate-background-color: {PANEL}; selection-background-color: {ACCENT}; selection-color: {INK}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {FAINT}; }}
QLabel#title {{ font-size: 23pt; font-weight: 800; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 11.5pt; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ font-size: 13pt; font-weight: 700; }}
QLabel#big {{ font-size: 30pt; font-weight: 800; }}
QLabel#stepNumber, QFrame#tile QLabel#stepNumber, QFrame#note QLabel#stepNumber {{
    background: {ACCENT_DIM}; color: {ACCENT_HOVER}; border-radius: 13px; font-weight: 800;
    min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ background: #2a2f43; border-color: #474d6b; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {FAINT}; background: {PANEL}; border-color: {PANEL_2}; }}
QPushButton#primary {{ background: {GRADIENT}; border: none; font-weight: 700; color: {INK}; padding: 10px 22px; }}
QPushButton#primary:hover {{ background: {GRADIENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {ACCENT_DIM}; color: #8f9bc4; }}
QPushButton#hero {{ background: white; border: none; border-radius: 14px; color: #1a1d3a; font-size: 13.5pt;
                    font-weight: 800; padding: 14px 30px; }}
QPushButton#hero:hover {{ background: #e3e7ff; }}
QPushButton#hero:pressed {{ background: #c9d0ff; }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT_HOVER}; padding: 4px 2px; font-weight: 600; }}
QPushButton#link:hover {{ color: white; }}
QPushButton#danger {{ color: {BAD}; }}
QPushButton#danger:hover {{ border-color: {BAD}; }}
QTreeWidget, QListWidget, QTableWidget, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QLineEdit {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; padding: 4px;
    selection-background-color: {ACCENT_DIM}; selection-color: white; }}
QComboBox, QSpinBox, QLineEdit {{ padding: 7px 10px; border-radius: 10px; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {BORDER}; outline: none;
    selection-background-color: {ACCENT_DIM}; }}
QTreeWidget::item, QListWidget::item {{ padding: 8px 4px; border-radius: 7px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {PANEL_2}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {ACCENT_DIM}; color: white; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 8px 7px; font-weight: 600; font-size: 10pt; }}
QTableWidget {{ gridline-color: {BORDER}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 18px; }}
QFrame#kpi, QFrame#tile {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#kpi QLabel, QFrame#tile QLabel {{ background: transparent; border: none; }}
QLabel#kpiValue {{ font-size: 21pt; font-weight: 800; color: {ACCENT_HOVER}; }}
QLabel#tileValue {{ font-size: 20pt; font-weight: 800; }}
QLabel#tileLabel {{ color: {MUTED}; font-size: 10pt; font-weight: 600; }}
QFrame#hero {{ background: {HERO}; border: 1px solid #454c9c; border-radius: 22px; }}
QFrame#hero QLabel {{ background: transparent; border: none; }}
QLabel#heroTitle {{ font-size: 21pt; font-weight: 800; color: white; }}
QLabel#heroText {{ font-size: 12pt; color: #c9cffa; }}
QLabel#hello {{ font-size: 25pt; font-weight: 800; }}
QFrame#choice {{ background: {PANEL}; border: 2px solid {BORDER}; border-radius: 14px; }}
QFrame#choice:hover {{ border-color: {ACCENT}; background: {PANEL_2}; }}
QFrame#choice[state="good"] {{ border-color: {GOOD}; background: #173527; }}
QFrame#choice[state="bad"] {{ border-color: {BAD}; background: #3a1c22; }}
QFrame#choice[state="off"] {{ border-color: {BORDER}; background: {PANEL}; }}
QFrame#choice QLabel {{ background: transparent; border: none; }}
QLabel#choiceKey {{ color: {MUTED}; font-weight: 700; }}
QFrame#action {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#action:hover, QFrame#action:focus {{ border-color: {ACCENT}; background: {PANEL_2}; }}
QFrame#action[primary="true"] {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QFrame#action[primary="true"]:hover, QFrame#action[primary="true"]:focus {{ background: #34407f; }}
QFrame#action:disabled {{ background: {SURFACE}; border-color: {PANEL_2}; }}
QFrame#action QLabel {{ background: transparent; border: none; }}
QLabel#actionTitle {{ font-size: 12.5pt; font-weight: 700; }}
QLabel#actionText {{ color: {MUTED}; font-size: 10pt; }}
QLabel#actionTitle:disabled, QLabel#actionText:disabled {{ color: {FAINT}; }}
QFrame#drop {{ background: {PANEL}; border: 2px dashed #4a5078; border-radius: 16px; }}
QFrame#drop[active="true"] {{ border-color: {ACCENT}; background: {PANEL_2}; }}
QFrame#drop QLabel {{ background: transparent; border: none; }}
QFrame#note {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#note QLabel {{ background: transparent; border: none; }}
QLabel#step {{ font-size: 12pt; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {GRADIENT}; border-radius: 4px; }}
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
QRadioButton:disabled {{ color: {FAINT}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a5070; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 8px; border-radius: 7px; }}
"""


def nav_icon(name: str, size: int = 20):
    """Petite icône au trait du menu, dessinée ici (grise au repos, blanche quand la page est ouverte)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

    def draw(color: str) -> QPixmap:
        scale = 3  # dessiné en grand puis réduit par Qt : traits nets sur tous les écrans
        pix = QPixmap(size * scale, size * scale)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size * scale / 20, size * scale / 20)  # tout est décrit dans un carré de 20 × 20
        pen = QPen(QColor(color), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if name == "home":
            path = QPainterPath(QPointF(3, 9.5))
            path.lineTo(10, 3.5)
            path.lineTo(17, 9.5)
            p.drawPath(path)
            p.drawRoundedRect(QRectF(5, 9, 10, 8), 1.5, 1.5)
        elif name == "courses":
            for y in (4, 8.5, 13):
                p.drawRoundedRect(QRectF(3.5, y, 13, 3.2), 1.4, 1.4)
        elif name == "add":
            p.drawEllipse(QPointF(10, 10), 7, 7)
            p.drawLine(QPointF(10, 6.8), QPointF(10, 13.2))
            p.drawLine(QPointF(6.8, 10), QPointF(13.2, 10))
        elif name == "learn":
            p.drawRoundedRect(QRectF(4.5, 3, 11, 14), 1.8, 1.8)
            for y in (7, 10, 13):
                p.drawLine(QPointF(7.2, y), QPointF(12.8, y))
        elif name == "quiz":
            for y in (5.5, 10, 14.5):
                p.drawEllipse(QPointF(5, y), 1.5, 1.5)
                p.drawLine(QPointF(9, y), QPointF(16.5, y))
        elif name == "stats":
            for x, top in ((5, 11), (10, 6), (15, 9)):
                p.drawLine(QPointF(x, 16), QPointF(x, top))
        p.end()
        return pix

    icon = QIcon()
    icon.addPixmap(draw(MUTED), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(draw("#ffffff"), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(draw(FAINT), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon


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
