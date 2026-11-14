"""QCM fabriqués à partir des cartes : la bonne réponse d'une carte, mélangée aux
réponses d'autres cartes du même cours qui lui ressemblent le plus."""

from __future__ import annotations

import random
from dataclasses import dataclass

from revise.db import Card

MAX_CHOICE_CHARS = 320


@dataclass
class QuizQuestion:
    card: Card
    choices: list[str]
    correct: int  # indice de la bonne réponse dans `choices`


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def choice_text(answer: str) -> str:
    s = answer.strip()
    if len(s) <= MAX_CHOICE_CHARS:
        return s
    return s[:MAX_CHOICE_CHARS].rsplit(" ", 1)[0] + " …"


def _closeness(card: Card, other: Card) -> float:
    """Plus le score est haut, plus la réponse de `other` est un leurre crédible."""
    score = 0.0
    if other.deck_id == card.deck_id:
        score += 3
    if other.kind == card.kind:
        score += 2
    if other.section and other.section == card.section:
        score += 1
    a, b = len(card.answer), len(other.answer)
    score += 2 * min(a, b) / max(a, b, 1)
    return score


def distractors(card: Card, pool: list[Card], rng: random.Random, n: int = 3) -> list[str]:
    """Jusqu'à `n` mauvaises réponses, toutes différentes entre elles et de la bonne."""
    seen = {_norm(card.answer), _norm(choice_text(card.answer))}
    ranked = sorted(((_closeness(card, o), o.id, o) for o in pool if o.id != card.id), reverse=True)
    candidates: list[str] = []
    for _, _, other in ranked:
        text = choice_text(other.answer)
        key = _norm(text)
        if not key or key in seen or _norm(other.answer) in seen:
            continue
        seen.add(key)
        candidates.append(text)
        if len(candidates) >= 2 * n:
            break
    # Tirage parmi les meilleurs leurres, pour que le QCM change d'une fois à l'autre.
    best = candidates
    rng.shuffle(best)
    return best[:n]


def usable_count(cards: list[Card]) -> int:
    """Nombre de cartes utilisables en QCM : toutes dès qu'il existe deux réponses différentes."""
    return len(cards) if len({_norm(c.answer) for c in cards}) >= 2 else 0


def build_quiz(cards: list[Card], count: int, rng: random.Random | None = None,
               pool: list[Card] | None = None) -> list[QuizQuestion]:
    """Tire `count` questions au hasard parmi `cards`. Les leurres viennent de `pool`
    (par défaut `cards`). Une carte sans aucun leurre possible est écartée."""
    rng = rng or random.Random()
    pool = cards if pool is None else pool
    order = list(cards)
    rng.shuffle(order)
    questions: list[QuizQuestion] = []
    for card in order:
        if len(questions) >= count:
            break
        wrong = distractors(card, pool, rng)
        if not wrong:
            continue
        choices = wrong + [choice_text(card.answer)]
        rng.shuffle(choices)
        questions.append(QuizQuestion(card, choices, choices.index(choice_text(card.answer))))
    return questions
