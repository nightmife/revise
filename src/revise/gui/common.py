"""Petits utilitaires partagés par les pages."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

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


def fill_scope_combo(combo: QComboBox, db: Database) -> None:
    """Liste « tous les cours », puis chaque matière et ses cours. La donnée de chaque
    entrée est la liste des identifiants de cours concernés. La sélection est conservée."""
    previous = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    every = [d.id for d in db.decks()]
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


def cloze_question(question: str) -> str:
    """Met en évidence le trou d'une carte « texte à trous »."""
    return question.replace("[...]", "**[ … ]**").replace("[…]", "**[ … ]**")
