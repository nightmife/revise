"""Page de révision : une carte à la fois, réponse puis note de 1 à 4."""

from __future__ import annotations

import time

from fsrs import Rating
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QLabel, QLineEdit,
                               QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTextBrowser, QVBoxLayout,
                               QWidget)

from revise import config, pageview
from revise.answercheck import CLOSE, EMPTY, GOOD, check_answer
from revise.db import Card, Database, deck_label, utcnow
from revise.engines import distractors
from revise.engines.explain import explain
from revise.engines.rewrite import rewrite
from revise.gui import theme
from revise.gui.common import Background, cloze_question, confirm, muted, row, save_cancel_buttons
from revise.importer import source_file
from revise.gui.render import show_markdown
from revise.models import KINDS, ReviseError
from revise.scheduler import RATING_LABELS, Session, format_interval, preview

KIND_LABEL = {"qa": "Question", "cloze": "Texte à trous", "code": "Code"}
MAX_DURATION_MS = 60_000


class CardEditDialog(QDialog):
    """Modification d'une carte (question, réponse, type, page)."""

    def __init__(self, card: Card, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier la carte")
        self.resize(640, 480)
        form = QFormLayout(self)
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(KIND_LABEL[k], k)
        self.kind.setCurrentIndex(KINDS.index(card.kind) if card.kind in KINDS else 0)
        self.page = QSpinBox()
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("—")
        self.page.setValue(card.page or 0)
        self.question = QPlainTextEdit(card.question)
        self.answer = QPlainTextEdit(card.answer)
        form.addRow("Type", self.kind)
        form.addRow("Page", self.page)
        form.addRow("Question", self.question)
        form.addRow("Réponse", self.answer)
        form.addRow(muted("Markdown accepté : **gras**, `code`, listes, blocs ``` pour le code."))
        buttons = save_cancel_buttons()
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        if self.question.toPlainText().strip() and self.answer.toPlainText().strip():
            self.accept()

    def values(self) -> tuple[str, str, str, int | None]:
        return (self.kind.currentData(), self.question.toPlainText().strip(), self.answer.toPlainText().strip(),
                self.page.value() or None)


class RewriteDialog(QDialog):
    """Ancienne et nouvelle version d'une carte, côte à côte : l'utilisateur garde celle qu'il veut."""

    def __init__(self, card: Card, question: str, answer: str, change: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouvelle version de la carte")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        if change:
            lay.addWidget(muted(f"Ce que l'IA a corrigé : {change}"))
        for title, q, a in (("Avant", card.question, card.answer), ("Proposée par l'IA", question, answer)):
            head = QLabel(title)
            head.setObjectName("section")
            lay.addWidget(head)
            view = markdown_view(12)
            show_markdown(view, f"**{cloze_question(q)}**\n\n{a}")
            lay.addWidget(view, 1)
        keep_old = QPushButton("Garder l'ancienne")
        keep_old.clicked.connect(self.reject)
        keep_new = QPushButton("Garder la nouvelle")
        keep_new.setObjectName("primary")
        keep_new.clicked.connect(self.accept)
        lay.addLayout(row(None, keep_old, keep_new))


def markdown_view(size: float) -> QTextBrowser:
    v = QTextBrowser()
    v.setOpenExternalLinks(True)
    v.setFrameShape(QFrame.Shape.NoFrame)
    # Le style global fixe la taille des polices : on la redéfinit ici en feuille de style.
    v.setStyleSheet(f"background: transparent; border: none; font-size: {size}pt;")
    v.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    return v


class ReviewPage(QWidget):
    finished = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.setObjectName("page")
        self.db = db
        self.session: Session | None = None
        self.card: Card | None = None
        self.revealed = False
        self.exam = False
        self.total = 0
        self.shown_at = 0.0
        self.started = 0.0
        self.labels: dict[int, str] = {}
        self.subjects: dict[int, str] = {}
        self.engine_factory = distractors.default_engine  # l'IA des imports
        self.engine = None
        self.ai_busy = False
        self._request = 0  # change à chaque carte : une explication arrivée trop tard est ignorée
        self.ai_job = Background(self, self._on_ai)
        self.verdict: str | None = None  # correction de la réponse tapée

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 20)
        self.where = muted("")
        self.where.setWordWrap(False)
        self.counts = QLabel()
        self.counts.setTextFormat(Qt.TextFormat.RichText)
        quit_btn = QPushButton("Terminer")
        quit_btn.setToolTip("Échap")
        quit_btn.clicked.connect(self.finished.emit)
        self.type_toggle = QCheckBox("Écrire mes réponses")
        self.type_toggle.setToolTip("Tape ta réponse avant de la voir : l'application la compare à celle de la carte "
                                    "et te propose une note.")
        self.type_toggle.setChecked(bool(config.load().get("type_answers", False)))
        self.type_toggle.toggled.connect(self._toggle_typing)
        lay.addLayout(row(self.where, None, self.type_toggle, quit_btn))
        lay.addWidget(self.counts)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        lay.addWidget(self.progress)

        self.card_frame = QFrame()
        self.card_frame.setObjectName("card")
        cl = QVBoxLayout(self.card_frame)
        cl.setContentsMargins(28, 20, 28, 20)
        self.kind = muted("")
        cl.addWidget(self.kind)
        self.question = markdown_view(18)
        cl.addWidget(self.question, 4)
        self.sep = QFrame()
        self.sep.setObjectName("sep")
        self.sep.setFixedHeight(1)
        cl.addWidget(self.sep)
        self.answer = markdown_view(15)
        cl.addWidget(self.answer, 4)
        self.think = muted("Cherche la réponse dans ta tête (ou dis-la à voix haute), puis affiche-la pour vérifier.")
        self.think.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.think, 4)
        self.explanation = markdown_view(13)
        self.explanation.setVisible(False)
        cl.addWidget(self.explanation, 3)
        lay.addWidget(self.card_frame, 1)
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Écris ta réponse ici, puis Entrée pour la vérifier")
        self.typed.returnPressed.connect(self.reveal)
        self.typed.setMinimumHeight(42)
        lay.addWidget(self.typed)
        self.check_label = QLabel()
        self.check_label.setTextFormat(Qt.TextFormat.RichText)
        self.check_label.setWordWrap(True)
        lay.addWidget(self.check_label)

        self.reveal_btn = QPushButton("Afficher la réponse  (Espace)")
        self.reveal_btn.setObjectName("primary")
        self.reveal_btn.setMinimumHeight(52)
        self.reveal_btn.clicked.connect(self.reveal)
        self.rate_btns: dict[int, QPushButton] = {}
        for r in Rating:
            b = QPushButton()
            b.setMinimumHeight(56)
            color = theme.RATING_COLORS[int(r)]
            b.setStyleSheet(f"QPushButton {{ background: {color}; color: white; border: none; border-radius: 8px;"
                            f" font-weight: 600; }} QPushButton:hover {{ border: 2px solid white; }}")
            b.clicked.connect(lambda _=False, v=int(r): self.rate(v))
            self.rate_btns[int(r)] = b
        self.rate_row = row(*self.rate_btns.values(), spacing=12)
        self.rate_hint = muted("Tu avais la bonne réponse ? Sois honnête : c'est ce qui décide quand la carte revient. "
                               "(touches 1 à 4)")
        self.rate_hint.setWordWrap(False)
        lay.addWidget(self.reveal_btn)
        lay.addWidget(self.rate_hint)
        lay.addLayout(self.rate_row)

        self.edit_btn = QPushButton("Corriger la carte")
        self.edit_btn.setToolTip("Touche E")
        self.edit_btn.clicked.connect(self.edit)
        self.suspend_btn = QPushButton("Ne plus me la poser")
        self.suspend_btn.setToolTip("La carte est mise de côté (touche S). Tu peux la réactiver depuis "
                                    "« Voir et corriger les cartes ».")
        self.suspend_btn.clicked.connect(self.suspend)
        self.explain_btn = QPushButton("Explique-moi")
        self.explain_btn.setToolTip("L'IA explique cette réponse avec d'autres mots et un exemple (touche X).")
        self.explain_btn.clicked.connect(self.explain)
        self.page_btn = QPushButton("Voir la page du cours")
        self.page_btn.setToolTip("La page du cours d'où vient cette carte (touche P).")
        self.page_btn.clicked.connect(self.show_page)
        self.fix_btn = QPushButton("Carte mal faite ?")
        self.fix_btn.setToolTip("L'IA réécrit la carte à partir de la page du cours ; tu choisis la version à garder "
                                "(touche R).")
        self.fix_btn.clicked.connect(self.fix)
        self.back_btn = QPushButton("Retour")
        self.where.setMinimumWidth(10)
        self.back_btn.setObjectName("primary")
        self.back_btn.clicked.connect(self.finished.emit)
        lay.addLayout(row(self.edit_btn, self.suspend_btn, self.page_btn, self.fix_btn, self.explain_btn, None,
                          self.back_btn))

        # Raccourcis actifs seulement quand la page de révision a le focus.
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for key, fn in (("Space", self.reveal), ("Return", self.reveal), ("E", self.edit), ("S", self.suspend),
                        ("X", self.explain), ("P", self.show_page), ("R", self.fix), ("Escape", self.finished.emit)):
            QShortcut(QKeySequence(key), self, activated=fn, context=ctx)
        for v in range(1, 5):
            QShortcut(QKeySequence(str(v)), self, activated=lambda v=v: self.rate(v), context=ctx)
        for w in (self.question, self.answer, self.explanation):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.typed.installEventFilter(self)  # pendant qu'on tape, les lettres ne sont pas des raccourcis

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        if obj is self.typed and event.type() == QEvent.Type.ShortcutOverride and event.key() != Qt.Key.Key_Escape:
            event.accept()  # la touche va au champ de texte, pas au raccourci
            return True
        return super().eventFilter(obj, event)

    def typing(self) -> bool:
        return self.type_toggle.isChecked()

    def _toggle_typing(self, on: bool) -> None:
        config.save({"type_answers": on})
        if self.card is not None and not self.revealed:
            self.typed.setVisible(on)
            if on:
                self.typed.setFocus()
            else:
                self.setFocus()

    # ----------------------------------------------------------------- séance
    def start(self, deck_ids: list[int], exam: bool, include_known: bool, new_per_day: int,
              card_ids: list[int] | None = None) -> None:
        self.exam = exam
        self.session = Session(self.db, None, new_per_day, deck_ids=deck_ids, cram=exam, include_known=include_known,
                               card_ids=card_ids)
        self.total = self.session.remaining
        self.started = time.monotonic()
        self.labels = {d.id: deck_label(d) for d in self.db.decks()}
        self.subjects = {d.id: d.subject for d in self.db.decks()}
        self.progress.setRange(0, max(1, self.total))
        self.next_card()
        self.setFocus()

    def update_counts(self) -> None:
        s = self.session
        new, learning, review = s.counts()
        if self.exam:
            known = self.total - s.remaining
            self.progress.setValue(known)
            skipped = f" · {s.known_skipped} déjà connues sautées" if s.known_skipped else ""
            html = (f"<b>TOUT REVOIR</b> &nbsp; <span style='color:{theme.GOOD}'>{known} / {self.total} connues</span>"
                    f" &nbsp; <span style='color:{theme.ACCENT_HOVER}'>{new} jamais vues</span>"
                    f" &nbsp; <span style='color:{theme.WARN}'>{learning} à revoir</span>"
                    f" &nbsp; <span style='color:{theme.MUTED}'>{s.done} réponses{skipped}</span>")
        else:
            self.progress.setValue(max(0, self.total - s.remaining))
            html = (f"<span style='color:{theme.ACCENT_HOVER}'>{new} nouvelles</span> &nbsp; "
                    f"<span style='color:{theme.WARN}'>{learning} en cours d'apprentissage</span> &nbsp; "
                    f"<span style='color:{theme.GOOD}'>{review} à revoir</span> &nbsp; "
                    f"<span style='color:{theme.MUTED}'>{s.done} faites</span>")
        self.counts.setText(html)

    def _show_rating(self, visible: bool) -> None:
        for b in (*self.rate_btns.values(), self.rate_hint):
            b.setVisible(visible)
        self.reveal_btn.setVisible(not visible and self.card is not None)

    def next_card(self) -> None:
        self.card = self.session.current(utcnow()) if self.session else None
        self.revealed = False
        self.answer.setVisible(False)
        self.sep.setVisible(False)
        self._request += 1
        self.think.setVisible(self.card is not None)
        self.explanation.setVisible(False)
        self.explain_btn.setVisible(False)
        has = self.card is not None
        for w in (self.edit_btn, self.suspend_btn, self.fix_btn):
            w.setVisible(has)
        self.page_btn.setVisible(has and bool(self.card.page))
        self.typed.clear()
        self.typed.setReadOnly(False)
        self.typed.setVisible(has and self.typing())
        self.check_label.setVisible(False)
        self.verdict = None
        self.back_btn.setVisible(not has)
        if not has:
            self._show_rating(False)
            self.reveal_btn.setVisible(False)
            self.finish()
            return
        c = self.card
        page = f" · p. {c.page}" if c.page else ""
        section = f" · {c.section}" if c.section else ""
        self.where.setText(f"{self.labels.get(c.deck_id, '')}{page}{section}")
        self.kind.setText(KIND_LABEL.get(c.kind, "Question") + (" · nouvelle" if c.is_new else ""))
        show_markdown(self.question, c.question.replace("[...]", "**[ … ]**").replace("[…]", "**[ … ]**"))
        self._show_rating(False)
        self.update_counts()
        self.shown_at = time.monotonic()
        if self.typing() and self.isVisible():
            self.typed.setFocus()

    def reveal(self) -> None:
        if self.card is None or self.revealed or not self.isVisible():
            return
        self.revealed = True
        self.think.setVisible(False)
        show_markdown(self.answer, self.card.answer)
        self.answer.setVisible(True)
        self.sep.setVisible(True)
        self._check_typed()
        iv = preview(self.session.scheduler, self.card, utcnow())
        suggested = {GOOD: 3, CLOSE: 2}.get(self.verdict, 1) if self.verdict not in (None, EMPTY) else None
        for r in Rating:
            mark = "  ✓ conseillé" if int(r) == suggested else ""
            self.rate_btns[int(r)].setText(f"{RATING_LABELS[r]}{mark}\nrevient dans {format_interval(iv[r])}")
            self.rate_btns[int(r)].setToolTip(f"Touche {int(r)}")
        self._show_rating(True)
        self.setFocus()  # les touches 1 à 4 notent la carte
        self.explain_btn.setVisible(True)
        self.explain_btn.setEnabled(not self.ai_busy)

    # -------------------------------------------------------------- réponse tapée
    def _check_typed(self) -> None:
        """Compare la réponse écrite à celle de la carte (sans IA) et affiche le résultat."""
        if not self.typing() or self.card is None:
            return
        typed = self.typed.text()
        self.typed.setReadOnly(True)
        result = check_answer(typed, self.card.answer, self.card.kind)
        self.verdict = result.verdict
        if result.verdict == EMPTY:
            text = f"<span style='color:{theme.MUTED}'>Pas de réponse écrite : compare dans ta tête.</span>"
        elif result.verdict == GOOD:
            text = f"<span style='color:{theme.GOOD}'><b>✓ Juste</b></span> — vérifie quand même la réponse ci-dessus."
        elif result.verdict == CLOSE:
            miss = ", ".join(result.missing[:6])
            text = (f"<span style='color:{theme.WARN}'><b>≈ Presque</b></span>"
                    + (f" — il manque : <i>{miss}</i>" if miss else ""))
        else:
            text = f"<span style='color:{theme.BAD}'><b>✗ Pas tout à fait</b></span> — relis bien la réponse."
        self.check_label.setText(text + f" <span style='color:{theme.MUTED}'>(La note reste ton choix.)</span>")
        self.check_label.setVisible(True)

    # ------------------------------------------------------- IA : explication, réécriture
    def _ai_ready(self, title: str) -> bool:
        """Faux si l'IA de cet ordinateur doit d'abord être téléchargée et que l'utilisateur refuse."""
        if self.engine is None and self.engine_factory is distractors.default_engine \
                and distractors.default_engine_name() == "ia":
            from revise.engines import embedded
            if not embedded.installed() and not confirm(
                    self, title, "L'IA de cet ordinateur n'est pas encore installée : il faut d'abord la télécharger "
                    "(2,5 à 7 Go).\n\nTu peux aussi choisir une autre IA dans « Ajouter un cours ».", "Télécharger"):
                return False
        return True

    def _run_ai(self, kind: str, task) -> None:
        """Lance `task(chat)` dans un fil ; le résultat revient dans `_on_ai` avec `kind`."""
        self.ai_busy = True
        self.explain_btn.setEnabled(False)
        self.fix_btn.setEnabled(False)
        request = self._request

        def work(post) -> None:
            try:
                if self.engine is None:
                    self.engine = self.engine_factory()
                getattr(self.engine, "check", lambda: None)()
                self.engine.progress = lambda message: post((request, kind, f"*{message}*", False))
                post((request, kind, task(self.engine.chat), True))
            except ReviseError as e:
                post((request, kind, e, True))
            except Exception as e:  # une panne de l'IA ne doit pas fermer l'application
                post((request, kind, ReviseError(f"erreur inattendue ({e})"), True))
        self.ai_job.start(work)

    def explain(self) -> None:
        """Demande à l'IA d'expliquer la réponse affichée (dans un fil : la page reste utilisable)."""
        if self.card is None or not self.revealed or not self.isVisible() or self.ai_busy:
            return
        if not self._ai_ready("Explique-moi"):
            return
        self.explanation.setMarkdown("*L'IA réfléchit…*")
        self.explanation.setVisible(True)
        card = self.card
        subject, course = self.subjects.get(card.deck_id, ""), self.labels.get(card.deck_id, "")
        self._run_ai("explain", lambda chat: explain(card.question, card.answer, subject, course, chat))

    def fix(self) -> None:
        """« Carte mal faite ? » : l'IA propose une nouvelle version, l'utilisateur choisit."""
        if self.card is None or not self.isVisible() or self.ai_busy:
            return
        if not self._ai_ready("Carte mal faite ?"):
            return
        card = self.card
        deck = self.db.deck(card.deck_id)
        path = source_file(deck) if deck else None
        page_text = pageview.page_text(path, card.page) if path and card.page else ""
        subject, course = self.subjects.get(card.deck_id, ""), self.labels.get(card.deck_id, "")
        self.explanation.setMarkdown("*L'IA réécrit la carte…*")
        self.explanation.setVisible(True)
        self._run_ai("fix", lambda chat: rewrite(card.question, card.answer, page_text, subject, course, chat))

    def _on_ai(self, message) -> None:
        request, kind, result, final = message
        if final:
            self.ai_busy = False
            self.explain_btn.setEnabled(True)
            self.fix_btn.setEnabled(True)
        if request != self._request:  # l'utilisateur est déjà passé à une autre carte
            return
        if not final:
            self.explanation.setMarkdown(result)
            return
        if isinstance(result, ReviseError):
            show_markdown(self.explanation, f"**{'Pas d’explication' if kind == 'explain' else 'Pas de nouvelle version'}**"
                                            f" : {result}")
        elif kind == "explain":
            show_markdown(self.explanation, f"**Explication de l'IA**\n\n{result}")
        else:
            self.explanation.setVisible(False)
            self.offer_rewrite(*result)

    def offer_rewrite(self, question: str, answer: str, change: str) -> None:
        if self.card is None:
            return
        dlg = RewriteDialog(self.card, question, answer, change, self)
        if dlg.exec():
            self.db.update_card_content(self.card.id, self.card.kind, question, answer, self.card.page)
            self._reload_card()

    def show_page(self) -> None:
        if self.card is None or not self.card.page or not self.isVisible():
            return
        deck = self.db.deck(self.card.deck_id)
        if deck is not None:
            from revise.gui.page_dialog import PageDialog
            PageDialog(self.db, deck, self.card.page, self).exec()

    def stop_engine(self) -> None:
        """Arrête l'IA lancée pour les explications (sans effet s'il n'y en a pas)."""
        engine, self.engine = self.engine, None
        getattr(engine, "close", lambda: None)()

    def rate(self, value: int) -> None:
        if self.card is None or not self.revealed or not self.isVisible():
            return
        duration = min(MAX_DURATION_MS, int((time.monotonic() - self.shown_at) * 1000))
        self.session.answer(self.card, Rating(value), duration)
        self.next_card()

    def suspend(self) -> None:
        if self.card is None or not self.isVisible():
            return
        self.db.set_suspended(self.card.id, True)
        self.session.skip(self.card)
        self.next_card()

    def edit(self) -> None:
        if self.card is None or not self.isVisible():
            return
        dlg = CardEditDialog(self.card, self)
        if dlg.exec():
            kind, q, a, page = dlg.values()
            self.db.update_card_content(self.card.id, kind, q, a, page)
            self._reload_card()

    def _reload_card(self) -> None:
        self.session.refresh(self.card.id)
        fresh = self.db.card(self.card.id)
        self.card = fresh
        if fresh:
            show_markdown(self.question, cloze_question(fresh.question))
            if self.revealed:
                show_markdown(self.answer, fresh.answer)

    def finish(self) -> None:
        minutes = (time.monotonic() - self.started) / 60
        self.where.setText("")
        self.kind.setText("")
        s = self.session
        if s and self.exam and s.done:
            msg = (f"## Tu sais tout !\n\nLes {self.total} cartes ont été notées « Bien » ou « Facile » "
                   f"({s.done} réponses en {minutes:.0f} min).\n\nBon courage pour le contrôle !")
        elif s and self.exam and s.known_skipped:
            msg = (f"## Tu sais déjà tout\n\nLes {s.known_skipped} cartes de ces cours sont déjà connues. "
                   "Coche « Tout revoir repose aussi les cartes déjà connues » pour une dernière passe complète.")
        elif s and s.done:
            msg = (f"## Séance terminée\n\n{s.done} cartes révisées en {minutes:.0f} min, "
                   f"dont {s.new_seen} nouvelles. Reviens demain pour la suite.")
        else:
            msg = ("## Rien à réviser pour l'instant\n\nToutes les cartes de ces cours sont à jour. "
                   "Utilise **Tout revoir** pour les reprendre toutes maintenant, ou fais un **QCM**.")
        self.question.setMarkdown(msg)
        if s:
            self.update_counts()
