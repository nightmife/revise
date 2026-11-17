"""Moteurs de génération de cartes."""

from __future__ import annotations

from typing import Callable, Protocol

from pathlib import Path

from revise.models import CardDraft

Progress = Callable[[str], None]


class Step(str):
    """Message d'avancement qui porte aussi la part du travail déjà faite (0 à 1).

    Reste une chaîne : un `Progress` qui ne connaît que le texte l'affiche tel quel.
    `phase` = "download" pour un téléchargement (sa barre est la sienne, pas celle de l'import)."""

    fraction: float | None
    phase: str

    def __new__(cls, text: str, fraction: float | None = None, phase: str = "work") -> Step:
        obj = super().__new__(cls, text)
        obj.fraction = None if fraction is None else min(1.0, max(0.0, float(fraction)))
        obj.phase = phase
        return obj


def fraction_of(message: str) -> float | None:
    return getattr(message, "fraction", None)


def scaled(progress: Progress, start: float, end: float) -> Progress:
    """`progress` pour une étape qui occupe la tranche [start, end] du travail total."""
    def report(message: str) -> None:
        f = fraction_of(message)
        if f is None or getattr(message, "phase", "work") != "work":
            progress(message)
        else:
            progress(Step(str(message), start + (end - start) * f))
    return report


class Engine(Protocol):
    name: str

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        """Retourne (titre du cours, cartes)."""
        ...
