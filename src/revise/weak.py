"""« Mes points faibles » : les cartes souvent ratées (révisions, QCM, examens blancs)."""

from __future__ import annotations

from dataclasses import dataclass

from revise.db import Card, Database


@dataclass
class Weak:
    card: Card
    misses: float   # erreurs (« Difficile » compte pour une demi-erreur)
    attempts: int
    last_ok: bool   # la dernière réponse était juste

    @property
    def rate(self) -> float:
        return self.misses / self.attempts if self.attempts else 0.0

    def describe(self) -> str:
        n = round(self.misses) if self.misses == int(self.misses) else self.misses
        return f"ratée {str(n).replace('.', ',')} fois sur {self.attempts}" + ("" if self.last_ok else ", dont la dernière")


def weak_cards(db: Database, deck_ids: list[int] | None = None, limit: int = 50) -> list[Weak]:
    """Cartes à retravailler, la plus fragile d'abord. Une carte ratée une fois puis sue deux fois de suite
    n'est plus un point faible."""
    history = db.answer_history()
    cards = {c.id: c for c in db.cards(deck_ids=deck_ids, include_suspended=False)}
    out = []
    for card_id, results in history.items():
        card = cards.get(card_id)
        if card is None:
            continue
        misses = sum(1 - r for r in results)
        if misses < 1:
            continue
        recovered = len(results) >= 2 and results[-1] == 1 and results[-2] == 1
        rate = misses / len(results)
        if recovered or (results[-1] == 1 and rate < 0.4):
            continue
        out.append(Weak(card, misses, len(results), results[-1] == 1))
    out.sort(key=lambda w: (w.last_ok, -w.rate * min(w.misses, 5), -w.misses, w.card.id))
    return out[:limit]
