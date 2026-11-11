"""Page de révision : une carte à la fois, réponse puis note de 1 à 4."""

from __future__ import annotations

import time

from fsrs import Rating
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QTextBrowser, QVBoxLayout, QWidget)

from revise.db import Card, Database, deck_label, utcnow
from revise.gui import theme
from revise.gui.common import muted, row
from revise.models import KINDS
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        if self.question.toPlainText().strip() and self.answer.toPlainText().strip():
            self.accept()

    def values(self) -> tuple[str, str, str, int | None]:
        return (self.kind.currentData(), self.question.toPlainText().strip(), self.answer.toPlainText().strip(),
                self.page.value() or None)


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

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 20)
        self.where = muted("")
        self.where.setWordWrap(False)
        self.counts = QLabel()
        self.counts.setTextFormat(Qt.TextFormat.RichText)
        quit_btn = QPushButton("Terminer")
        quit_btn.setToolTip("Échap")
        quit_btn.clicked.connect(self.finished.emit)
        lay.addLayout(row(self.where, None, quit_btn))
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
        cl.addWidget(self.question, 3)
        self.sep = QFrame()
        self.sep.setFrameShape(QFrame.Shape.HLine)
        self.sep.setStyleSheet(f"color: {theme.BORDER};")
        cl.addWidget(self.sep)
        self.answer = markdown_view(15)
        cl.addWidget(self.answer, 4)
        lay.addWidget(self.card_frame, 1)

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
        lay.addWidget(self.reveal_btn)
        lay.addLayout(self.rate_row)

        self.edit_btn = QPushButton("Modifier (E)")
        self.edit_btn.clicked.connect(self.edit)
        self.suspend_btn = QPushButton("Suspendre (S)")
        self.suspend_btn.setToolTip("La carte ne sera plus proposée.")
        self.suspend_btn.clicked.connect(self.suspend)
        self.back_btn = QPushButton("Retour aux cours")
        self.where.setMinimumWidth(10)
        self.back_btn.setObjectName("primary")
        self.back_btn.clicked.connect(self.finished.emit)
        lay.addLayout(row(self.edit_btn, self.suspend_btn, None, self.back_btn))

        # Raccourcis actifs seulement quand la page de révision a le focus.
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for key, fn in (("Space", self.reveal), ("Return", self.reveal), ("E", self.edit), ("S", self.suspend),
                        ("Escape", self.finished.emit)):
            QShortcut(QKeySequence(key), self, activated=fn, context=ctx)
        for v in range(1, 5):
            QShortcut(QKeySequence(str(v)), self, activated=lambda v=v: self.rate(v), context=ctx)
        for w in (self.question, self.answer):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ----------------------------------------------------------------- séance
    def start(self, deck_ids: list[int], exam: bool, include_known: bool, new_per_day: int) -> None:
        self.exam = exam
        self.session = Session(self.db, None, new_per_day, deck_ids=deck_ids, cram=exam, include_known=include_known)
        self.total = self.session.remaining
        self.started = time.monotonic()
        self.labels = {d.id: deck_label(d) for d in self.db.decks()}
        self.progress.setVisible(exam)
        self.progress.setRange(0, max(1, self.total))
        self.next_card()
        self.setFocus()

    def update_counts(self) -> None:
        s = self.session
        new, learning, review = s.counts()
        if self.exam:
            known = self.total - s.remaining
            self.progress.setValue(known)
            skipped = f" · {s.known_skipped} déjà sues sautées" if s.known_skipped else ""
            html = (f"<b>MODE EXAMEN</b> &nbsp; <span style='color:#0ca30c'>{known} / {self.total} sues</span>"
                    f" &nbsp; <span style='color:#86b6ef'>{new} jamais vues</span>"
                    f" &nbsp; <span style='color:#fab219'>{learning} à revoir</span>"
                    f" &nbsp; <span style='color:{theme.MUTED}'>{s.done} réponses{skipped}</span>")
        else:
            html = (f"<span style='color:#86b6ef'>{new} nouvelles</span> &nbsp; "
                    f"<span style='color:#fab219'>{learning} en apprentissage</span> &nbsp; "
                    f"<span style='color:#0ca30c'>{review} à réviser</span> &nbsp; "
                    f"<span style='color:{theme.MUTED}'>{s.done} faites</span>")
        self.counts.setText(html)

    def _show_rating(self, visible: bool) -> None:
        for b in self.rate_btns.values():
            b.setVisible(visible)
        self.reveal_btn.setVisible(not visible and self.card is not None)

    def next_card(self) -> None:
        self.card = self.session.current(utcnow()) if self.session else None
        self.revealed = False
        self.answer.setVisible(False)
        self.sep.setVisible(False)
        has = self.card is not None
        for w in (self.edit_btn, self.suspend_btn):
            w.setVisible(has)
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
        self.question.setMarkdown(c.question.replace("[...]", "**[ … ]**").replace("[…]", "**[ … ]**"))
        self._show_rating(False)
        self.update_counts()
        self.shown_at = time.monotonic()

    def reveal(self) -> None:
        if self.card is None or self.revealed or not self.isVisible():
            return
        self.revealed = True
        self.answer.setMarkdown(self.card.answer)
        self.answer.setVisible(True)
        self.sep.setVisible(True)
        iv = preview(self.session.scheduler, self.card, utcnow())
        for r in Rating:
            self.rate_btns[int(r)].setText(f"{int(r)} · {RATING_LABELS[r]}\n{format_interval(iv[r])}")
        self._show_rating(True)

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
            self.session.refresh(self.card.id)
            fresh = self.db.card(self.card.id)
            self.card = fresh
            if fresh:
                self.question.setMarkdown(fresh.question)
                if self.revealed:
                    self.answer.setMarkdown(fresh.answer)

    def finish(self) -> None:
        minutes = (time.monotonic() - self.started) / 60
        self.where.setText("")
        self.kind.setText("")
        s = self.session
        if s and self.exam and s.done:
            msg = (f"## Tout est su !\n\nLes {self.total} cartes ont été notées « Bien » ou « Facile » "
                   f"({s.done} réponses en {minutes:.0f} min).\n\nBon courage pour le contrôle !")
        elif s and self.exam and s.known_skipped:
            msg = (f"## Déjà tout su\n\nLes {s.known_skipped} cartes de ces cours sont déjà sues. "
                   "Coche « Revoir aussi les cartes déjà sues » pour une dernière passe complète.")
        elif s and s.done:
            msg = (f"## Séance terminée\n\n{s.done} cartes révisées en {minutes:.0f} min, "
                   f"dont {s.new_seen} nouvelles. Reviens demain pour la suite.")
        else:
            msg = ("## Rien à réviser pour l'instant\n\nToutes les cartes de ces cours sont à jour. "
                   "Utilise le **mode examen** pour tout revoir maintenant.")
        self.question.setMarkdown(msg)
        if s:
            self.update_counts()
