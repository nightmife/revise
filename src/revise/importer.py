"""Import d'un PDF : utilisé par la ligne de commande et par l'application graphique."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from revise.db import Database, file_sha256
from revise.engines import Progress
from revise.engines.simple import title_from_filename
from revise.models import CardDraft, ReviseError


@dataclass
class ImportResult:
    pdf: Path
    deck_id: int | None
    cards: list[CardDraft]
    title: str
    skipped: bool = False  # déjà importé


def guess_subject(pdf: Path) -> str:
    """« [LIFAPSD] CM8 - Pile.pdf » → « LIFAPSD », sinon le nom du dossier."""
    m = re.match(r"^\s*\[([^\]]+)\]", pdf.name)
    return m.group(1).strip() if m else pdf.resolve().parent.name


def course_title(pdf: Path, fallback: str) -> str:
    named = title_from_filename(pdf.stem)
    return named if len(named) >= 4 and any(ch.isalpha() for ch in named) else (fallback or pdf.stem)


def already_imported(db: Database, pdf: Path) -> bool:
    return pdf.is_file() and db.find_deck_by_hash(file_sha256(pdf)) is not None


def import_pdf(db: Database, engine, pdf: Path, subject: str | None, progress: Progress,
               title: str | None = None, force: bool = False) -> ImportResult:
    pdf = pdf.expanduser()
    if not pdf.is_file():
        raise ReviseError(f"Fichier introuvable : {pdf}")
    sha = file_sha256(pdf)
    existing = db.find_deck_by_hash(sha)
    if existing and not force:
        return ImportResult(pdf, existing.id, [], existing.title, skipped=True)
    subject = subject or guess_subject(pdf)
    gen_title, cards = engine.generate(pdf, subject, progress)
    if not cards:
        raise ReviseError(f"Aucune carte trouvée dans {pdf.name}.")
    final_title = title or course_title(pdf, gen_title)
    if existing and force:
        db.delete_deck(existing.id)
    deck_id = db.add_deck(subject, final_title, str(pdf.resolve()), sha, engine.name, cards)
    return ImportResult(pdf, deck_id, cards, final_title)
