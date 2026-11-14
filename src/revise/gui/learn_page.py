"""Page « Apprendre » : le cours sous forme de fiche, partie par partie, pour le lire
avant de se tester (révision ou QCM)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QListWidget, QPushButton, QSplitter, QVBoxLayout, QWidget

from revise.db import Card, Database, deck_label
from revise.gui.common import fill_scope_combo, muted, page_header, row
from revise.gui.review import markdown_view

NO_SECTION = "Sans titre de partie"


def card_markdown(c: Card) -> str:
    """Une carte présentée comme un point de cours : la notion, puis son contenu."""
    q, a = c.question.strip(), c.answer.strip()
    hole = next((h for h in ("[...]", "[…]") if h in q), None)
    if c.kind == "cloze" and hole and "\n" not in a:
        return q.replace(hole, f"**{a}**")  # phrase du cours, trou rempli
    return f"**{q}**\n\n{a}"


def sections_of(cards: list[Card], labels: dict[int, str], several_decks: bool) -> list[tuple[str, list[Card]]]:
    """Regroupe les cartes par partie, dans l'ordre du cours."""
    groups: dict[tuple[int, str], list[Card]] = {}
    for c in cards:
        groups.setdefault((c.deck_id, c.section or NO_SECTION), []).append(c)
    out = []
    for (deck_id, section), group in groups.items():
        name = f"{labels.get(deck_id, '')} — {section}" if several_decks else section
        out.append((name, group))
    return out


class LearnPage(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setObjectName("page")
        self.sections: list[tuple[str, list[Card]]] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(page_header("Apprendre", "Ton cours en fiche de révision : lis chaque partie, réponses "
                                               "visibles, avant de te tester en révision ou en QCM."))
        self.scope = QComboBox()
        self.scope.setMinimumWidth(420)
        self.scope.currentIndexChanged.connect(self._load)
        self.info = muted("")
        lay.addLayout(row(muted("Cours :"), self.scope, self.info, None))

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show)
        split.addWidget(self.list)
        frame = QFrame()
        frame.setObjectName("card")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(22, 16, 22, 16)
        self.view = markdown_view(12.5)
        fl.addWidget(self.view)
        split.addWidget(frame)
        split.setSizes([280, 720])
        split.setChildrenCollapsible(False)
        lay.addWidget(split, 1)

        self.prev_btn = QPushButton("← Partie précédente")
        self.prev_btn.clicked.connect(lambda: self.list.setCurrentRow(self.list.currentRow() - 1))
        self.next_btn = QPushButton("Partie suivante →")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(lambda: self.list.setCurrentRow(self.list.currentRow() + 1))
        self.position = muted("")
        lay.addLayout(row(self.prev_btn, self.position, None, self.next_btn))

    def refresh(self) -> None:
        fill_scope_combo(self.scope, self.db)
        self._load()

    def _load(self) -> None:
        deck_ids = list(self.scope.currentData() or [])
        cards = self.db.cards(deck_ids=deck_ids, include_suspended=False) if deck_ids else []
        labels = {d.id: deck_label(d) for d in self.db.decks()}
        self.sections = sections_of(cards, labels, len(deck_ids) > 1)
        self.list.blockSignals(True)
        self.list.clear()
        for name, group in self.sections:
            self.list.addItem(f"{name}  ({len(group)})")
        self.list.blockSignals(False)
        if not self.sections:
            self.info.setText("")
            self.view.setMarkdown("Aucun cours pour l'instant : importe un PDF dans l'onglet « Importer »."
                                  if self.scope.count() == 0 else "Ce cours n'a aucune carte.")
            self._update_nav()
            return
        self.info.setText(f"{len(cards)} notions · {len(self.sections)} parties")
        self.list.setCurrentRow(0)
        self._show(0)

    def _show(self, i: int) -> None:
        if 0 <= i < len(self.sections):
            name, group = self.sections[i]
            pages = sorted({c.page for c in group if c.page})
            where = f"*p. {pages[0]}*" if len(pages) == 1 else f"*p. {pages[0]} à {pages[-1]}*" if pages else ""
            body = "\n\n---\n\n".join(card_markdown(c) for c in group)
            self.view.setMarkdown(f"## {name}\n\n{where}\n\n{body}")
            self.view.verticalScrollBar().setValue(0)
        self._update_nav()

    def _update_nav(self) -> None:
        i, n = self.list.currentRow(), len(self.sections)
        self.prev_btn.setEnabled(i > 0)
        self.next_btn.setEnabled(0 <= i < n - 1)
        self.position.setText(f"Partie {i + 1} / {n}" if n and i >= 0 else "")
