from __future__ import annotations

import random

from revise.models import CardDraft
from revise.quiz import build_quiz, choice_text, prepared_count, usable_count
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
    assert len(Session(db, new_per_day=5).queue) == 5                # mode normal : la limite du jour tient


def test_ai_distractors_come_first(db):
    wrong = ["O(n)", "O(n^2)", "O(log n)", "o(N LOG N)"]          # le dernier est la bonne réponse : écarté
    deck = db.add_deck("Algo", "CM1", None, None, "ia", [
        CardDraft("qa", "Complexité du tri fusion ?", "O(n log n)", 1, "Tris", wrong),
        CardDraft("qa", "Qu'est-ce qu'une pile ?", "Une structure LIFO.", 2, "Structures"),
        CardDraft("qa", "Qu'est-ce qu'une file ?", "Une structure FIFO.", 3, "Structures")])
    cards = db.cards(deck_id=deck)
    assert cards[0].distractors == wrong and prepared_count(cards) == 1
    for seed in range(5):
        q = next(q for q in build_quiz(cards, 3, random.Random(seed)) if q.card.id == cards[0].id)
        assert sorted(q.choices) == sorted(["O(n log n)", "O(n)", "O(n^2)", "O(log n)"])
    # Corriger la réponse d'une carte efface ses pièges ; changer seulement la page les garde.
    db.update_card_content(cards[0].id, "qa", cards[0].question, cards[0].answer, 7)
    assert db.card(cards[0].id).distractors == wrong
    db.update_card_content(cards[0].id, "qa", cards[0].question, "O(n)", 7)
    assert db.card(cards[0].id).distractors == []


def test_fallback_prefers_answers_of_the_same_kind(db):
    deck = db.add_deck("Droit", "CM", None, None, "simple", [
        CardDraft("qa", "Pourquoi le juge administratif est-il compétent ?", "Parce que l'acte est administratif.", 1),
        CardDraft("qa", "Pourquoi l'acte est-il annulé ?", "Parce que son auteur était incompétent.", 2),
        CardDraft("qa", "Pourquoi le recours est-il rejeté ?", "Parce que le délai de deux mois est dépassé.", 3),
        CardDraft("qa", "Pourquoi le préfet agit-il ?", "Parce que le maire est resté inactif.", 4),
        *[CardDraft("qa", f"En quelle année est rendu l'arrêt numéro {i} ?", f"{1900 + i}", 10 + i) for i in range(12)]])
    cards = db.cards(deck_id=deck)
    for seed in range(5):
        q = next(q for q in build_quiz(cards, 99, random.Random(seed)) if q.card.id == cards[0].id)
        assert all(c.startswith("Parce que") for c in q.choices)


def test_old_database_gets_the_new_column(tmp_path):
    import sqlite3

    from revise.db import SCHEMA, Database
    path = tmp_path / "ancienne.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.replace(",\n    distractors TEXT           -- mauvaises réponses de QCM (liste JSON), "
                                      "NULL = pas encore préparées", ""))
    conn.execute("INSERT INTO decks(subject, title, engine, created) VALUES ('A', 'B', 'simple', 'x')")
    conn.execute("INSERT INTO cards(deck_id, kind, question, answer, due, created) VALUES (1, 'qa', 'Q', 'R', 'x', 'x')")
    conn.commit()
    conn.close()
    old = Database(path)
    [card] = old.cards()
    assert card.distractors == []
    old.set_distractors(card.id, ["faux"])
    assert old.card(card.id).distractors == ["faux"]
    old.close()
    Database(path).close()   # rouvrir ne casse rien


def test_quiz_draws_from_every_selected_course(db):
    ids = [db.add_deck("Algo", f"CM{n}", None, None, "ia",
                       [CardDraft("qa", f"Question {n}-{i} ?", f"Réponse {n}-{i}", i + 1, "", ["a", "b", "c"])
                        for i in range(20)]) for n in range(3)]
    cards = db.cards(deck_ids=ids[:2])
    seen_decks, firsts = set(), set()
    for seed in range(6):
        quiz = build_quiz(cards, 10, random.Random(seed))
        assert len({q.card.id for q in quiz}) == 10
        seen_decks |= {q.card.deck_id for q in quiz}
        firsts.add(quiz[0].card.id)
    assert seen_decks == set(ids[:2]) and len(firsts) > 1          # les deux cours choisis, jamais le troisième
