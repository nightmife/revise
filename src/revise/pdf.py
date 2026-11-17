"""Lecture des cours : texte par page (PDF ici ; PowerPoint, Word et texte dans `documents.py`)."""

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
    """Texte du cours, page par page (diapositive par diapositive pour un PowerPoint)."""
    if path.suffix.lower() != ".pdf":
        from revise import documents
        return documents.page_texts(path)
    reader = open_pdf(path)
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # page corrompue : on l'ignore plutôt que d'échouer
            out.append("")
    return out


MIN_IMAGE_PIXELS = 200 * 150   # plus petit : puce, icône, filet décoratif
LOW_TEXT_CHARS = 60


def _page_images(page) -> set[int]:
    """Identifiants des images assez grandes posées sur la page."""
    found: set[int] = set()
    try:
        resources = page.get("/Resources")
        xobjects = resources.get_object().get("/XObject") if resources is not None else None
        if xobjects is None:
            return found
        for ref in xobjects.get_object().values():
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Image" and int(obj.get("/Width", 0)) * int(obj.get("/Height", 0)) >= MIN_IMAGE_PIXELS:
                found.add(getattr(ref, "idnum", id(obj)))
    except Exception:  # PDF mal formé : on fait comme s'il n'y avait pas d'image
        pass
    return found


def visual_pages(path: Path, texts: list[str]) -> set[int]:
    """Numéros (à partir de 1) des pages qu'il faut *voir* pour les comprendre : pages scannées (une image,
    presque pas de texte) et pages qui portent un schéma ou une photo. Une image répétée sur plus de la
    moitié des pages (logo, fond du modèle de diapositives) ne compte pas comme un schéma."""
    if path.suffix.lower() != ".pdf":
        return set()
    try:
        images = [_page_images(page) for page in open_pdf(path).pages]
    except ReviseError:
        return set()
    seen: dict[int, int] = {}
    for ids in images:
        for i in ids:
            seen[i] = seen.get(i, 0) + 1
    decoration = {i for i, n in seen.items() if len(images) >= 4 and n > len(images) / 2}
    out = set()
    for number, (ids, text) in enumerate(zip(images, texts), start=1):
        if ids - decoration or (ids and len(text.strip()) < LOW_TEXT_CHARS):
            out.add(number)
    return out


def pages_pdf(path: Path, first: int, last: int) -> bytes:
    """Les pages `first` à `last` (numérotées à partir de 1) dans un nouveau PDF."""
    return extract_pages(open_pdf(path), first - 1, last)


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


BOILERPLATE_SHARE = 0.3   # une ligne présente sur au moins 30 % des pages est un en-tête ou un pied de page
MIN_PAGES_FOR_BOILERPLATE = 6


def _line_key(line: str) -> str:
    """Ligne comparable d'une page à l'autre : sans chiffres (numéro de page, date) ni espaces en trop."""
    return " ".join("".join("#" if ch.isdigit() else ch for ch in line.lower()).split())


def clean_pages(texts: list[str], slides: bool = True) -> list[str]:
    """Texte des pages débarrassé de ce qui ne s'apprend pas, sans changer la numérotation :
    - les lignes répétées sur une grande partie des pages (en-tête, nom de l'université, pied de page avec son
      numéro de page) ;
    - les pages « à étapes » d'une présentation (chaque page reprend la précédente et ajoute une ligne) :
      seule la dernière est gardée, les autres deviennent vides.
    `slides` : faux pour un document Word ou un texte, qui n'a ni en-têtes répétés ni pages à étapes.
    Moins de texte = moins d'appels à l'IA et des cartes sans doublon."""
    pages = [[ln.strip() for ln in t.splitlines() if ln.strip()] for t in texts]
    if not slides:
        return ["\n".join(lines) for lines in pages]
    if len(pages) >= MIN_PAGES_FOR_BOILERPLATE:
        exact: dict[str, int] = {}
        masked: dict[str, int] = {}
        for lines in pages:
            for key in {" ".join(ln.lower().split()) for ln in lines if len(ln) <= 120}:
                exact[key] = exact.get(key, 0) + 1
            # Numéros (de page, de date) qui changent : seulement dans un pied de page (dernière ligne).
            for key in {_line_key(ln) for ln in lines[-1:] if len(ln) <= 120 and len(ln.split()) >= 3}:
                masked[key] = masked.get(key, 0) + 1
        limit = max(3, BOILERPLATE_SHARE * len(pages))

        def repeated(i: int, line: str, count: int) -> bool:
            if len(line) > 120:
                return False
            if exact.get(" ".join(line.lower().split()), 0) >= limit:
                return True
            return i == count - 1 and len(line.split()) >= 3 and masked.get(_line_key(line), 0) >= limit
        pages = [[ln for i, ln in enumerate(lines) if not repeated(i, ln, len(lines))] for lines in pages]
    out = ["\n".join(lines) for lines in pages]
    keys = [{" ".join(ln.split()) for ln in lines} for lines in pages]
    for i in range(len(pages) - 1):
        if keys[i] and keys[i] <= keys[i + 1]:
            out[i] = ""
    return out
