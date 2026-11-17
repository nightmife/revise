"""Page « Examen blanc » : QCM et réponses à écrire, chronométré, noté sur 20, avec corrigé."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QFrame, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar,
                               QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from revise.answercheck import CLOSE
from revise.db import Card, Database, deck_label
from revise.gui import theme
from revise.gui.common import cloze_question, confirm, fill_scope_combo, muted, page_header, row, select_scope
from revise.gui.quiz_page import ChoiceCard
from revise.gui.render import show_markdown
from revise.gui.review import markdown_view
from revise.mock_exam import ExamQuestion, answer_choice, answer_written, build_exam, mark
from revise.quiz import usable_count

WRITTEN_SHARES = (("Moitié QCM, moitié à écrire", 0.5), ("Surtout des QCM", 0.25), ("Surtout à écrire", 0.75),
                  ("Que des QCM", 0.0), ("Que des réponses à écrire", 1.0))
ITEM_ROLE = Qt.ItemDataRole.UserRole


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class ExamPage(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setObjectName("page")
        self.questions: list[ExamQuestion] = []
        self.questions_done: list[ExamQuestion] = []
        self.selected = -1
        self.elapsed = 0.0
        self.index = 0
        self.deadline = 0.0          # time.monotonic() de la fin (0 = pas de limite)
        self.started = 0.0
        self.custom: list[int] | None = None
        self.labels: dict[int, str] = {}
        self.answer_ids: dict[int, int] = {}   # indice de question → ligne enregistrée (corrections)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)
        self.pages.addWidget(self._build_setup())
        self.pages.addWidget(self._build_question())
        self.pages.addWidget(self._build_result())
        for k in range(1, 5):
            sc = QShortcut(QKeySequence(str(k)), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda i=k - 1: self._key_choice(i))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- construction ---------------------------------------------------------
    def _build_setup(self) -> QWidget:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page_header("Examen blanc", "Comme le jour J : des QCM et des réponses à écrire, en temps "
                                                  "limité, sans voir les réponses avant la fin. Note sur 20 et corrigé. "
                                                  "Ne change rien à ton planning de révision."))
        self.scope = QComboBox()
        self.scope.setMinimumWidth(420)
        self.scope.currentIndexChanged.connect(self._update_setup)
        lay.addLayout(row(muted("Cours :"), self.scope, None))
        self.count = QSpinBox()
        self.count.setRange(1, 100)
        self.count.setValue(20)
        self.count.setSuffix(" questions")
        lay.addLayout(row(muted("Longueur :"), self.count, None))
        self.duration = QSpinBox()
        self.duration.setRange(0, 240)
        self.duration.setValue(20)
        self.duration.setSuffix(" min")
        self.duration.setSpecialValueText("sans limite")
        self.duration.setToolTip("Quand le temps est écoulé, l'examen s'arrête et les questions restantes valent 0.")
        lay.addLayout(row(muted("Durée :"), self.duration, None))
        self.mix = QComboBox()
        for label, share in WRITTEN_SHARES:
            self.mix.addItem(label, share)
        lay.addLayout(row(muted("Questions :"), self.mix, None))
        self.info = muted("")
        lay.addWidget(self.info)
        lay.addWidget(muted("Réponses écrites : l'application compare tes mots à ceux de la réponse (fautes de frappe "
                            "tolérées). Juste = 1 point, presque = ½ point. Au corrigé, tu peux compter une réponse "
                            "comme juste si la correction automatique s'est trompée."))
        self.start_btn = QPushButton("Commencer l'examen")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(46)
        self.start_btn.clicked.connect(self.start)
        lay.addSpacing(6)
        lay.addLayout(row(self.start_btn, None))
        lay.addStretch(1)
        return w

    def _build_question(self) -> QWidget:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.clock = QLabel()
        self.clock.setObjectName("section")
        stop = QPushButton("Rendre la copie")
        stop.setToolTip("Termine l'examen maintenant : les questions sans réponse valent 0.")
        stop.clicked.connect(self.ask_finish)
        lay.addLayout(row(self.status, None, self.clock, stop))
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        lay.addWidget(self.progress)
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 16, 22, 16)
        self.kind = muted("")
        cl.addWidget(self.kind)
        self.question = markdown_view(16)
        cl.addWidget(self.question)
        lay.addWidget(card, 2)
        self.choices: list[ChoiceCard] = []
        for i in range(4):
            c = ChoiceCard(i + 1)
            c.clicked.connect(lambda i=i: self.choose(i))
            self.choices.append(c)
            lay.addWidget(c)
        self.written = QPlainTextEdit()
        self.written.setPlaceholderText("Écris ta réponse ici")
        self.written.setMaximumHeight(140)
        lay.addWidget(self.written)
        self.skip_btn = QPushButton("Passer")
        self.skip_btn.setToolTip("Question laissée sans réponse (0 point).")
        self.skip_btn.clicked.connect(self.skip)
        self.next_btn = QPushButton("Valider et continuer")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self.validate)
        lay.addLayout(row(None, self.skip_btn, self.next_btn))
        return w

    def _build_result(self) -> QWidget:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page_header("Résultat de l'examen blanc"))
        self.note = QLabel()
        self.note.setObjectName("big")
        lay.addWidget(self.note)
        self.note_detail = muted("")
        lay.addWidget(self.note_detail)
        self.correction = QListWidget()
        self.correction.setWordWrap(True)
        self.correction.itemChanged.connect(self._override)
        lay.addWidget(self.correction, 1)
        again = QPushButton("Nouvel examen")
        again.setObjectName("primary")
        again.clicked.connect(self.refresh)
        lay.addLayout(row(again, None))
        return w

    # -- préparation ----------------------------------------------------------
    def refresh(self) -> None:
        if self.pages.currentIndex() == 1 and self.questions:
            return  # examen en cours
        fill_scope_combo(self.scope, self.db, self.custom)
        self.labels = {d.id: deck_label(d) for d in self.db.decks()}
        self.pages.setCurrentIndex(0)
        self._update_setup()

    def set_scope(self, deck_ids: list[int]) -> None:
        self.custom = deck_ids
        self.refresh()
        select_scope(self.scope, deck_ids)

    def _cards(self) -> list[Card]:
        ids = self.scope.currentData()
        return self.db.cards(deck_ids=list(ids), include_suspended=False) if ids else []

    def _update_setup(self) -> None:
        cards = self._cards()
        self.start_btn.setEnabled(bool(cards))
        if self.scope.count() == 0:
            self.info.setText("Aucun cours pour l'instant : commence par « Ajouter un cours ».")
        else:
            self.info.setText(f"{len(cards)} cartes dans ce choix ({usable_count(cards)} utilisables en QCM).")

    def start(self) -> None:
        cards = self._cards()
        questions = build_exam(cards, self.count.value(), self.mix.currentData())
        if not questions:
            return
        self.questions = questions
        self.index = 0
        self.answer_ids = {}
        self.started = time.monotonic()
        minutes = self.duration.value()
        self.deadline = self.started + 60 * minutes if minutes else 0.0
        self.progress.setRange(0, len(questions))
        self.pages.setCurrentIndex(1)
        self._show()
        self._tick()
        self.timer.start()

    # -- déroulement ----------------------------------------------------------
    def current(self) -> ExamQuestion | None:
        return self.questions[self.index] if 0 <= self.index < len(self.questions) else None

    def _show(self) -> None:
        q = self.current()
        if q is None:
            self.finish()
            return
        c = q.card
        where = self.labels.get(c.deck_id, "")
        self.status.setText(f"<b>Question {self.index + 1} / {len(self.questions)}</b> &nbsp; "
                            f"<span style='color:{theme.MUTED}'>{where}</span>")
        self.progress.setValue(self.index)
        self.kind.setText("QCM : choisis une réponse (touches 1 à 4)" if q.mode == "qcm"
                          else "Réponse à écrire")
        show_markdown(self.question, cloze_question(c.question))
        is_qcm = q.mode == "qcm"
        for i, widget in enumerate(self.choices):
            widget.setVisible(is_qcm and i < len(q.choices))
            if is_qcm and i < len(q.choices):
                widget.set_choice(q.choices[i])
        self.selected = -1
        self.written.setVisible(not is_qcm)
        self.written.clear()
        self.next_btn.setEnabled(not is_qcm)
        if is_qcm:
            self.setFocus()
        else:
            self.written.setFocus()

    def choose(self, i: int) -> None:
        q = self.current()
        if q is None or q.mode != "qcm" or i >= len(q.choices) or self.pages.currentIndex() != 1:
            return
        self.selected = i
        for j, widget in enumerate(self.choices[:len(q.choices)]):
            widget.set_state("")
            if j == i:  # choix marqué, sans dire s'il est juste
                widget.setStyleSheet(f"QFrame#choice {{ border-color: {theme.ACCENT}; }}")
            else:
                widget.setStyleSheet("")
        self.next_btn.setEnabled(True)

    def _key_choice(self, i: int) -> None:
        if self.pages.currentIndex() == 1 and not self.written.hasFocus():
            self.choose(i)

    def validate(self) -> None:
        q = self.current()
        if q is None:
            return
        if q.mode == "qcm":
            if self.selected < 0:
                return
            answer_choice(q, self.selected)
        else:
            answer_written(q, self.written.toPlainText())
        self._next()

    def skip(self) -> None:
        q = self.current()
        if q is not None:
            q.given, q.points = "", 0.0
        self._next()

    def _next(self) -> None:
        for widget in self.choices:
            widget.setStyleSheet("")
        self.index += 1
        if self.index >= len(self.questions):
            self.finish()
        else:
            self._show()

    def _tick(self) -> None:
        if self.pages.currentIndex() != 1:
            self.timer.stop()
            return
        if not self.deadline:
            self.clock.setText(f"⏱ {clock(time.monotonic() - self.started)}")
            return
        left = self.deadline - time.monotonic()
        self.clock.setText(f"⏱ {clock(left)}")
        self.clock.setStyleSheet(f"color: {theme.BAD};" if left < 60 else "")
        if left <= 0:
            self.finish()

    def ask_finish(self) -> None:
        unanswered = sum(not q.answered for q in self.questions)
        if not unanswered or confirm(self, "Rendre la copie", f"{unanswered} question(s) sans réponse vaudront 0. "
                                     "Rendre la copie maintenant ?", "Rendre"):
            self.finish()

    def finish(self) -> None:
        self.timer.stop()
        if not self.questions:
            self.refresh()
            return
        for i, q in enumerate(self.questions):
            if q.points is None:
                q.points = 0.0
            if q.given:  # une question passée ne compte pas comme une erreur de connaissance
                self.answer_ids[i] = self.db.record_quiz_answer(q.card.id, q.points >= 1, "examen")
        self.elapsed = time.monotonic() - self.started
        self.correction.blockSignals(True)
        self.correction.clear()
        for i, q in enumerate(self.questions):
            given = q.given or "(sans réponse)"
            right = q.choices[q.correct] if q.mode == "qcm" else q.card.answer
            text = (f"{i + 1}. {cloze_question(q.card.question).replace('**', '')}\n"
                    f"    Ta réponse : {given}\n    Réponse attendue : {right}")
            item = QListWidgetItem(text)
            item.setData(ITEM_ROLE, i)
            item.setToolTip(right)
            if q.mode == "ecrit" and q.given:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if q.points >= 1 else Qt.CheckState.Unchecked)
            self.correction.addItem(item)
            self._paint_item(item, q)
        self.correction.blockSignals(False)
        self._show_note()
        self.pages.setCurrentIndex(2)
        self.questions_done = self.questions
        self.questions = []

    def _paint_item(self, item: QListWidgetItem, q: ExamQuestion) -> None:
        from PySide6.QtGui import QColor
        color = theme.GOOD if q.points >= 1 else theme.WARN if q.points > 0 else theme.BAD
        item.setForeground(QColor(color))
        verdict = "juste" if q.points >= 1 else "½ point" if q.points > 0 else "faux" if q.given else "sans réponse"
        if q.mode == "ecrit" and q.given:
            verdict += " — coche pour compter comme juste"
        item.setText(item.text().split("\n    [")[0] + f"\n    [{verdict}]")

    def _show_note(self) -> None:
        questions = self.questions or self.questions_done
        note, got = mark(questions)
        self.note.setText(f"{str(note).replace('.', ',').removesuffix(',0')} / 20")
        self.note.setStyleSheet(f"color: {theme.GOOD if note >= 14 else theme.WARN if note >= 10 else theme.BAD};")
        written = [q for q in questions if q.mode == "ecrit"]
        self.note_detail.setText(
            f"{str(got).replace('.', ',').removesuffix(',0')} point(s) sur {len(questions)} en {clock(self.elapsed)}"
            + (f" · {sum(q.points >= 1 for q in written)} réponse(s) écrite(s) juste(s) sur {len(written)}"
               if written else "") + ". Les questions ratées rejoignent « Mes points faibles ».")

    def _override(self, item: QListWidgetItem) -> None:
        """L'étudiant corrige la correction automatique d'une réponse écrite."""
        questions = self.questions_done
        i = item.data(ITEM_ROLE)
        if i is None or not 0 <= i < len(questions):
            return
        q = questions[i]
        if item.checkState() == Qt.CheckState.Checked:
            q.points = 1.0
        else:
            q.points = 0.5 if q.check is not None and q.check.verdict == CLOSE else 0.0
        if i in self.answer_ids:
            self.db.set_quiz_answer(self.answer_ids[i], q.points >= 1)
        self.correction.blockSignals(True)
        self._paint_item(item, q)
        self.correction.blockSignals(False)
        self._show_note()

