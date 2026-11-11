from datetime import timedelta

from revise.db import iso, parse_iso, utcnow
from revise.models import CardDraft


def drafts(n):
    return [CardDraft("qa", f"Q{i}", f"R{i}", page=i + 1) for i in range(n)]


def test_deck_and_cards(db):
    d = db.add_deck("Algo", "CM1", "/x.pdf", "abc", "simple", drafts(3))
    assert db.find_deck_by_hash("abc").id == d
    assert [c.question for c in db.cards(deck_id=d)] == ["Q0", "Q1", "Q2"]
    assert db.subjects() == ["Algo"]
    assert len(db.new_cards(2)) == 2
    assert db.due_cards(utcnow()) == []  # les nouvelles ne sont pas « dues »


def test_iso_ordering():
    a = utcnow()
    b = a + timedelta(microseconds=1)
    assert iso(a) < iso(b)
    assert parse_iso(iso(a)) == a


def test_delete_cascades(db):
    d = db.add_deck("Algo", "CM1", None, None, "simple", drafts(2))
    c = db.cards(deck_id=d)[0]
    db.record_review(c.id, "{}", utcnow(), 3, utcnow(), 1000, 0)
    assert db.delete_deck(d)
    assert db.cards() == []
    assert db.conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0


def test_subject_filter_case_insensitive(db):
    db.add_deck("Réseaux", "CM1", None, None, "simple", drafts(1))
    db.add_deck("Algo", "CM1", None, None, "simple", drafts(2))
    assert len(db.cards(subject="réseaux")) == 1
    assert len(db.new_cards(10, subject="ALGO")) == 2
