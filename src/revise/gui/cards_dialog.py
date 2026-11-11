"""Fenêtre « cartes d'un cours » : parcourir, modifier, supprimer, ajouter."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget, QLabel,
                               QLineEdit)

from revise.db import Database, deck_label
from revise.gui.common import muted, row
from revise.gui.review import KIND_LABEL
from revise.models import KINDS, CardDraft

ID_ROLE = Qt.ItemDataRole.UserRole


class CardsDialog(QDialog):
    def __init__(self, db: Database, deck_id: int, parent=None):
        super().__init__(parent)
        self.db, self.deck_id = db, deck_id
        deck = db.deck(deck_id)
        self.setWindowTitle(f"Cartes — {deck_label(deck)}")
        self.resize(1050, 680)
        lay = QVBoxLayout(self)

        self.name = QLineEdit(deck.title)
        self.subject = QLineEdit(deck.subject)
        save_meta = QPushButton("Renommer")
        save_meta.clicked.connect(self._save_meta)
        lay.addLayout(row(muted("Titre :"), self.name, muted("Matière :"), self.subject, save_meta))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher dans les cartes…")
        self.search.textChanged.connect(self._filter)

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._load)
        ll.addWidget(self.list)
        add = QPushButton("Nouvelle carte")
        add.clicked.connect(self._new)
        ll.addWidget(add)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(KIND_LABEL[k], k)
        self.page = QSpinBox()
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("—")
        self.page.setPrefix("page ")
        self.state = muted("")
        rl.addLayout(row(self.kind, self.page, None, self.state))
        rl.addWidget(QLabel("Question"))
        self.q = QPlainTextEdit()
        rl.addWidget(self.q, 1)
        rl.addWidget(QLabel("Réponse"))
        self.a = QPlainTextEdit()
        rl.addWidget(self.a, 1)
        rl.addWidget(muted("Markdown accepté : **gras**, `code`, listes, blocs ``` pour le code."))
        self.save_btn = QPushButton("Enregistrer")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        self.suspend_btn = QPushButton("Suspendre")
        self.suspend_btn.clicked.connect(self._toggle_suspend)
        self.del_btn = QPushButton("Supprimer la carte")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self._delete)
        rl.addLayout(row(self.save_btn, self.suspend_btn, None, self.del_btn))
        split.addWidget(right)
        split.setSizes([380, 670])
        lay.addWidget(split, 1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        lay.addLayout(row(None, close))
        self._editing_new = False
        self.reload()

    def reload(self, select: int | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.db.cards(deck_id=self.deck_id):
            first = c.question.strip().splitlines()[0] if c.question.strip() else "(vide)"
            tag = " [suspendue]" if c.suspended else ""
            it = QListWidgetItem(f"p.{c.page or '?'}  {first[:80]}{tag}")
            it.setData(ID_ROLE, c.id)
            it.setToolTip(c.question)
            if c.suspended:
                it.setForeground(Qt.GlobalColor.gray)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._filter(self.search.text())
        for i in range(self.list.count()):
            if select is None or self.list.item(i).data(ID_ROLE) == select:
                self.list.setCurrentRow(i)
                break
        if self.list.count() == 0:
            self._new()

    def _filter(self, text: str) -> None:
        t = text.lower().strip()
        for i in range(self.list.count()):
            it = self.list.item(i)
            card = self.db.card(it.data(ID_ROLE))
            it.setHidden(bool(t) and card is not None and t not in (card.question + " " + card.answer).lower())

    def _current_id(self) -> int | None:
        it = self.list.currentItem()
        return None if (it is None or self._editing_new) else int(it.data(ID_ROLE))

    def _load(self, item, _prev=None) -> None:
        self._editing_new = False
        if item is None:
            return
        c = self.db.card(int(item.data(ID_ROLE)))
        if not c:
            return
        self.kind.setCurrentIndex(KINDS.index(c.kind) if c.kind in KINDS else 0)
        self.page.setValue(c.page or 0)
        self.q.setPlainText(c.question)
        self.a.setPlainText(c.answer)
        self.state.setText("suspendue" if c.suspended else ("jamais vue" if c.is_new else "déjà révisée"))
        self.suspend_btn.setText("Réactiver" if c.suspended else "Suspendre")
        for b in (self.suspend_btn, self.del_btn):
            b.setEnabled(True)

    def _new(self) -> None:
        self._editing_new = True
        self.list.clearSelection()
        self.q.clear()
        self.a.clear()
        self.page.setValue(0)
        self.state.setText("nouvelle carte")
        for b in (self.suspend_btn, self.del_btn):
            b.setEnabled(False)
        self.q.setFocus()

    def _save(self) -> None:
        q, a = self.q.toPlainText().strip(), self.a.toPlainText().strip()
        if not q or not a:
            QMessageBox.warning(self, "Carte incomplète", "Il faut une question et une réponse.")
            return
        kind, page = self.kind.currentData(), self.page.value() or None
        cid = self._current_id()
        if cid is None:
            cid = self.db.add_card(self.deck_id, CardDraft(kind, q, a, page))
        else:
            self.db.update_card_content(cid, kind, q, a, page)
        self.reload(select=cid)

    def _toggle_suspend(self) -> None:
        cid = self._current_id()
        if cid is None:
            return
        c = self.db.card(cid)
        self.db.set_suspended(cid, not c.suspended)
        self.reload(select=cid)

    def _delete(self) -> None:
        cid = self._current_id()
        if cid is None:
            return
        if QMessageBox.question(self, "Supprimer", "Supprimer cette carte et son historique ?") \
                == QMessageBox.StandardButton.Yes:
            self.db.delete_card(cid)
            self.reload()

    def _save_meta(self) -> None:
        if self.name.text().strip() and self.subject.text().strip():
            self.db.rename_deck(self.deck_id, self.name.text().strip(), self.subject.text().strip())
            self.setWindowTitle(f"Cartes — {self.name.text().strip()}")
