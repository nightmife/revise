"""Page « QCM » : questions à choix multiples tirées des cartes d'un cours."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from revise import mathtext
from revise.db import Card, Database, deck_label
from revise.engines import distractors
from revise.gui import theme
from revise.gui.common import cloze_question, confirm, fill_scope_combo, muted, page_header, row, select_scope
from revise.gui.render import show_markdown
from revise.gui.review import markdown_view
from revise.models import ReviseError
from revise.quiz import QuizQuestion, build_quiz, outdated_count, prepared_count, usable_count


class PrepareWorker(QObject):
    """Fait écrire par l'IA, dans un thread, les mauvaises réponses des cartes qui n'en ont pas."""

    status = Signal(str)
    done = Signal(int, str)  # cartes complétées, message d'erreur éventuel

    def __init__(self, db_path: Path, deck_ids: list[int]):
        super().__init__()
        self.db_path, self.deck_ids = db_path, deck_ids
        self.cancelled = False
        self.engine = None

    def run(self) -> None:
        db = Database(self.db_path)
        before = prepared_count(db.cards(deck_ids=self.deck_ids))
        error = ""
        try:
            self.engine = distractors.default_engine()
            getattr(self.engine, "check", lambda: None)()
            self.engine.progress = self.status.emit
            distractors.prepare(db, self.deck_ids, self.engine.chat, self.status.emit, lambda: self.cancelled,
                                getattr(self.engine, "trap_batch", distractors.BATCH))
        except ReviseError as e:
            error = str(e)
        except Exception as e:  # une panne de l'IA ne doit pas fermer l'application
            error = f"erreur inattendue : {e}"
        finally:
            self.stop_engine()
            filled = prepared_count(db.cards(deck_ids=self.deck_ids)) - before
            db.close()
            self.done.emit(filled, error)

    def stop_engine(self) -> None:
        getattr(self.engine, "close", lambda: None)()


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
        self.text.setText(mathtext.render(text))
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
        self.mistakes: list[tuple[QuizQuestion, int]] = []  # question ratée, réponse choisie
        self.labels: dict[int, str] = {}
        self.custom: list[int] | None = None
        self._thread: QThread | None = None
        self.worker: PrepareWorker | None = None

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
        lay.addWidget(page_header("QCM", "Quatre propositions, une seule est juste. "
                                         "Le QCM ne change rien à ton planning de révision."))
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

        self.traps = QFrame()
        self.traps.setObjectName("note")
        tl = QVBoxLayout(self.traps)
        tl.setContentsMargins(18, 14, 18, 14)
        self.traps_title = QLabel()
        self.traps_title.setObjectName("section")
        self.traps_text = muted("")
        self.prepare_btn = QPushButton("Préparer les réponses pièges")
        self.prepare_btn.clicked.connect(self.ask_prepare)
        self.stop_btn = QPushButton("Arrêter")
        self.stop_btn.clicked.connect(self.stop_prepare)
        self.stop_btn.setVisible(False)
        self.traps_status = muted("")
        self.traps_status.setWordWrap(False)
        tl.addWidget(self.traps_title)
        tl.addWidget(self.traps_text)
        tl.addLayout(row(self.prepare_btn, self.stop_btn, self.traps_status, None))
        lay.addSpacing(6)
        lay.addWidget(self.traps)
        lay.addSpacing(6)

        self.start_btn = QPushButton("Commencer le QCM")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(46)
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
        fill_scope_combo(self.scope, self.db, self.custom)
        self.labels = {d.id: deck_label(d) for d in self.db.decks()}
        self.pages.setCurrentIndex(0)
        self._update_setup()

    def set_scope(self, deck_ids: list[int]) -> None:
        """Prépare un QCM sur ces cours (ceux cochés dans « Mes cours »)."""
        self.custom = deck_ids
        self.questions = []
        self.refresh()
        select_scope(self.scope, deck_ids)
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
            self.info.setText("Aucun cours pour l'instant : commence par « Ajouter un cours ».")
        elif usable == 0:
            self.info.setText("Il faut au moins deux cartes aux réponses différentes pour faire un QCM.")
        else:
            self.info.setText(f"{usable} question{'s' if usable > 1 else ''} possible{'s' if usable > 1 else ''} "
                              "avec ce choix.")
        self._update_traps(cards)

    def _update_traps(self, cards: list[Card]) -> None:
        missing = len(cards) - prepared_count(cards)
        busy = self.worker is not None
        self.traps.setVisible(bool(cards))
        self.prepare_btn.setVisible(missing > 0 or busy)
        self.prepare_btn.setEnabled(not busy)
        self.stop_btn.setVisible(busy)
        if missing == 0:
            self.traps_title.setText("Réponses pièges prêtes")
            self.traps_text.setText("Pour chaque question, l'IA a écrit de fausses réponses crédibles : "
                                    "impossible de deviner sans connaître le cours.")
        elif outdated_count(cards) == missing:
            self.traps_title.setText("Réponses pièges à refaire")
            self.traps_text.setText(
                f"Pour {missing} question{'s' if missing > 1 else ''}, les réponses pièges datent d'une ancienne "
                "version : la bonne réponse se repère souvent parce qu'elle est plus longue ou plus détaillée. "
                "L'IA peut réécrire les quatre propositions pour qu'elles se ressemblent.")
        else:
            self.traps_title.setText("QCM trop facile pour l'instant" if missing == len(cards)
                                     else f"Réponses pièges prêtes pour {len(cards) - missing} questions "
                                          f"sur {len(cards)}")
            self.traps_text.setText(
                f"Pour {missing} question{'s' if missing > 1 else ''}, les mauvaises réponses sont empruntées à "
                "d'autres questions du cours : elles se repèrent vite. L'IA peut écrire à la place de fausses "
                "réponses crédibles sur le même sujet. C'est à faire une seule fois par cours.")

    # -- réponses pièges --------------------------------------------------------

    def ask_prepare(self) -> None:
        deck_ids = list(self.scope.currentData() or [])
        if not deck_ids or self.worker is not None:
            return
        engine = distractors.default_engine_name()
        online = engine == "en-ligne"
        how = ("Claude (ton abonnement) va écrire les réponses pièges : compte environ une minute pour cent "
               "questions." if engine == "abonnement" else
               "L'IA en ligne va écrire les réponses pièges : compte une à deux minutes pour cent questions avec "
               "une clé (sans clé : environ un quart d'heure). "
               "Les questions du cours sont envoyées au service d'IA choisi." if online else
               "L'IA installée sur cet ordinateur va écrire les réponses pièges. Si elle n'a encore jamais servi, "
               "elle est d'abord téléchargée (2,5 à 7 Go, une seule fois). Ensuite, compte plusieurs minutes "
               "pour cent questions.")
        if confirm(self, "Préparer les réponses pièges",
                   how + "\n\nTu peux arrêter quand tu veux : ce qui est fait est gardé.", "Lancer"):
            self.start_prepare(deck_ids)

    def start_prepare(self, deck_ids: list[int]) -> None:
        self._thread = QThread(self)
        self.worker = PrepareWorker(Path(self.db.path), deck_ids)
        self.worker.moveToThread(self._thread)
        self._thread.started.connect(self.worker.run)
        self.worker.status.connect(self.traps_status.setText)
        self.worker.done.connect(self._prepare_done)
        self.traps_status.setText("Démarrage…")
        self._update_traps(self._cards())
        self._thread.start()

    def stop_prepare(self) -> None:
        if self.worker:
            self.worker.cancelled = True
            self.stop_btn.setEnabled(False)
            self.traps_status.setText("Arrêt après les questions en cours…")

    def _prepare_done(self, filled: int, error: str) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.worker = None
        self.stop_btn.setEnabled(True)
        self.traps_status.setText(error if error else f"Terminé : {filled} question{'s' if filled > 1 else ''} "
                                                      f"complétée{'s' if filled > 1 else ''}.")
        self._update_traps(self._cards())

    def start(self) -> None:
        cards = self._cards()
        self._run(build_quiz(cards, self.count.value()))

    def retry_mistakes(self) -> None:
        pool = self._cards()
        self._run(build_quiz([q.card for q, _ in self.mistakes], len(self.mistakes), pool=pool))

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
        show_markdown(self.question, cloze_question(c.question))
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
        self.db.record_quiz_answer(q.card.id, i == q.correct)  # pour « Mes points faibles » (planning inchangé)
        for j, widget in enumerate(self.choices[:len(q.choices)]):
            widget.set_state("good" if j == q.correct else "bad" if j == i else "off")
        if i == q.correct:
            self.score += 1
            self.feedback.setText(f"<span style='color:{theme.GOOD}'><b>Bonne réponse !</b></span>")
        else:
            self.mistakes.append((q, i))
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
        for q, chosen in self.mistakes:
            parts.append(f"**{cloze_question(q.card.question)}**\n\n"
                         f"Ta réponse : {q.choices[chosen]}\n\nLa bonne réponse : {q.card.answer}")
        show_markdown(self.review_view, "\n\n---\n\n".join(parts))
        self.review_view.setVisible(bool(self.mistakes))
        self.retry_btn.setVisible(bool(self.mistakes))
        self.pages.setCurrentIndex(2)

    def _key_choice(self, i: int) -> None:
        if self.pages.currentIndex() == 1:
            self.choose(i)

    def _key_next(self) -> None:
        if self.pages.currentIndex() == 1 and self.answered:
            self.next_question()
