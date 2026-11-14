"""Page « QCM » : questions à choix multiples tirées des cartes d'un cours."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from revise.db import Card, Database, deck_label
from revise.gui import theme
from revise.gui.common import cloze_question, fill_scope_combo, muted, page_header, row
from revise.gui.review import markdown_view
from revise.quiz import QuizQuestion, build_quiz, usable_count


class ChoiceCard(QFrame):
    """Une réponse proposée : cadre cliquable dont le texte revient à la ligne."""

    clicked = Signal()

    def __init__(self, key: int):
        super().__init__()
        self.setObjectName("choice")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)
        self.key = QLabel(str(key))
        self.key.setObjectName("choiceKey")
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.MarkdownText)
        for lab in (self.key, self.text):
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.key, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.text, 1)
        self.active = True

    def set_choice(self, text: str) -> None:
        self.text.setText(text)
        self.set_state("")
        self.active = True

    def set_state(self, state: str) -> None:
        """État affiché : vide = cliquable, "good" = bonne réponse, "bad" = erreur, "off" = figé."""
        self.active = False
        self.setProperty("state", state)
        self.setCursor(Qt.CursorShape.ArrowCursor if state else Qt.CursorShape.PointingHandCursor)
        self.style().unpolish(self)
        self.style().polish(self)

    def click(self) -> None:
        if self.active and self.isEnabled():
            self.clicked.emit()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.click()


class QuizPage(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setObjectName("page")
        self.questions: list[QuizQuestion] = []
        self.index = 0
        self.score = 0
        self.answered = False
        self.mistakes: list[QuizQuestion] = []
        self.labels: dict[int, str] = {}

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
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._key_next)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- construction ---------------------------------------------------------

    def _build_setup(self) -> QWidget:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page_header("QCM", "Quatre réponses proposées, une seule est la bonne. Les mauvaises réponses "
                                         "viennent des autres cartes du cours : plus le cours a de cartes, plus "
                                         "le QCM est piégeux. Le QCM ne modifie pas ton planning de révision."))
        self.scope = QComboBox()
        self.scope.setMinimumWidth(420)
        self.scope.currentIndexChanged.connect(self._update_setup)
        lay.addLayout(row(muted("Cours :"), self.scope, None))
        self.count = QSpinBox()
        self.count.setRange(1, 200)
        self.count.setValue(10)
        self.count.setSuffix(" questions")
        lay.addLayout(row(muted("Longueur :"), self.count, None))
        self.info = muted("")
        lay.addWidget(self.info)
        self.start_btn = QPushButton("Commencer le QCM")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        lay.addLayout(row(self.start_btn, None))
        lay.addStretch(1)
        return w

    def _build_question(self) -> QWidget:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.where = muted("")
        self.where.setWordWrap(False)
        quit_btn = QPushButton("Arrêter")
        quit_btn.clicked.connect(self.finish)
        lay.addLayout(row(self.where, None, quit_btn))
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        lay.addWidget(self.progress)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 16, 22, 16)
        self.question = markdown_view(16)
        cl.addWidget(self.question)
        lay.addWidget(card, 2)

        self.choices: list[ChoiceCard] = []
        for i in range(4):
            c = ChoiceCard(i + 1)
            c.clicked.connect(lambda i=i: self.choose(i))
            self.choices.append(c)
            lay.addWidget(c)
        self.feedback = QLabel()
        self.feedback.setTextFormat(Qt.TextFormat.RichText)
        self.next_btn = QPushButton("Question suivante  (Entrée)")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self.next_question)
        lay.addLayout(row(self.feedback, None, self.next_btn))
        return w

    def _build_result(self) -> QWidget:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page_header("Résultat du QCM"))
        self.result = QLabel()
        self.result.setObjectName("big")
        lay.addWidget(self.result)
        self.result_detail = muted("")
        lay.addWidget(self.result_detail)
        self.review_view = markdown_view(12)
        lay.addWidget(self.review_view, 1)
        self.retry_btn = QPushButton("Refaire mes erreurs")
        self.retry_btn.setObjectName("primary")
        self.retry_btn.clicked.connect(self.retry_mistakes)
        again = QPushButton("Nouveau QCM")
        again.clicked.connect(self.refresh)
        lay.addLayout(row(self.retry_btn, again, None))
        return w

    # -- préparation ----------------------------------------------------------

    def refresh(self) -> None:
        """Revient à l'écran de préparation, sauf si un QCM est en cours."""
        if self.pages.currentIndex() == 1 and self.questions:
            return
        fill_scope_combo(self.scope, self.db)
        self.labels = {d.id: deck_label(d) for d in self.db.decks()}
        self.pages.setCurrentIndex(0)
        self._update_setup()

    def _cards(self) -> list[Card]:
        deck_ids = self.scope.currentData()
        if not deck_ids:
            return []
        return self.db.cards(deck_ids=list(deck_ids), include_suspended=False)

    def _update_setup(self) -> None:
        cards = self._cards()
        usable = usable_count(cards)
        self.start_btn.setEnabled(usable > 0)
        if self.scope.count() == 0:
            self.info.setText("Aucun cours pour l'instant : importe un PDF dans l'onglet « Importer ».")
        elif usable == 0:
            self.info.setText("Il faut au moins deux cartes aux réponses différentes pour faire un QCM.")
        else:
            self.info.setText(f"{usable} question(s) possible(s) avec ce choix.")

    def start(self) -> None:
        cards = self._cards()
        self._run(build_quiz(cards, self.count.value()))

    def retry_mistakes(self) -> None:
        pool = self._cards()
        self._run(build_quiz([q.card for q in self.mistakes], len(self.mistakes), pool=pool))

    def _run(self, questions: list[QuizQuestion]) -> None:
        if not questions:
            return
        self.questions = questions
        self.index = 0
        self.score = 0
        self.mistakes = []
        self.progress.setRange(0, len(questions))
        self.pages.setCurrentIndex(1)
        self._show()
        self.setFocus()

    # -- déroulement ----------------------------------------------------------

    def _show(self) -> None:
        q = self.questions[self.index]
        c = q.card
        where = self.labels.get(c.deck_id, "")
        if c.page:
            where += f" · p. {c.page}"
        if c.section:
            where += f" · {c.section}"
        self.where.setText(where)
        self.question.setMarkdown(cloze_question(c.question))
        for i, widget in enumerate(self.choices):
            widget.setVisible(i < len(q.choices))
            if i < len(q.choices):
                widget.set_choice(q.choices[i])
        self.answered = False
        self.feedback.setText("")
        self.next_btn.setVisible(False)
        self._update_status()

    def _update_status(self) -> None:
        done = self.index + (1 if self.answered else 0)
        self.progress.setValue(done)
        self.status.setText(f"<b>Question {self.index + 1} / {len(self.questions)}</b> &nbsp; "
                            f"<span style='color:{theme.GOOD}'>{self.score} bonne(s)</span> &nbsp; "
                            f"<span style='color:{theme.BAD}'>{len(self.mistakes)} erreur(s)</span>")

    def choose(self, i: int) -> None:
        if self.answered or self.pages.currentIndex() != 1:
            return
        q = self.questions[self.index]
        if i >= len(q.choices):
            return
        self.answered = True
        for j, widget in enumerate(self.choices[:len(q.choices)]):
            widget.set_state("good" if j == q.correct else "bad" if j == i else "off")
        if i == q.correct:
            self.score += 1
            self.feedback.setText(f"<span style='color:{theme.GOOD}'><b>Bonne réponse !</b></span>")
        else:
            self.mistakes.append(q)
            self.feedback.setText(f"<span style='color:{theme.BAD}'><b>Raté</b></span> — la bonne réponse "
                                  f"était la {q.correct + 1}.")
        last = self.index == len(self.questions) - 1
        self.next_btn.setText("Voir le résultat  (Entrée)" if last else "Question suivante  (Entrée)")
        self.next_btn.setVisible(True)
        self._update_status()

    def next_question(self) -> None:
        if not self.answered:
            return
        if self.index >= len(self.questions) - 1:
            self.finish()
            return
        self.index += 1
        self._show()

    def finish(self) -> None:
        answered = self.index + (1 if self.answered else 0)
        self.questions = []
        if answered == 0:
            self.refresh()
            return
        pct = round(100 * self.score / answered)
        self.result.setText(f"{self.score} / {answered}")
        self.result.setStyleSheet(
            f"color: {theme.GOOD if pct >= 80 else theme.WARN if pct >= 50 else theme.BAD};")
        self.result_detail.setText(
            f"{pct} % de bonnes réponses. " + ("Sans faute, bravo !" if not self.mistakes
                                               else "Voici ce qu'il faut revoir :"))
        parts = []
        for q in self.mistakes:
            parts.append(f"**{cloze_question(q.card.question)}**\n\n{q.card.answer}")
        self.review_view.setMarkdown("\n\n---\n\n".join(parts))
        self.review_view.setVisible(bool(self.mistakes))
        self.retry_btn.setVisible(bool(self.mistakes))
        self.pages.setCurrentIndex(2)

    def _key_choice(self, i: int) -> None:
        if self.pages.currentIndex() == 1:
            self.choose(i)

    def _key_next(self) -> None:
        if self.pages.currentIndex() == 1 and self.answered:
            self.next_question()
