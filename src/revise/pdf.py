"""Lecture des PDF : texte par page et découpage en morceaux."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from revise.models import ReviseError

logging.getLogger("pypdf").setLevel(logging.ERROR)  # avertissements de PDF mal formés


@dataclass
class PdfChunk:
    first_page: int  # numéro (1-based) de la première page dans le PDF d'origine
    last_page: int
    data: bytes


def open_pdf(path: Path) -> PdfReader:
    if not path.is_file():
        raise ReviseError(f"Fichier introuvable : {path}")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as e:  # pypdf lève divers types selon le chiffrement
                raise ReviseError(f"{path.name} est protégé par mot de passe") from e
        _ = len(reader.pages)
        return reader
    except PdfReadError as e:
        raise ReviseError(f"{path.name} n'est pas un PDF lisible ({e})") from e


def page_texts(path: Path) -> list[str]:
    reader = open_pdf(path)
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # page corrompue : on l'ignore plutôt que d'échouer
            out.append("")
    return out


def page_count(path: Path) -> int:
    return len(open_pdf(path).pages)


def extract_pages(reader: PdfReader, start: int, end: int) -> bytes:
    """Pages [start, end) (0-based) dans un nouveau PDF en mémoire."""
    writer = PdfWriter()
    for i in range(start, end):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
