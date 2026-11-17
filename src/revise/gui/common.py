"""Petits utilitaires partagés par les pages."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLayout, QMessageBox,
                               QVBoxLayout, QWidget)

from revise.db import Database, deck_label


class Background(QObject):
    """Travail dans un fil Python, résultats livrés dans le fil de l'interface.

    Le fil ne touche jamais à Qt : il dépose ses messages dans une file, qu'une minuterie de l'interface
    vide. (Émettre un signal Qt depuis un fil Python fait créer à Qt des objets pour ce fil, détruits dans
    le désordre à la fermeture : plantage à la sortie sur certains systèmes.)"""

    def __init__(self, parent: QObject, on_message: Callable[[object], None]):
        super().__init__(parent)
        self.on_message = on_message
        self.messages: queue.SimpleQueue = queue.SimpleQueue()
        self.running = 0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.drain)

    def start(self, work: Callable[[Callable[[object], None]], None]) -> None:
        """Lance `work(post)` ; chaque `post(message)` arrive à `on_message` dans le fil de l'interface."""
        def run() -> None:
            try:
                work(self.messages.put)
            finally:
                self.messages.put(Background)  # marque de fin
        self.running += 1
        self.timer.start()
        threading.Thread(target=run, name="revise-arriere-plan", daemon=True).start()

    def drain(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                return
            if message is Background:
                self.running -= 1
                if self.running <= 0:
                    self.timer.stop()
            else:
                self.on_message(message)


def page_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 8)
    t = QLabel(title)
    t.setObjectName("title")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("subtitle")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def row(*widgets, stretch_at: int | None = None, spacing: int = 8) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


class FlowLayout(QLayout):
    """Rangée de boutons qui passe à la ligne quand la fenêtre est trop étroite (au lieu de déborder)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        lines: list[list] = [[]]
        x = rect.x()
        for item in self._items:
            if item.isEmpty():  # widget caché
                continue
            width = item.sizeHint().width()
            if lines[-1] and x + width > rect.right() + 1:
                lines.append([])
                x = rect.x()
            lines[-1].append(item)
            x += width + self._spacing
        y = rect.y()
        for line in filter(None, lines):
            height = max(i.sizeHint().height() for i in line)
            x = rect.x()
            for item in line:
                hint = item.sizeHint()
                if move:  # centré verticalement sur la ligne
                    item.setGeometry(QRect(QPoint(x, y + (height - hint.height()) // 2), hint))
                x += hint.width() + self._spacing
            y += height + self._spacing
        return max(0, y - self._spacing - rect.y())


def flow(*widgets: QWidget, spacing: int = 8) -> QWidget:
    """Widgets les uns après les autres, sur plusieurs lignes si la place manque."""
    box = QWidget()
    lay = FlowLayout(box, spacing)
    for w in widgets:
        lay.addWidget(w)
    return box


def step_header(number: int, title: str) -> QHBoxLayout:
    """Titre d'une étape numérotée : pastille « 1 » puis ce qu'il y a à faire."""
    badge = QLabel(str(number))
    badge.setObjectName("stepNumber")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label = QLabel(title)
    label.setObjectName("section")
    return row(badge, label, None, spacing=10)


def muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


class ActionCard(QFrame):
    """Gros bouton à deux lignes : ce qu'il fait, puis une phrase qui l'explique."""

    clicked = Signal()

    def __init__(self, title: str, text: str, primary: bool = False):
        super().__init__()
        self.setObjectName("action")
        self.setProperty("primary", "true" if primary else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(3)
        self.title = QLabel(title)
        self.title.setObjectName("actionTitle")
        self.text = QLabel(text)
        self.text.setObjectName("actionText")
        self.text.setWordWrap(True)
        for lab in (self.title, self.text):
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(lab)
        lay.addStretch(1)

    def click(self) -> None:
        if self.isEnabled():
            self.clicked.emit()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.click()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.click()
        else:
            super().keyPressEvent(e)


def fill_scope_combo(combo: QComboBox, db: Database, custom: list[int] | None = None) -> None:
    """Liste « tous les cours », puis chaque matière et ses cours. La donnée de chaque
    entrée est la liste des identifiants de cours concernés. La sélection est conservée.
    `custom` : cours cochés dans « Mes cours », proposés en tête s'ils ne forment pas déjà une entrée."""
    previous = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    every = [d.id for d in db.decks()]
    custom = [d for d in custom or [] if d in every]
    groups = [every] + [[d.id for d in db.decks(s)] for s in db.subjects()] + [[d] for d in every]
    if custom and custom not in groups:
        combo.addItem(f"Ma sélection ({len(custom)} cours)", custom)
    if every:
        combo.addItem("Tous les cours", every)
    for subject in db.subjects():
        decks = db.decks(subject)
        combo.addItem(f"{subject} — toute la matière", [d.id for d in decks])
        for d in decks:
            combo.addItem(f"    {deck_label(d)}", [d.id])
    if previous is not None:
        i = combo.findData(previous)
        if i >= 0:
            combo.setCurrentIndex(i)
    combo.blockSignals(False)


def select_scope(combo: QComboBox, deck_ids: list[int]) -> None:
    i = combo.findData(deck_ids)
    if i >= 0:
        combo.setCurrentIndex(i)


def cloze_question(question: str) -> str:
    """Met en évidence le trou d'une carte « texte à trous »."""
    return question.replace("[...]", "**[ … ]**").replace("[…]", "**[ … ]**")


def confirm(parent: QWidget, title: str, text: str, yes: str = "Oui", no: str = "Annuler") -> bool:
    """Question à deux boutons, en français quel que soit le système."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    ok = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(box.addButton(no, QMessageBox.ButtonRole.RejectRole))
    box.exec()
    return box.clickedButton() is ok


def save_cancel_buttons() -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Save).setText("Enregistrer")
    box.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
    return box


class Eta:
    """Temps restant estimé d'après l'avancement (0 à 1) et le temps déjà passé."""

    def __init__(self, clock: Callable[[], float] | None = None):
        import time
        self.clock = clock or time.monotonic
        self.start = self.clock()

    def restart(self) -> None:
        self.start = self.clock()

    def text(self, fraction: float) -> str:
        elapsed = self.clock() - self.start
        if fraction >= 1:
            return ""
        if fraction < 0.03 or elapsed < 5:
            return "calcul du temps restant…"
        left = elapsed / fraction * (1 - fraction)
        if left < 60:
            return "moins d'une minute restante"
        minutes = round(left / 60)
        if minutes < 60:
            return f"environ {minutes} min restante{'s' if minutes > 1 else ''}"
        return f"environ {minutes // 60} h {minutes % 60:02d} restantes"
