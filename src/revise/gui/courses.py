"""Page « Mes cours » : sélection des CM et lancement des révisions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QHeaderView, QMessageBox, QPushButton, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from revise.db import Database, deck_label, parse_iso, utcnow
from revise.gui.common import muted, page_header, row
from revise.scheduler import KNOWN_RETRIEVABILITY, load_state, make_scheduler

DECK_ROLE = Qt.ItemDataRole.UserRole


class CoursesPage(QWidget):
    start_review = Signal(list, bool, bool, int)  # paquets, examen, inclure les sues, nouvelles/jour
    edit_cards = Signal(int)
    go_import = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.setObjectName("page")
        self.db = db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(page_header("Mes cours", "Coche un ou plusieurs CM, puis choisis comment réviser."))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Cours", "Cartes", "Nouv.", "Dues", "Sues"])
        for c, tip in enumerate(["", "Nombre de cartes", "Jamais vues", "À réviser aujourd'hui (planning)",
                                 "Sues : notées Bien/Facile et encore fraîches en mémoire"]):
            if tip:
                self.tree.headerItem().setToolTip(c, tip)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.tree.setColumnWidth(c, 58)
        hdr.setMinimumSectionSize(40)
        self.tree.itemChanged.connect(self._on_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        lay.addWidget(self.tree, 1)

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addWidget(muted("Aucun cours pour l'instant. Commence par importer tes PDF de CM."))
        b = QPushButton("Importer des PDF")
        b.setObjectName("primary")
        b.clicked.connect(self.go_import.emit)
        el.addLayout(row(b, None))
        lay.addWidget(self.empty)

        all_btn = QPushButton("Tout cocher")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("Tout décocher")
        none_btn.clicked.connect(lambda: self._set_all(False))
        self.selection_label = muted("")
        self.selection_label.setWordWrap(False)
        lay.addLayout(row(all_btn, none_btn, None))
        lay.addWidget(self.selection_label)

        self.review_btn = QPushButton("Réviser")
        self.review_btn.setObjectName("primary")
        self.review_btn.setMinimumWidth(150)
        self.review_btn.setToolTip("Révision au bon moment (répétition espacée) : cartes dues + nouvelles du jour.")
        self.review_btn.clicked.connect(lambda: self._start(False))
        self.exam_btn = QPushButton("Mode examen")
        self.exam_btn.setObjectName("primary")
        self.exam_btn.setMinimumWidth(150)
        self.exam_btn.setToolTip("Bachotage : toutes les cartes des cours cochés tout de suite,\n"
                                 "jusqu'à les avoir toutes sues.")
        self.exam_btn.clicked.connect(lambda: self._start(True))
        self.include_known = QCheckBox("Revoir aussi les sues")
        self.include_known.setToolTip("En mode examen, les cartes notées Bien/Facile récemment sont sautées.")
        self.new_per_day = QSpinBox()
        self.new_per_day.setRange(0, 999)
        self.new_per_day.setValue(20)
        self.new_per_day.setSuffix(" nouv./jour")
        self.new_per_day.setToolTip("Nombre maximum de nouvelles cartes par jour (révision normale)")
        lay.addLayout(row(self.review_btn, self.new_per_day, None))
        lay.addLayout(row(self.exam_btn, self.include_known, None))

        self.edit_btn = QPushButton("Voir les cartes")
        self.edit_btn.clicked.connect(self._edit)
        self.delete_btn = QPushButton("Supprimer")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._delete)
        lay.addLayout(row(self.edit_btn, self.delete_btn, None))
        self.refresh()

    # ------------------------------------------------------------------ données
    def refresh(self) -> None:
        checked = set(self.selected_decks())
        first_load = self.tree.topLevelItemCount() == 0
        self.tree.blockSignals(True)
        self.tree.clear()
        now = utcnow()
        last = self.db.last_ratings()
        sch = make_scheduler()
        for subject in self.db.subjects():
            parent = QTreeWidgetItem([subject])
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            totals = [0, 0, 0, 0]
            for d in self.db.decks(subject):
                cards = self.db.cards(deck_id=d.id, include_suspended=False)
                new = sum(1 for c in cards if c.fsrs is None)
                due = sum(1 for c in cards if c.fsrs is not None and parse_iso(c.due) <= now)
                known = sum(1 for c in cards if c.fsrs is not None and last.get(c.id, 0) >= 3
                            and sch.get_card_retrievability(load_state(c), now) >= KNOWN_RETRIEVABILITY)
                vals = [len(cards), new, due, known]
                totals = [a + b for a, b in zip(totals, vals)]
                item = QTreeWidgetItem([deck_label(d)] + [str(v) for v in vals])
                item.setData(0, DECK_ROLE, d.id)
                item.setToolTip(0, f"{d.title}\n{d.source or ''}\nImporté le {d.created[:10]} ({d.engine})")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if d.id in checked else Qt.CheckState.Unchecked)
                for c in range(1, 5):
                    item.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                parent.addChild(item)
            for c, v in enumerate(totals, start=1):
                parent.setText(c, str(v))
                parent.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)
        self.tree.blockSignals(False)
        has = self.tree.topLevelItemCount() > 0
        self.tree.setVisible(has)
        self.empty.setVisible(not has)
        if first_load and has and not checked:
            pass  # rien de coché par défaut : l'étudiant choisit
        self._update_buttons()

    def selected_decks(self) -> list[int]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            p = self.tree.topLevelItem(i)
            for j in range(p.childCount()):
                ch = p.child(j)
                if ch.checkState(0) == Qt.CheckState.Checked:
                    out.append(int(ch.data(0, DECK_ROLE)))
        return out

    # -------------------------------------------------------------- interaction
    def _set_all(self, value: bool) -> None:
        state = Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)
        self._update_buttons()

    def _on_changed(self, item, column) -> None:
        self._update_buttons()

    def _on_double_click(self, item, column) -> None:
        deck = item.data(0, DECK_ROLE)
        if deck is not None:
            item.setCheckState(0, Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)

    def _update_buttons(self) -> None:
        sel = self.selected_decks()
        n_cards = sum(len(self.db.cards(deck_id=d, include_suspended=False)) for d in sel)
        self.selection_label.setText(f"{len(sel)} cours coché(s), {n_cards} cartes" if sel
                                     else "Coche les CM à réviser")
        for b in (self.review_btn, self.exam_btn):
            b.setEnabled(bool(sel))
        self.edit_btn.setEnabled(len(sel) == 1)
        self.edit_btn.setToolTip("" if len(sel) == 1 else "Coche un seul cours pour voir ses cartes.")
        self.delete_btn.setEnabled(bool(sel))

    def _start(self, exam: bool) -> None:
        sel = self.selected_decks()
        if sel:
            self.start_review.emit(sel, exam, self.include_known.isChecked(), self.new_per_day.value())

    def _edit(self) -> None:
        sel = self.selected_decks()
        if len(sel) == 1:
            self.edit_cards.emit(sel[0])

    def _delete(self) -> None:
        sel = self.selected_decks()
        if not sel:
            return
        names = "\n".join(f"• {deck_label(self.db.deck(d))}" for d in sel)
        if QMessageBox.question(self, "Supprimer", f"Supprimer ces cours, leurs cartes et leur historique ?\n\n{names}") \
                != QMessageBox.StandardButton.Yes:
            return
        for d in sel:
            self.db.delete_deck(d)
        self.refresh()
