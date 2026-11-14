from __future__ import annotations

import random

from revise.models import CardDraft
from revise.quiz import build_quiz, choice_text, usable_count
from revise.scheduler import Session


def make(db, answers, subject="Algo"):
    cards = [CardDraft("qa", f"Q{i}", a, i + 1) for i, a in enumerate(answers)]
    return db.add_deck(subject, "CM1", None, None, "simple", cards)


def test_build_quiz(db):
    make(db, ["pile", "file", "arbre", "graphe", "tas", "Pile "])
    cards = db.cards()
    quiz = build_quiz(cards, 4, random.Random(1))
    assert len(quiz) == 4 and len({q.card.id for q in quiz}) == 4
    for q in quiz:
        assert len(q.choices) == 4 and q.choices[q.correct] == q.card.answer.strip()
        assert len({c.lower().strip() for c in q.choices}) == 4   # « Pile » n'est jamais un leurre de « pile »
    assert len(build_quiz(cards, 50)) == 6
    assert usable_count(cards) == 6


def test_quiz_needs_two_different_answers(db):
    make(db, ["pareil", "pareil", "Pareil"])
    assert build_quiz(db.cards(), 3) == [] and usable_count(db.cards()) == 0
    make(db, ["x" * 1000, "autre"], subject="B")
    quiz = build_quiz(db.cards(subject="B"), 2, random.Random(0))
    assert [len(q.choices) for q in quiz] == [2, 2]
    assert all(len(c) <= 330 for q in quiz for c in q.choices) and choice_text("x" * 1000).endswith("…")


def test_exam_order_is_random(db):
    make(db, [f"R{i}" for i in range(30)])
    orders = {tuple(c.id for c in Session(db, cram=True).queue) for _ in range(6)}
    assert len(orders) > 1
    assert all(sorted(o) == sorted(c.id for c in db.cards()) for o in orders)
    assert [c.question for c in Session(db, new_per_day=5).queue] == [f"Q{i}" for i in range(5)]  # mode normal inchangé
