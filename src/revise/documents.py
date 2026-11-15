"""Lecture des cours qui ne sont pas des PDF : PowerPoint (.pptx), Word (.docx), texte (.txt, .md).

Tout est rendu sous la même forme que pour un PDF : une liste de « pages » de texte (une diapositive
= une page ; un document Word ou un texte est découpé en pages d'environ une demi-feuille)."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from revise.models import ReviseError

SUPPORTED = (".pdf", ".pptx", ".docx", ".txt", ".md")
OLD_FORMATS = {".ppt": "PowerPoint (.pptx)", ".doc": "Word (.docx)", ".odp": "PowerPoint (.pptx) ou PDF",
               ".odt": "Word (.docx) ou PDF", ".key": "PDF", ".pages": "PDF"}
PAGE_CHARS = 1800                    # taille d'une « page » de document Word ou de texte
MAX_MEMBER_BYTES = 60 * 1024 * 1024  # un fichier XML plus gros que ça n'est pas un cours
MAX_TEXT_BYTES = 20 * 1024 * 1024

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


def unsupported_message(path: Path) -> str:
    better = OLD_FORMATS.get(path.suffix.lower())
    if better:
        return f"{path.name} : ce format n'est pas lu. Enregistre-le en {better}, puis réessaie."
    return f"{path.name} : ce type de fichier n'est pas lu (PDF, PowerPoint .pptx, Word .docx, texte)."


def _xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    info = archive.getinfo(name)  # KeyError si absent
    if info.file_size > MAX_MEMBER_BYTES:
        raise ReviseError("fichier trop volumineux")
    return ElementTree.fromstring(archive.read(info))


def _open(path: Path) -> zipfile.ZipFile:
    if not path.is_file():
        raise ReviseError(f"Fichier introuvable : {path}")
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ReviseError(f"{path.name} n'est pas un fichier lisible (abîmé, ou protégé par mot de passe ?)") from e


# --------------------------------------------------------------- PowerPoint ---

def _slide_names(archive: zipfile.ZipFile) -> list[str]:
    """Fichiers des diapositives, dans l'ordre de la présentation (pas celui de leur numéro de fichier)."""
    try:
        rels = {r.get("Id"): r.get("Target") for r in _xml(archive, "ppt/_rels/presentation.xml.rels").iter(f"{REL}Relationship")}
        order = [rels.get(s.get(f"{R}id")) for s in _xml(archive, "ppt/presentation.xml").iter(f"{P}sldId")]
        names = []
        for target in order:
            if target:
                name = target.lstrip("/") if target.startswith("/") else str(PurePosixPath("ppt") / target)
                if name in archive.namelist():
                    names.append(name)
        if names:
            return names
    except (KeyError, ElementTree.ParseError):
        pass
    found = [n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    return sorted(found, key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()))


def _paragraph(p: ElementTree.Element) -> str:
    parts = []
    for node in p.iter():
        if node.tag == f"{A}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{A}br":
            parts.append(" ")
    return " ".join("".join(parts).split())


def _slide_text(root: ElementTree.Element) -> str:
    lines = []
    for shape in root.iter(f"{P}sp"):
        ph = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
        kind = ph.get("type", "body") if ph is not None else ""
        if kind in ("sldNum", "dt", "ftr", "hdr"):  # numéro, date, pied de page
            continue
        for p in shape.iter(f"{A}p"):
            text = _paragraph(p)
            if text:
                lines.append(text if kind in ("title", "ctrTitle", "subTitle") else f"• {text}")
    for cell in root.iter(f"{A}tc"):  # tableaux
        text = " ".join(filter(None, (_paragraph(p) for p in cell.iter(f"{A}p"))))
        if text:
            lines.append(f"• {text}")
    return "\n".join(lines)


def pptx_pages(path: Path) -> list[str]:
    try:
        with _open(path) as archive:
            names = _slide_names(archive)
            if not names:
                raise ReviseError(f"{path.name} ne contient aucune diapositive.")
            return [_slide_text(_xml(archive, name)) for name in names]
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile, OSError) as e:
        raise ReviseError(f"{path.name} n'est pas une présentation PowerPoint lisible ({e}).") from e


# --------------------------------------------------------------------- Word ---

def _word_paragraph(p: ElementTree.Element) -> str:
    parts = []
    for node in p.iter():
        if node.tag == f"{W}t" and node.text:
            parts.append(node.text)
        elif node.tag in (f"{W}tab", f"{W}br", f"{W}cr"):
            parts.append(" ")
    text = " ".join("".join(parts).split())
    if text and p.find(f"{W}pPr/{W}numPr") is not None:
        return f"• {text}"
    return text


def paginate(paragraphs: list[str], size: int = PAGE_CHARS) -> list[str]:
    """Regroupe des paragraphes en pages d'environ `size` caractères, sans couper un paragraphe."""
    pages: list[str] = []
    current: list[str] = []
    length = 0
    for text in paragraphs:
        text = text.strip()
        if not text:
            continue
        if current and length + len(text) > size:
            pages.append("\n".join(current))
            current, length = [], 0
        current.append(text)
        length += len(text) + 1
    if current:
        pages.append("\n".join(current))
    return pages


def docx_pages(path: Path) -> list[str]:
    try:
        with _open(path) as archive:
            root = _xml(archive, "word/document.xml")
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile, OSError) as e:
        raise ReviseError(f"{path.name} n'est pas un document Word lisible ({e}).") from e
    return paginate([_word_paragraph(p) for p in root.iter(f"{W}p")])


# -------------------------------------------------------------------- texte ---

def text_pages(path: Path) -> list[str]:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise ReviseError(f"{path.name} est trop gros pour un cours en texte.")
        raw = path.read_bytes()
    except OSError as e:
        raise ReviseError(f"Impossible de lire {path.name} ({e.strerror or e})") from e
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")  # vieux fichiers Windows
    return paginate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def page_texts(path: Path) -> list[str]:
    """Texte page par page d'un cours qui n'est pas un PDF."""
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        return pptx_pages(path)
    if suffix == ".docx":
        return docx_pages(path)
    if suffix in (".txt", ".md"):
        return text_pages(path)
    raise ReviseError(unsupported_message(path))
