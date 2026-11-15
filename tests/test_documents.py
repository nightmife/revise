"""Cours en PowerPoint, Word et texte (fichiers fabriqués à la main, sans bibliothèque)."""

import zipfile

import pytest

from revise import cli, documents
from revise.db import Database
from revise.models import ReviseError
from revise.pdf import page_texts

NS_P = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def slide(title: str, *bullets: str, footer: str = "") -> str:
    def shape(kind, texts):
        ps = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in texts)
        return f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="{kind}"/></p:nvPr></p:nvSpPr><p:txBody>{ps}</p:txBody></p:sp>'
    body = shape("title", [title]) + shape("body", bullets) + (shape("sldNum", [footer]) if footer else "")
    return f'<p:sld {NS_P}><p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>'


def make_pptx(path, slides: dict[str, str], order: list[str]):
    """`slides` : nom de fichier → XML ; `order` : ordre de la présentation."""
    rels = "".join(f'<Relationship Id="rId{i}" Target="slides/{name}"/>' for i, name in enumerate(order, 1))
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, len(order) + 1))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", f"<p:presentation {NS_P}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>")
        z.writestr("ppt/_rels/presentation.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f"{rels}</Relationships>")
        for name, xml in slides.items():
            z.writestr(f"ppt/slides/{name}", xml)
    return path


def make_docx(path, paragraphs: list[tuple[str, bool]]):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p>{'<w:pPr><w:numPr/></w:pPr>' if bullet else ''}<w:r><w:t>{text[:5]}</w:t></w:r>"
                   f"<w:r><w:t>{text[5:]}</w:t></w:r></w:p>" for text, bullet in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {w}><w:body>{body}</w:body></w:document>")
    return path


def test_pptx_one_page_per_slide_in_presentation_order(tmp_path):
    f = make_pptx(tmp_path / "cours.pptx",
                  {"slide1.xml": slide("Les files", "Une file est de type FIFO"),
                   "slide2.xml": slide("Les piles", "Une pile est de type LIFO", "Empiler &amp; dépiler", footer="12")},
                  order=["slide2.xml", "slide1.xml"])                   # diapositives réordonnées par l'auteur
    assert page_texts(f) == ["Les piles\n• Une pile est de type LIFO\n• Empiler & dépiler",
                             "Les files\n• Une file est de type FIFO"]


def test_pptx_without_order_falls_back_to_file_numbers(tmp_path):
    f = tmp_path / "vrac.pptx"
    with zipfile.ZipFile(f, "w") as z:
        for n in (10, 2, 1):
            z.writestr(f"ppt/slides/slide{n}.xml", slide(f"Titre {n}"))
    assert page_texts(f) == ["Titre 1", "Titre 2", "Titre 10"]


def test_docx_and_text_are_cut_into_pages(tmp_path):
    f = make_docx(tmp_path / "cours.docx", [("Définition d'une pile", False), ("structure LIFO", True), ("", False)])
    assert page_texts(f) == ["Définition d'une pile\n• structure LIFO"]
    long = make_docx(tmp_path / "long.docx", [("mot " * 150, False)] * 6)
    pages = page_texts(long)
    assert len(pages) == 2 and all(len(p) <= documents.PAGE_CHARS for p in pages)

    txt = tmp_path / "notes.md"
    txt.write_bytes("# Piles\r\n\r\nUne pile est LIFO.\r\n".encode("utf-8-sig"))
    assert page_texts(txt) == ["# Piles\nUne pile est LIFO."]
    old = tmp_path / "vieux.txt"
    old.write_bytes("Définition : énoncé".encode("cp1252"))
    assert page_texts(old) == ["Définition : énoncé"]


def test_unreadable_files_are_reported(tmp_path):
    fake = tmp_path / "faux.pptx"
    fake.write_bytes(b"pas un zip")
    empty = tmp_path / "vide.pptx"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("autre.txt", "x")
    broken = make_pptx(tmp_path / "casse.pptx", {"slide1.xml": "<p:sld"}, order=["slide1.xml"])
    notword = tmp_path / "pas-word.docx"
    with zipfile.ZipFile(notword, "w") as z:
        z.writestr("autre.txt", "x")
    for f in (fake, empty, broken, notword, tmp_path / "absent.docx"):
        with pytest.raises(ReviseError):
            page_texts(f)
    with pytest.raises(ReviseError, match=r"\.pptx"):
        documents.page_texts(tmp_path / "ancien.ppt")
    assert documents.is_supported(tmp_path / "A.PPTX") and not documents.is_supported(tmp_path / "a.ppt")


def test_import_pptx_with_simple_engine(tmp_path, capsys):
    f = make_pptx(tmp_path / "[Algo] CM3 - Piles.pptx",
                  {"slide1.xml": slide("Les piles", "Une pile est une structure de données de type LIFO",
                                       "Une file est une structure de données de type FIFO")}, order=["slide1.xml"])
    base = tmp_path / "x.db"
    assert cli.main(["--base", str(base), "importer", str(f), "--moteur", "simple"]) == 0
    db = Database(base)
    [deck] = db.decks()
    assert (deck.subject, deck.title) == ("Algo", "CM3 - Piles") and len(db.cards()) >= 2
    assert all(c.page == 1 for c in db.cards())
    db.close()
    old = tmp_path / "cours.ppt"
    old.write_bytes(b"x")
    assert cli.main(["--base", str(base), "importer", str(old), "--moteur", "simple"]) == 1
    assert ".pptx" in capsys.readouterr().err
