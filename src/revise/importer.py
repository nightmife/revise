"""Import d'un cours (PDF, PowerPoint, Word, texte) : utilisé par la ligne de commande et par l'application graphique."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from revise import documents
from revise.db import Database, file_sha256
from revise.engines import Progress
from revise.engines.simple import title_from_filename
from revise.models import CardDraft, ReviseError

# Version de la fabrication des cartes : à augmenter quand les cartes ou les QCM fabriqués changent nettement.
# Les cours fabriqués avant sont signalés « à mettre à jour » dans « Mes cours ».
GENERATOR_VERSION = 2  # 0.9 : moteur sans IA refait, pages nettoyées avant l'IA


@dataclass
class ImportResult:
    pdf: Path
    deck_id: int | None
    cards: list[CardDraft]
    title: str
    skipped: bool = False  # déjà importé


# Dossiers fourre-tout : leur nom ne dit rien de la matière.
GENERIC_FOLDERS = {"downloads", "téléchargements", "telechargements", "documents", "desktop", "bureau", "tmp", "temp"}


def guess_subject(pdf: Path) -> str:
    """« [LIFAPSD] CM8 - Pile.pdf » → « LIFAPSD », sinon le nom du dossier (« Mes cours » pour un dossier
    fourre-tout comme Téléchargements)."""
    m = re.match(r"^\s*\[([^\]]+)\]", pdf.name)
    if m:
        return m.group(1).strip()
    folder = pdf.resolve().parent.name
    return "Mes cours" if folder.lower() in GENERIC_FOLDERS or not folder else folder


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
    if not documents.is_supported(pdf):
        raise ReviseError(documents.unsupported_message(pdf))
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
    deck_id = db.add_deck(subject, final_title, str(pdf.resolve()), sha, engine.name, cards, GENERATOR_VERSION)
    return ImportResult(pdf, deck_id, cards, final_title)


@dataclass
class UpdateResult:
    deck_id: int
    kept: int      # cartes qui gardent la progression
    added: int     # nouvelles cartes
    removed: int   # anciennes cartes sans équivalent


def is_outdated(deck) -> bool:
    """Cours fabriqué par une ancienne version de l'application (ou reçu d'un autre)."""
    return deck.gen_version is None or deck.gen_version < GENERATOR_VERSION


def source_file(deck) -> Path | None:
    """Fichier du cours s'il est toujours là."""
    if deck.source:
        p = Path(deck.source)
        if p.is_file():
            return p
    return None


def update_deck(db: Database, engine, deck_id: int, progress: Progress, path: Path | None = None) -> UpdateResult:
    """Refait les cartes (et les QCM) d'un cours déjà importé, à partir de son fichier (ou de `path`, sa nouvelle
    version), sans perdre la progression : une nouvelle carte qui dit la même chose qu'une ancienne reprend son
    planning et son historique."""
    from revise.matching import match_cards

    deck = db.deck(deck_id)
    if deck is None:
        raise ReviseError("Ce cours n'existe plus.")
    pdf = Path(path).expanduser() if path else source_file(deck)
    if pdf is None:
        raise ReviseError(f"Le fichier du cours « {deck.title} » est introuvable"
                          + (f" ({deck.source})" if deck.source else "") + " : choisis-le à nouveau.")
    if not pdf.is_file():
        raise ReviseError(f"Fichier introuvable : {pdf}")
    if not documents.is_supported(pdf):
        raise ReviseError(documents.unsupported_message(pdf))
    sha = file_sha256(pdf)
    other = db.find_deck_by_hash(sha)
    if other is not None and other.id != deck_id:
        raise ReviseError(f"{pdf.name} est déjà le fichier d'un autre cours (« {other.title} »).")
    _, cards = engine.generate(pdf, deck.subject, progress)
    if not cards:
        raise ReviseError(f"Aucune carte trouvée dans {pdf.name}.")
    old = db.cards(deck_id=deck_id)
    matches = match_cards(old, cards)
    kept, added, removed = db.replace_deck_cards(deck_id, cards, matches, source=str(pdf.resolve()), sha=sha,
                                                 engine=engine.name, gen_version=GENERATOR_VERSION)
    return UpdateResult(deck_id, kept, added, removed)
