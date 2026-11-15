"""Page « Mes cours » : sélection des CM et lancement des révisions."""

from __future__ import annotations

import re
from pathlib import Path

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (QCalendarWidget, QCheckBox, QDialog, QFileDialog, QFrame, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from revise import exam, share
from revise.db import Database, deck_label, parse_iso, utcnow
from revise.gui import theme
from revise.gui.common import ActionCard, confirm, muted, page_header, row
from revise.models import ReviseError
from revise.scheduler import KNOWN_RETRIEVABILITY, load_state, make_scheduler, start_of_day

DECK_ROLE = Qt.ItemDataRole.UserRole
SHARE_FILTER = "Cours pour revise (*.revise)"
ANKI_FILTER = "Cartes pour Anki (*.txt)"


class ExamDialog(QDialog):
    """Choix de la date d'examen des cours cochés."""

    def __init__(self, current: str | None, count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Date d'examen")
        self.chosen: str | None = current
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(muted(f"Quel jour est l'examen de {'ce cours' if count == 1 else f'ces {count} cours'} ? "
                            "« Réviser » te donnera chaque jour assez de nouvelles cartes pour avoir tout vu "
                            "à temps, en gardant la veille pour tout revoir."))
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setMinimumSize(420, 290)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setMinimumDate(QDate.currentDate())
        plain = QTextCharFormat()  # pas de week-ends en rouge : illisible sur le fond sombre
        plain.setForeground(QColor(theme.TEXT))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.calendar.setWeekdayTextFormat(day, plain)
        header = QTextCharFormat()
        header.setForeground(QColor(theme.MUTED))
        header.setBackground(QColor(theme.PANEL))
        self.calendar.setHeaderTextFormat(header)
        start = exam.parse_date(current)
        if start is None or start < date.today():
            start = date.today() + timedelta(days=14)
        self.calendar.setSelectedDate(QDate(start.year, start.month, start.day))
        lay.addWidget(self.calendar)
        remove = QPushButton("Enlever la date")
        remove.setEnabled(current is not None)
        remove.clicked.connect(lambda: self._finish(None))
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Enregistrer")
        save.setObjectName("primary")
        save.clicked.connect(lambda: self._finish(self.calendar.selectedDate().toString(Qt.DateFormat.ISODate)))
        lay.addLayout(row(remove, None, cancel, save))

    def _finish(self, value: str | None) -> None:
        self.chosen = value
        self.accept()


class CoursesPage(QWidget):
    start_review = Signal(list, bool, bool, int)  # paquets, examen, inclure les connues, nouvelles/jour
    open_learn = Signal(list)
    open_quiz = Signal(list)
    edit_cards = Signal(int)
    go_import = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.setObjectName("page")
        self.db = db
        self._pressed: tuple[QTreeWidgetItem, Qt.CheckState] | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(page_header("Mes cours", "Coche les cours que tu veux travailler, puis choisis une activité."))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["Cours", "Cartes", "Nouvelles", "À revoir", "Connues", "Examen"])
        for c, tip in enumerate(["", "Nombre de questions du cours", "Cartes que tu n'as encore jamais vues",
                                 "Cartes à revoir aujourd'hui pour ne pas les oublier",
                                 "Cartes que tu as su récemment",
                                 "Jours avant l'examen, et part des cartes que tu sais déjà"]):
            if tip:
                self.tree.headerItem().setToolTip(c, tip)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.tree.setColumnWidth(c, 92)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(5, 170)
        hdr.setMinimumSectionSize(40)
        self.tree.itemChanged.connect(self._on_changed)
        self.tree.itemPressed.connect(self._on_pressed)
        self.tree.itemClicked.connect(self._on_clicked)
        lay.addWidget(self.tree, 1)

        self.empty = QFrame()
        self.empty.setObjectName("note")
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(24, 20, 24, 20)
        el.setSpacing(8)
        t = QLabel("Bienvenue ! Trois étapes pour réviser :")
        t.setObjectName("section")
        el.addWidget(t)
        for step in ("1.  Ajoute le PDF d'un cours : l'application le transforme en questions-réponses.",
                     "2.  Lis la fiche du cours, puis teste-toi avec les cartes ou un QCM.",
                     "3.  Reviens quelques minutes chaque jour : l'application te repose chaque question "
                     "juste avant que tu l'oublies."):
            lab = QLabel(step)
            lab.setObjectName("step")
            lab.setWordWrap(True)
            el.addWidget(lab)
        b = QPushButton("Ajouter mon premier cours")
        b.setObjectName("primary")
        b.clicked.connect(self.go_import.emit)
        el.addSpacing(6)
        el.addLayout(row(b, None))
        lay.addWidget(self.empty)
        self.empty_space = QWidget()
        lay.addWidget(self.empty_space, 1)

        self.all_btn = QPushButton("Tout cocher")
        self.all_btn.clicked.connect(lambda: self._set_all(True))
        self.none_btn = QPushButton("Tout décocher")
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        self.selection_label = muted("")
        self.selection_label.setWordWrap(False)
        self.edit_btn = QPushButton("Voir et corriger les cartes")
        self.edit_btn.clicked.connect(self._edit)
        self.exam_btn_date = QPushButton("Date d'examen…")
        self.exam_btn_date.setToolTip("Indique le jour de l'examen des cours cochés : l'application règle le rythme "
                                      "des nouvelles cartes pour que tout soit vu à temps.")
        self.exam_btn_date.clicked.connect(self._set_exam)
        self.share_btn = QPushButton("Partager…")
        self.share_btn.setToolTip("Enregistre les cours cochés dans un fichier à envoyer à quelqu'un : il n'a plus "
                                  "qu'à le glisser dans « Ajouter un cours ». Ta progression n'est pas incluse.")
        self.share_btn.clicked.connect(self._share)
        self.delete_btn = QPushButton("Supprimer")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._delete)
        lay.addLayout(row(self.all_btn, self.none_btn, self.selection_label, None, self.edit_btn,
                          self.exam_btn_date, self.share_btn, self.delete_btn))

        self.review_btn = ActionCard("Réviser", "Les cartes du jour : celles à revoir et quelques nouvelles.", True)
        self.review_btn.clicked.connect(lambda: self._start(False))
        self.exam_btn = ActionCard("Tout revoir", "Veille de contrôle : toutes les cartes, jusqu'à les savoir.")
        self.exam_btn.clicked.connect(lambda: self._start(True))
        self.learn_btn = ActionCard("Lire la fiche", "Le cours résumé, réponses visibles, pour apprendre d'abord.")
        self.learn_btn.clicked.connect(lambda: self.open_learn.emit(self.selected_decks()))
        self.quiz_btn = ActionCard("QCM", "Quatre propositions, une seule bonne réponse.")
        self.quiz_btn.clicked.connect(lambda: self.open_quiz.emit(self.selected_decks()))
        self.actions = (self.review_btn, self.exam_btn, self.learn_btn, self.quiz_btn)
        actions = row(*self.actions, spacing=10)
        for i in range(len(self.actions)):
            actions.setStretch(i, 1)
        lay.addSpacing(4)
        lay.addLayout(actions)

        self.new_per_day = QSpinBox()
        self.new_per_day.setRange(0, 999)
        self.new_per_day.setValue(20)
        self.new_per_day.setToolTip("« Réviser » ajoute chaque jour au maximum ce nombre de cartes jamais vues.")
        self.include_known = QCheckBox("« Tout revoir » repose aussi les cartes déjà connues")
        self.include_known.setToolTip("Sinon, les cartes que tu as su récemment sont sautées.")
        self.settings_label = muted("Réglages :   nouvelles cartes par jour")
        self.settings_label.setWordWrap(False)
        lay.addSpacing(4)
        lay.addLayout(row(self.settings_label, self.new_per_day, self.include_known, None, spacing=10))
        self.exam_hint = muted("")
        self.new_per_day.valueChanged.connect(lambda _: self._update_buttons())
        self.exam_hint.setVisible(False)
        lay.addWidget(self.exam_hint)
        self.refresh()

    # ------------------------------------------------------------------ données
    def refresh(self) -> None:
        checked = set(self.selected_decks())
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
                item = QTreeWidgetItem([deck_label(d)] + [str(v) for v in vals] + [self._exam_text(d, known, len(cards))])
                item.setTextAlignment(5, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        for w in (self.tree, self.all_btn, self.none_btn, self.selection_label, *self.actions, self.new_per_day,
                  self.include_known, self.edit_btn, self.exam_btn_date, self.share_btn, self.delete_btn,
                  self.settings_label):
            w.setVisible(has)
        self.empty.setVisible(not has)
        self.empty_space.setVisible(not has)
        if has and not checked and len(self.db.decks()) == 1:  # un seul cours : inutile de le faire cocher
            self.tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Checked)
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

    def _on_pressed(self, item, column) -> None:
        self._pressed = (item, item.checkState(0))

    def _on_clicked(self, item, column) -> None:
        """Un clic n'importe où sur la ligne coche le cours (pas seulement sur la petite case)."""
        pressed, self._pressed = self._pressed, None
        if pressed is None or pressed[0] is not item or item.checkState(0) != pressed[1]:
            return  # la case elle-même a été cliquée : Qt a déjà changé son état
        item.setCheckState(0, Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)

    def _update_buttons(self) -> None:
        sel = self.selected_decks()
        n_cards = sum(len(self.db.cards(deck_id=d, include_suspended=False)) for d in sel)
        self.selection_label.setText(f"{len(sel)} cours coché{'s' if len(sel) > 1 else ''}, {n_cards} cartes" if sel
                                     else "Coche au moins un cours pour commencer.")
        for b in self.actions:
            b.setEnabled(bool(sel))
        self.edit_btn.setEnabled(len(sel) == 1)
        self.edit_btn.setToolTip("" if len(sel) == 1 else "Coche un seul cours pour voir ses cartes.")
        self.share_btn.setEnabled(bool(sel))
        self.exam_btn_date.setEnabled(bool(sel))
        self.delete_btn.setEnabled(bool(sel))
        needed, soonest = self.exam_plan(sel)
        if soonest is not None and needed > self.new_per_day.value():
            when = {0: "aujourd'hui", 1: "demain"}.get(soonest, f"dans {soonest} jours")
            self.exam_hint.setText(f"Examen {when} : « Réviser » proposera {needed} nouvelles cartes par jour "
                                   f"(au lieu de {self.new_per_day.value()}) pour que tout soit vu à temps.")
        self.exam_hint.setVisible(bool(sel) and soonest is not None and needed > self.new_per_day.value())

    def _start(self, exam: bool) -> None:
        sel = self.selected_decks()
        if sel:
            new_per_day = self.new_per_day.value() if exam else max(self.new_per_day.value(), self.exam_plan(sel)[0])
            self.start_review.emit(sel, exam, self.include_known.isChecked(), new_per_day)

    def _edit(self) -> None:
        sel = self.selected_decks()
        if len(sel) == 1:
            self.edit_cards.emit(sel[0])

    # ------------------------------------------------------------------- examen
    @staticmethod
    def _exam_text(deck, known: int, total: int) -> str:
        days = exam.days_left(deck.exam_date)
        if days is None:
            return ""
        if days < 0:
            return "passé"
        return f"{exam.countdown(days)} · prêt à {exam.readiness(known, total)} %"

    def exam_plan(self, deck_ids: list[int]) -> tuple[int, int | None]:
        """(nouvelles cartes par jour qu'il faut pour les examens à venir des cours donnés,
        jours avant le plus proche de ces examens — None s'il n'y en a pas)."""
        needed, soonest = 0, None
        today_start = start_of_day(utcnow())
        for deck_id in deck_ids:
            deck = self.db.deck(deck_id)
            days = exam.days_left(deck.exam_date) if deck else None
            if days is None or days < 0:
                continue
            soonest = days if soonest is None else min(soonest, days)
            # Les nouvelles cartes déjà vues aujourd'hui comptent dans la part du jour.
            todo = (len(self.db.new_cards(100_000, deck_ids=[deck_id]))
                    + self.db.new_introduced_since(today_start, deck_ids=[deck_id]))
            needed += exam.new_per_day(todo, days)
        return needed, soonest

    def _set_exam(self) -> None:
        sel = self.selected_decks()
        if not sel:
            return
        dates = {d.exam_date for d in map(self.db.deck, sel) if d is not None}
        dialog = ExamDialog(dates.pop() if len(dates) == 1 else None, len(sel), self)
        if dialog.exec():
            self.set_exam_date(dialog.chosen)

    def set_exam_date(self, value: str | None) -> None:
        self.db.set_exam_date(self.selected_decks(), value)
        self.refresh()

    def _share(self) -> None:
        sel = self.selected_decks()
        if not sel:
            return
        first = self.db.deck(sel[0])
        if first is None:
            return
        name = deck_label(first) if len(sel) == 1 else f"{first.subject} ({len(sel)} cours)"
        name = re.sub(r'[\\/:*?"<>|]+', " ", name).strip() or "cours"
        path, chosen = QFileDialog.getSaveFileName(self, "Partager des cours", str(Path.home() / name),
                                                   f"{SHARE_FILTER};;{ANKI_FILTER}")
        if path:
            self.share_to(Path(path), anki=chosen == ANKI_FILTER)

    def share_to(self, dest: Path, anki: bool = False) -> bool:
        """Écrit les cours cochés dans `dest` (fichier .revise, ou texte pour Anki)."""
        wanted = ".txt" if anki else share.EXTENSION
        if dest.suffix.lower() != wanted:
            dest = dest.with_name(dest.name + wanted)
        try:
            n = (share.export_anki if anki else share.export_courses)(self.db, self.selected_decks(), dest)
        except ReviseError as e:
            QMessageBox.warning(self, "Partager", str(e))
            return False
        self.selection_label.setText(f"{n} cartes enregistrées dans {dest.name}")
        return True

    def _delete(self) -> None:
        sel = self.selected_decks()
        if not sel:
            return
        names = "\n".join(f"• {deck_label(self.db.deck(d))}" for d in sel)
        if not confirm(self, "Supprimer", f"Supprimer ces cours, leurs cartes et leur historique ?\n\n{names}",
                       "Supprimer"):
            return
        for d in sel:
            self.db.delete_deck(d)
        self.refresh()
