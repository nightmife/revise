"""Nouveautés de la 0.9 : correction des réponses tapées, points faibles, examen blanc, mise à jour d'un cours,
nettoyage des pages, progression chiffrée, reprise d'un import, recherche des cours."""

import json
import random
from pathlib import Path

import pytest

from revise.answercheck import CLOSE, EMPTY, GOOD, WRONG, check_answer
from revise.engines import Step, fraction_of, scaled
from revise.importer import GENERATOR_VERSION, import_pdf, is_outdated, update_deck
from revise.matching import match_cards
from revise.mock_exam import answer_choice, answer_written, build_exam, mark
from revise.models import CardDraft, ReviseError
from revise.pdf import clean_pages
from revise.scheduler import Rating, Session, apply_review, make_scheduler
from revise.weak import weak_cards


def test_check_answer_tolerates_typos_and_detects_missing_ideas():
    assert check_answer("FIFO", "FIFO", "cloze").verdict == GOOD
    assert check_answer("fifo ", "FIFO", "cloze").verdict == GOOD
    assert check_answer("LIFO", "FIFO", "cloze").verdict in (WRONG, CLOSE)
    assert check_answer("", "FIFO").verdict == EMPTY
    expected = "Une structure de donnée où seul le sommet est accessible (dernier entré, premier sorti)."
    assert check_answer("structure de données ou seul le sommet est accesible, dernier entré premier sorti",
                        expected).verdict == GOOD
    close = check_answer("une structure avec un sommet", expected)
    assert close.verdict in (CLOSE, WRONG) and "accessible" in close.missing
    assert check_answer("Non, jamais", "Oui, toujours en O(1)").verdict == WRONG
    assert check_answer("en 1964", "1963").verdict != GOOD   # un nombre doit être exact


def deck_with_cards(db, n=6, name="cours.pdf"):
    drafts = [CardDraft("qa", f"Question numéro {i} sur les piles ?", f"Réponse {i} : sommet {i}", i + 1)
              for i in range(n)]
    return db.add_deck("Algo", "CM", f"/tmp/{name}", None, "simple", drafts)


def test_weak_cards_from_reviews_and_quizzes(db):
    deck = deck_with_cards(db)
    cards = db.cards(deck_id=deck)
    sched = make_scheduler()
    a, b, c = cards[0], cards[1], cards[2]
    apply_review(db, sched, a, Rating.Again)                 # ratée en révision
    db.record_quiz_answer(b.id, False)                       # ratée au QCM
    db.record_quiz_answer(b.id, False, "examen")
    db.record_quiz_answer(c.id, False)                       # ratée puis sue deux fois : remise
    db.record_quiz_answer(c.id, True)
    db.record_quiz_answer(c.id, True)
    weak = weak_cards(db)
    ids = [w.card.id for w in weak]
    assert ids[0] == b.id and a.id in ids and c.id not in ids
    assert weak[0].describe() == "ratée 2 fois sur 2, dont la dernière"
    db.set_suspended(a.id, True)
    assert a.id not in [w.card.id for w in weak_cards(db)]


def test_weak_session_asks_only_those_cards(db):
    deck = deck_with_cards(db)
    ids = [c.id for c in db.cards(deck_id=deck)][:2]
    s = Session(db, deck_ids=[deck], cram=True, include_known=True, card_ids=ids, rng=random.Random(1))
    assert sorted(c.id for c in s.queue) == sorted(ids)


def test_mock_exam_mixes_questions_and_marks_out_of_20(db):
    deck = deck_with_cards(db, 10)
    cards = db.cards(deck_id=deck)
    exam = build_exam(cards, 8, written_share=0.5, rng=random.Random(3))
    assert len(exam) == 8 and {q.mode for q in exam} == {"qcm", "ecrit"}
    assert len({q.card.id for q in exam}) == 8
    for q in exam:
        if q.mode == "qcm":
            answer_choice(q, q.correct)
        else:
            answer_written(q, q.card.answer)
    assert mark(exam) == (20.0, 8.0)
    exam[0].points = 0.0
    exam[1].points = 0.5
    assert mark(exam) == (16.5, 6.5)            # 16,25 arrondi au demi-point supérieur


def test_update_deck_keeps_progress_of_matching_cards(db, tmp_path):
    class Engine:
        name = "simple"

        def __init__(self, cards):
            self.cards = cards

        def generate(self, pdf, subject, progress):
            progress(Step("travail", 0.5))
            return "Titre", [CardDraft(**c) for c in self.cards]

    src = tmp_path / "cours.txt"
    src.write_text("Une pile est une structure LIFO.\n", encoding="utf-8")
    first = [dict(kind="qa", question="Qu'est-ce qu'une pile ?", answer="Une structure LIFO", page=1),
             dict(kind="qa", question="Une question ratée et mal faite", answer="réponse coupée", page=1)]
    res = import_pdf(db, Engine(first), src, "Algo", lambda m: None)
    deck = db.deck(res.deck_id)
    assert deck.gen_version == GENERATOR_VERSION and not is_outdated(deck)
    pile = db.cards(deck_id=deck.id)[0]
    apply_review(db, make_scheduler(), pile, Rating.Good)
    db.conn.execute("UPDATE decks SET gen_version = NULL")
    assert is_outdated(db.deck(deck.id))

    src.write_text("Une pile est une structure LIFO. Une file est FIFO.\n", encoding="utf-8")  # nouvelle version
    second = [dict(kind="qa", question="Qu'est-ce qu'une pile en algorithmique ?",
                   answer="Une structure LIFO : dernier entré, premier sorti", page=1),
              dict(kind="qa", question="Qu'est-ce qu'une file ?", answer="Une structure FIFO", page=1)]
    out = update_deck(db, Engine(second), deck.id, lambda m: None)
    assert (out.kept, out.added, out.removed) == (1, 1, 1)
    after = {c.question: c for c in db.cards(deck_id=deck.id)}
    kept = after["Qu'est-ce qu'une pile en algorithmique ?"]
    assert kept.id == pile.id and kept.fsrs is not None             # même carte, progression gardée
    assert after["Qu'est-ce qu'une file ?"].fsrs is None
    assert not is_outdated(db.deck(deck.id))
    assert db.find_deck_by_hash(__import__("revise.db", fromlist=["x"]).file_sha256(src)).id == deck.id

    src.unlink()
    with pytest.raises(ReviseError, match="introuvable"):
        update_deck(db, Engine(second), deck.id, lambda m: None)


def test_match_cards_pairs_each_old_card_once(db):
    deck = db.add_deck("Algo", "CM", None, None, "simple", [
        CardDraft("qa", "Qu'est-ce qu'un arbre binaire ?", "Un arbre dont chaque nœud a au plus deux fils"),
        CardDraft("qa", "Qu'est-ce qu'une pile ?", "Une structure LIFO"),
        CardDraft("qa", "Complexité du tri fusion ?", "O(n log n)")])
    old = db.cards(deck_id=deck)
    new = [CardDraft("qa", "Qu'est-ce qu'une pile ?", "Une structure LIFO"),
           CardDraft("qa", "Qu'est-ce qu'une pile ?", "Une structure LIFO"),
           CardDraft("qa", "Rien à voir avec le reste", "Tout autre chose")]
    m = match_cards(old, new)
    assert m == {0: old[1].id}


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    from revise.db import Database
    path = tmp_path / "vieille.db"
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE decks(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, title TEXT NOT NULL,
        source TEXT, sha256 TEXT UNIQUE, engine TEXT NOT NULL, created TEXT NOT NULL);
        INSERT INTO decks VALUES (1, 'Algo', 'CM1', NULL, NULL, 'simple', '2025-01-01');""")
    con.close()
    db = Database(path)
    assert db.deck(1).gen_version is None and is_outdated(db.deck(1))
    assert db.answer_history() == {}
    db.close()


def test_clean_pages_removes_footers_and_build_up_pages():
    pages = [f"Titre {i}\nContenu {i}\nUniversité Lyon 1 — {i}/10" for i in range(10)]
    pages[5] = "Titre 6\nContenu 6"          # page « à étapes » : la suivante la reprend en entier
    pages[6] = "Titre 6\nContenu 6\nSuite 6\nUniversité Lyon 1 — 7/10"
    out = clean_pages(pages)
    assert len(out) == 10 and "Université" not in "".join(out)
    assert out[5] == "" and out[6] == "Titre 6\nContenu 6\nSuite 6"
    assert clean_pages(["Un", "Deux"]) == ["Un", "Deux"]


def test_step_and_scaled_progress():
    got = []
    report = scaled(got.append, 0.5, 1.0)
    report(Step("moitié", 0.5))
    report("texte seul")
    report(Step("Téléchargement : 40 %", 0.4, "download"))
    assert [str(m) for m in got] == ["moitié", "texte seul", "Téléchargement : 40 %"]
    assert [fraction_of(m) for m in got] == [0.75, None, 0.4]
    assert got[2].phase == "download"


def test_interrupted_import_resumes_from_cache(tmp_path):
    from revise.engines.prompt import generate_cards
    src = tmp_path / "cours.txt"
    src.write_text("\n\n".join(f"Notion {i} : définition numéro {i} " * 30 for i in range(6)), encoding="utf-8")
    calls = []

    def chat(system, user):
        calls.append(user)
        if len(calls) == 2:
            raise ReviseError("quota épuisé")          # coupure au deuxième morceau
        page = int(user.split("=== Page ")[1].split(" ")[0])
        return json.dumps({"title": "T", "cards": [{"kind": "qa", "question": f"Définition numéro {page} ?",
                                                    "answer": f"Notion {page} définition numéro", "page": page,
                                                    "section": ""}]})
    import revise.engines.prompt as prompt
    old = prompt.CHUNK_CHARS
    prompt.CHUNK_CHARS = 1500
    try:
        with pytest.raises(ReviseError):
            generate_cards(src, "Algo", lambda m: None, chat, "IA test")
        first = len(calls)
        _, cards = generate_cards(src, "Algo", lambda m: None, chat, "IA test")
    finally:
        prompt.CHUNK_CHARS = old
    asked_again = calls[first:]
    assert calls[0] not in asked_again          # le premier morceau vient du cache
    assert cards and not list(prompt._cache_dir().glob("*.json"))   # cache vidé après l'import réussi


def test_find_courses_goes_deep_and_skips_junk(tmp_path):
    from revise.gui.import_page import find_courses, where
    root = tmp_path / "pc"
    (root / "fac" / "L2" / "algo" / "vieux").mkdir(parents=True)
    (root / ".cache").mkdir()
    (root / "node_modules").mkdir()
    for p in (root / "fac" / "L2" / "algo" / "vieux" / "CM1.pdf", root / "a.docx", root / ".cache" / "x.pdf",
              root / "node_modules" / "y.pdf", root / "notes.txt", root / "~$tmp.docx"):
        p.write_bytes(b"x")
    found = find_courses([root])
    names = sorted(p.name for p, _ in found)
    assert names == ["CM1.pdf", "a.docx"]
    deep = next(p for p, _ in found if p.name == "CM1.pdf")
    assert where(deep, root) == "pc/fac/L2/algo/vieux"
    assert len(find_courses([root], limit=1)) == 1


def test_render_page_image(pdf_factory):
    pytest.importorskip("pypdfium2")
    from revise.pageview import render_page
    pdf = pdf_factory(2)
    img = render_page(pdf, 2, scale=1.0)
    assert img is not None and img.channels in (3, 4) and len(img.data) >= img.stride * img.height - img.stride
    assert render_page(pdf, 3) is None and render_page(pdf.with_suffix(".txt"), 1) is None
