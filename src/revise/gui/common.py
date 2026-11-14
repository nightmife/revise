"""Petits utilitaires partagés par les pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout,
                               QWidget)

from revise.db import Database, deck_label


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
