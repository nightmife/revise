"""Séance de révision dans le terminal (Textual)."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from fsrs import Rating
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Markdown, Static

from revise import editfmt
from revise.db import Database, utcnow
from revise.models import ReviseError
from revise.scheduler import RATING_LABELS, Session, format_interval, preview

KIND_LABEL = {"qa": "Question", "cloze": "Texte à trous", "code": "Code"}
MAX_DURATION_MS = 60_000


def open_in_editor(text: str, suffix: str = ".md") -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(text)
        path = Path(f.name)
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=False)
        return path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)


class ReviewApp(App):
    CSS = """
    Screen { background: #1a1a19; }
    #top { height: 1; padding: 0 2; color: #a8a69e; }
    #counts { height: 1; padding: 0 2; }
    #card { margin: 1 2; padding: 1 2; border: round #52514e; height: 1fr; }
    #kind { color: #a8a69e; height: 1; }
    #sep { height: 1; color: #52514e; display: none; }
    #answer { display: none; }
    #ratings { height: 3; padding: 1 2 0 2; }
    #done { margin: 2 4; }
    Markdown { background: #1a1a19; margin: 0; }
    #question MarkdownParagraph { text-style: bold; }
    """

    BINDINGS = [
        Binding("space", "reveal", "Afficher la réponse"),
        Binding("enter", "reveal", "Afficher", show=False),
        Binding("1", "rate(1)", "À revoir", show=False),
        Binding("2", "rate(2)", "Difficile", show=False),
        Binding("3", "rate(3)", "Bien", show=False),
        Binding("4", "rate(4)", "Facile", show=False),
        Binding("e", "edit", "Modifier"),
        Binding("s", "suspend_card", "Suspendre"),
        Binding("q", "quit", "Quitter"),
    ]

    def __init__(self, db: Database, subject: str | None, new_per_day: int, deck_ids: list[int] | None = None,
                 cram: bool = False):
        super().__init__()
        self.db = db
        self.cram = cram
        self.session = Session(db, subject, new_per_day, deck_ids=deck_ids, cram=cram)
        self.total = self.session.remaining
        self.card = None
        self.revealed = False
        self.shown_at = 0.0
        self.started = time.monotonic()
        self.deck_titles = {d.id: (d.subject, d.title) for d in db.decks()}

    def compose(self) -> ComposeResult:
        yield Static(id="top")
        yield Static(id="counts")
        with VerticalScroll(id="card"):
            yield Static(id="kind")
            yield Markdown(id="question")
            yield Static("─" * 40, id="sep")
            yield Markdown(id="answer")
        yield Static(id="ratings")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "revise"
        self.next_card()

    # ---------------------------------------------------------------- affichage
    def update_counts(self) -> None:
        new, learning, review = self.session.counts()
        if self.cram:
            known = self.total - self.session.remaining
            self.query_one("#counts", Static).update(
                f"[b]MODE EXAMEN[/]   [#0ca30c]{known}/{self.total} sues[/]   [#86b6ef]{new} jamais vues[/]   "
                f"[#fab219]{learning} à revoir[/]   [#a8a69e]{review} déjà vues · {self.session.done} réponses[/]")
            return
        self.query_one("#counts", Static).update(
            f"[#86b6ef]{new} nouvelles[/]   [#fab219]{learning} en apprentissage[/]   "
            f"[#0ca30c]{review} à réviser[/]   [#a8a69e]· {self.session.done} faites[/]")

    def next_card(self) -> None:
        self.card = self.session.current(utcnow())
        self.revealed = False
        if self.card is None:
            self.finish()
            return
        c = self.card
        subj, title = self.deck_titles.get(c.deck_id, ("", ""))
        where = f" · p. {c.page}" if c.page else ""
        section = f" · {c.section}" if c.section else ""
        self.query_one("#top", Static).update(f"{subj} · {title}{where}{section}")
        self.query_one("#kind", Static).update(KIND_LABEL.get(c.kind, "Question") + (" · nouvelle" if c.is_new else ""))
        question = c.question.replace("[...]", "**[ … ]**").replace("[…]", "**[ … ]**")
        self.query_one("#question", Markdown).update(question)
        self.query_one("#answer", Markdown).update("")
        self.query_one("#answer").display = False
        self.query_one("#sep").display = False
        self.query_one("#ratings", Static).update("[#a8a69e]Espace : afficher la réponse[/]")
        self.update_counts()
        self.shown_at = time.monotonic()

    def action_reveal(self) -> None:
        if self.card is None or self.revealed:
            return
        self.revealed = True
        self.query_one("#answer", Markdown).update(self.card.answer)
        self.query_one("#answer").display = True
        self.query_one("#sep").display = True
        iv = preview(self.session.scheduler, self.card, utcnow())
        colors = {Rating.Again: "#d03b3b", Rating.Hard: "#ec835a", Rating.Good: "#0ca30c", Rating.Easy: "#3987e5"}
        parts = [f"[b {colors[r]}]{int(r)}[/] {RATING_LABELS[r]} [#a8a69e]({format_interval(iv[r])})[/]"
                 for r in Rating]
        self.query_one("#ratings", Static).update("     ".join(parts))

    def action_rate(self, value: int) -> None:
        if self.card is None or not self.revealed:
            return
        duration = min(MAX_DURATION_MS, int((time.monotonic() - self.shown_at) * 1000))
        self.session.answer(self.card, Rating(value), duration)
        self.next_card()

    def action_suspend_card(self) -> None:
        if self.card is None:
            return
        self.db.set_suspended(self.card.id, True)
        self.session.skip(self.card)
        self.notify("Carte suspendue (elle ne sera plus proposée).")
        self.next_card()

    def action_edit(self) -> None:
        if self.card is None:
            return
        c = self.card
        with self.suspend():
            text = open_in_editor(editfmt.render(self.deck_titles.get(c.deck_id, ("", ""))[1], [c]))
        try:
            blocks = [b for b in editfmt.parse(text) if b.card_id == c.id]
            if not blocks:
                self.notify("Carte inchangée (bloc introuvable).", severity="warning")
                return
            b = blocks[0]
            self.db.update_card_content(c.id, b.kind, b.question, b.answer, b.page)
            self.session.refresh(c.id)
            self.notify("Carte modifiée.")
        except ReviseError as e:
            self.notify(f"Modification ignorée : {e}", severity="error")
        self.revealed = False
        self.next_card()

    def finish(self) -> None:
        minutes = (time.monotonic() - self.started) / 60
        self.query_one("#top", Static).update("")
        self.query_one("#kind", Static).update("")
        self.query_one("#answer").display = False
        self.query_one("#sep").display = False
        if self.cram and self.session.done:
            msg = (f"## Tout est su !\n\nLes {self.total} cartes ont été notées « Bien » ou « Facile » "
                   f"({self.session.done} réponses en {minutes:.0f} min). Bon courage pour le contrôle !\n\n"
                   "Relance `revise reviser --examen …` juste avant pour une dernière passe.")
        elif self.session.done:
            msg = (f"## Séance terminée\n\n{self.session.done} cartes révisées en {minutes:.0f} min, "
                   f"dont {self.session.new_seen} nouvelles.\n\nReviens demain : `revise stats` pour voir la suite.")
        else:
            msg = "## Rien à réviser pour l'instant\n\nToutes les cartes sont à jour. Importe un nouveau cours ou reviens plus tard."
        self.query_one("#question", Markdown).update(msg)
        self.query_one("#ratings", Static).update("[#a8a69e]q : quitter[/]")
        self.update_counts()


def run(db: Database, subject: str | None, new_per_day: int, deck_ids: list[int] | None = None,
        cram: bool = False) -> int:
    app = ReviewApp(db, subject, new_per_day, deck_ids, cram)
    app.run()
    return app.session.done
