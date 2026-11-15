"""Date d'examen d'un cours : jours restants et nombre de nouvelles cartes par jour pour tout voir à temps."""

from __future__ import annotations

import math
from datetime import date


def parse_date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def days_left(exam_date: str | None, today: date | None = None) -> int | None:
    """Jours jusqu'à l'examen (0 = aujourd'hui, négatif = passé) ; None sans date valable."""
    exam = parse_date(exam_date)
    return (exam - (today or date.today())).days if exam else None


def countdown(days: int) -> str:
    if days < 0:
        return "passé"
    if days == 0:
        return "aujourd'hui"
    if days == 1:
        return "demain"
    return f"J-{days}"


def new_per_day(new_cards: int, days: int) -> int:
    """Nouvelles cartes à voir chaque jour (aujourd'hui compris) pour avoir tout vu avant l'examen.
    La veille est gardée pour tout revoir ; un examen passé ne demande plus rien."""
    if new_cards <= 0 or days < 0:
        return 0
    return math.ceil(new_cards / max(1, days - 1))


def readiness(known: int, total: int) -> int:
    """Pourcentage de cartes sues."""
    return round(100 * known / total) if total else 0
