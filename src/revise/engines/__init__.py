"""Moteurs de génération de cartes."""

from __future__ import annotations

from typing import Callable, Protocol

from pathlib import Path

from revise.models import CardDraft

Progress = Callable[[str], None]


class Engine(Protocol):
    name: str

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        """Retourne (titre du cours, cartes)."""
        ...
