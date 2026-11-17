"""Examen blanc : QCM et questions à réponse écrite mélangés, chronométrés, notés sur 20.

Ne touche pas au planning de révision ; les réponses sont gardées pour « Mes points faibles »."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from revise.answercheck import CLOSE, GOOD, Check, check_answer
from revise.db import Card
from revise.quiz import build_quiz

MAX_OPEN_ANSWER = 350  # au-delà, une réponse est trop longue à écrire pendant un examen
POINTS = {GOOD: 1.0, CLOSE: 0.5}


@dataclass
class ExamQuestion:
    card: Card
    mode: str                          # "qcm" ou "ecrit"
    choices: list[str] = field(default_factory=list)
    correct: int = -1
    given: str = ""                    # réponse choisie (texte) ou écrite
    check: Check | None = None
    points: float | None = None        # None = pas encore répondu

    @property
    def answered(self) -> bool:
        return self.points is not None


def build_exam(cards: list[Card], count: int, written_share: float = 0.4,
               rng: random.Random | None = None) -> list[ExamQuestion]:
    """`count` questions tirées au hasard : environ `written_share` à réponse écrite (cartes à réponse courte),
    le reste en QCM."""
    rng = rng or random.Random()
    pool = list(cards)
    rng.shuffle(pool)
    writable = [c for c in pool if c.kind != "code" and len(c.answer) <= MAX_OPEN_ANSWER]
    n_written = min(len(writable), round(count * written_share))
    written = writable[:n_written]
    taken = {c.id for c in written}
    rest = [c for c in pool if c.id not in taken]
    quiz = build_quiz(rest, count - n_written, rng=rng, pool=cards)
    questions = [ExamQuestion(c, "ecrit") for c in written]
    questions += [ExamQuestion(q.card, "qcm", q.choices, q.correct) for q in quiz]
    if len(questions) < count:  # pas assez de QCM possibles : on complète en écrit
        extra = [c for c in writable[n_written:] if c.id not in {q.card.id for q in questions}]
        questions += [ExamQuestion(c, "ecrit") for c in extra[:count - len(questions)]]
    rng.shuffle(questions)
    return questions


def answer_choice(q: ExamQuestion, index: int) -> None:
    q.given = q.choices[index] if 0 <= index < len(q.choices) else ""
    q.points = 1.0 if index == q.correct else 0.0


def answer_written(q: ExamQuestion, text: str) -> None:
    q.given = text.strip()
    q.check = check_answer(q.given, q.card.answer, q.card.kind)
    q.points = POINTS.get(q.check.verdict, 0.0)


def mark(questions: list[ExamQuestion]) -> tuple[float, float]:
    """(note sur 20 arrondie au demi-point, points obtenus). Une question sans réponse vaut 0."""
    if not questions:
        return 0.0, 0.0
    got = sum(q.points or 0.0 for q in questions)
    return math.floor(40 * got / len(questions) + 0.5) / 2, got
