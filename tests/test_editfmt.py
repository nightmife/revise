import pytest

from revise import editfmt
from revise.models import CardDraft, ReviseError


def test_roundtrip_update_create_delete(db):
    d = db.add_deck("Algo", "CM", None, None, "simple",
                    [CardDraft("qa", "Q1", "R1", 1), CardDraft("cloze", "a [...] b", "x", 2),
                     CardDraft("code", "Écris f", "```c\nint f();\n```", 3)])
    original = db.cards(deck_id=d)
    text = editfmt.render("CM", original)
    blocks = editfmt.parse(text)
    assert [(b.card_id, b.kind, b.question, b.answer, b.page) for b in blocks] == \
        [(c.id, c.kind, c.question, c.answer, c.page) for c in original]
    ch = editfmt.diff(db, d, original, blocks)
    assert (ch.updated, ch.created, ch.deleted) == (0, 0, [])

    c1, c2, c3 = original
    edited = (f"## carte {c1.id} · qa · p.1\nQ: Q1 modifiée\nsur deux lignes\nR: R1\n\n"
              f"## carte {c3.id} · code · p.3\nQ: Écris f\nR: ```c\nint f();\n```\n\n"
              "## nouvelle · qa · p.9\nQ: Nouvelle\nR: Réponse\n")
    blocks = editfmt.parse(edited)
    ch = editfmt.apply(db, d, original, blocks)
    assert (ch.updated, ch.created, ch.deleted) == (1, 1, [c2.id])
    cards = db.cards(deck_id=d)
    assert [c.question for c in cards] == ["Q1 modifiée\nsur deux lignes", "Écris f", "Nouvelle"]
    assert cards[1].answer == "```c\nint f();\n```"


def test_errors():
    with pytest.raises(ReviseError):
        editfmt.parse("## carte 1 · qa\nQ: sans réponse\n")
    with pytest.raises(ReviseError):
        editfmt.parse("## carte 1 · inconnu\nQ: a\nR: b\n")
    with pytest.raises(ReviseError):
        editfmt.parse("texte libre avant la première carte\n")
    assert editfmt.parse("## nouvelle · qa\nQ: \nR: \n") == []  # bloc vide ignoré


def test_foreign_card_rejected(db):
    d = db.add_deck("Algo", "CM", None, None, "simple", [CardDraft("qa", "Q", "R")])
    with pytest.raises(ReviseError):
        editfmt.diff(db, d, db.cards(deck_id=d), editfmt.parse("## carte 999 · qa\nQ: a\nR: b\n"))
