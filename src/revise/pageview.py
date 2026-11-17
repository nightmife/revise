"""Page du cours d'où vient une carte : image (si la bibliothèque pypdfium2 est là) ou texte."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from revise.models import ReviseError


@dataclass
class PageImage:
    data: bytes
    width: int
    height: int
    stride: int
    channels: int   # 3 = RVB, 4 = RVBA


def can_render() -> bool:
    try:
        import pypdfium2  # noqa: F401
    except Exception:  # absente, ou bibliothèque native illisible
        return False
    return True


def render_page(path: Path, page: int, scale: float = 2.0) -> PageImage | None:
    """Image de la page `page` (à partir de 1) d'un PDF, ou None si c'est impossible ici."""
    if path.suffix.lower() != ".pdf" or not can_render():
        return None
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page <= len(doc):
                return None
            bitmap = doc[page - 1].render(scale=scale, rev_byteorder=True)
            return PageImage(bytes(bitmap.buffer), bitmap.width, bitmap.height, bitmap.stride, bitmap.n_channels)
        finally:
            doc.close()
    except Exception:  # PDF abîmé, protégé… : on se rabat sur le texte
        return None


def page_text(path: Path, page: int) -> str:
    """Texte de la page (une diapositive pour un PowerPoint), "" si illisible."""
    from revise.pdf import page_texts
    try:
        texts = page_texts(path)
    except ReviseError:
        return ""
    return texts[page - 1] if 1 <= page <= len(texts) else ""
