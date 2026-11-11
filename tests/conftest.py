from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfWriter

from revise.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


def blank_pdf(path: Path, pages: int) -> Path:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    w.write(buf)
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture
def pdf_factory(tmp_path: Path):
    def make(pages: int, name: str = "cours.pdf") -> Path:
        return blank_pdf(tmp_path / name, pages)
    return make
