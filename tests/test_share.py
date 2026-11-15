"""Partage de cours (.revise, Anki), sauvegarde et restauration."""

import json

import pytest

from revise import cli, share
from revise.db import Database
from revise.models import CardDraft, ReviseError


def sample(db: Database) -> int:
    deck = db.add_deck("Algo", "Les piles", "/home/moi/dl/[UE] CM8 - Pile et file.pdf", "ab" * 32, "abonnement",
                       [CardDraft("qa", "Qu'est-ce qu'une **pile** ?", "Structure `LIFO`\nsur deux lignes", 3, "Piles",
                                  ["FIFO", "Un arbre", "Un tas"]),
                        CardDraft("cloze", "Une file est de type [...]", "FIFO", 9),
                        CardDraft("qa", "Carte ratée", "à ne plus poser")])
    db.set_suspended(db.cards(deck_id=deck)[2].id, True)
    return deck


def test_export_then_import_keeps_cards_but_not_progress(db, tmp_path):
    deck = sample(db)
    out = tmp_path / "algo.revise"
    assert share.export_courses(db, [deck], out) == 2          # la carte suspendue n'est pas partagée
    assert "/home/moi" not in out.read_text(encoding="utf-8")  # pas de chemin personnel dans le fichier

    other = Database(tmp_path / "autre.db")
    [got] = share.import_file(other, out)
    assert (got.name, got.cards, got.skipped) == ("CM8 - Pile et file", 2, False)
    [d] = other.decks()
    assert (d.subject, d.title, d.engine) == ("Algo", "Les piles", "abonnement")
    cards = other.cards(deck_id=d.id)
    assert [c.question for c in cards] == ["Qu'est-ce qu'une **pile** ?", "Une file est de type [...]"]
    assert cards[0].distractors == ["FIFO", "Un arbre", "Un tas"] and cards[0].page == 3
    assert all(c.is_new for c in cards)
    # Deuxième import du même fichier : rien en double ; matière imposée pour un fichier jamais vu
    assert [r.skipped for r in share.import_file(other, out)] == [True]
    assert len(other.decks()) == 1
    other.close()


def test_export_without_pdf_hash_is_still_deduplicated(db, tmp_path):
    deck = db.add_deck("Algo", "Sans PDF", None, None, "simple", [CardDraft("qa", "Q", "R")])
    out = tmp_path / "x.revise"
    share.export_courses(db, [deck], out)
    other = Database(tmp_path / "autre.db")
    assert [r.skipped for r in share.import_file(other, out, subject="Maths")] == [False]
    assert [r.skipped for r in share.import_file(other, out)] == [True]
    assert other.decks()[0].subject == "Maths"
    other.close()


@pytest.mark.parametrize("content", [
    "pas du json", "[]", '{"format": "autre", "courses": []}',
    '{"format": "revise-cours", "version": 1, "courses": []}',
    '{"format": "revise-cours", "version": 1, "courses": [{"cards": [{"question": "", "answer": "x"}]}]}',
    '{"format": "revise-cours", "version": 99, "courses": []}',
    '{"format": "revise-cours", "version": "1", "courses": "x"}',
])
def test_bad_share_files_are_refused(db, tmp_path, content):
    f = tmp_path / "mauvais.revise"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(ReviseError):
        share.import_file(db, f)
    assert db.decks() == []


def test_import_cleans_untrusted_content(db, tmp_path):
    f = tmp_path / "bizarre.revise"
    f.write_text(json.dumps({"format": "revise-cours", "version": 1, "courses": [
        {"subject": 12, "title": None, "file": "../../etc/passwd", "sha256": "pas un hash", "engine": ["x"], "cards": [
            {"kind": "inconnu", "question": " Q ", "answer": "R", "page": "trois", "distractors": ["a", 5, "", "b"]},
            "pas une carte", {"question": "sans réponse"}]},
        "pas un cours"]}), encoding="utf-8")
    [got] = share.import_file(db, f)
    [d] = db.decks()
    assert (d.subject, d.source, d.engine, got.cards) == ("Mes cours", "passwd", "partage", 1)
    [c] = db.cards(deck_id=d.id)
    assert (c.kind, c.question, c.page, c.distractors) == ("qa", "Q", None, ["a", "b"])


def test_anki_export(db, tmp_path):
    deck = sample(db)
    out = tmp_path / "anki.txt"
    assert share.export_anki(db, [deck], out) == 2
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["#separator:tab", "#html:true"]
    cards = [line.split("\t") for line in lines if not line.startswith("#")]
    assert all(len(c) == 3 for c in cards)                   # ni tabulation ni saut de ligne dans un champ
    assert cards[0][0] == "Qu'est-ce qu'une <b>pile</b> ?"
    assert cards[0][1] == "Structure <code>LIFO</code><br>sur deux lignes"
    assert cards[0][2] == "Algo CM8_-_Pile_et_file"


def test_backup_and_restore(db, tmp_path):
    deck = sample(db)
    save = tmp_path / "sauvegarde.db"
    db.backup_to(save)
    db.delete_deck(deck)
    extra = db.add_deck("Autre", "Après la sauvegarde", None, None, "simple", [CardDraft("qa", "Q", "R")])
    previous = db.restore_from(save)
    assert [d.title for d in db.decks()] == ["Les piles"] and len(db.cards()) == 3
    # Les données remplacées sont gardées, et la base reste utilisable (clés étrangères comprises)
    assert previous is not None and previous.is_file()
    old = Database(previous)
    assert [d.id for d in old.decks()] == [extra]
    old.close()
    db.delete_deck(db.decks()[0].id)
    assert db.cards() == []
    assert db.restore_from(previous) is None                  # annuler une restauration : la copie n'est pas écrasée
    assert [d.title for d in db.decks()] == ["Après la sauvegarde"]


def test_restore_refuses_other_files(db, tmp_path):
    deck = sample(db)
    junk = tmp_path / "photo.db"
    junk.write_bytes(b"pas une base")
    shared = tmp_path / "cours.revise"
    share.export_courses(db, [deck], shared)
    import sqlite3
    foreign = tmp_path / "autre-appli.db"
    con = sqlite3.connect(foreign)
    con.execute("CREATE TABLE cards(x)")
    con.commit()
    con.close()
    for bad in (junk, shared, foreign, tmp_path / "absent.db", db.path):
        with pytest.raises(ReviseError):
            db.restore_from(bad)
    with pytest.raises(ReviseError):
        db.backup_to(db.path)
    assert len(db.cards()) == 3                               # rien n'a été touché


def test_restore_migrates_old_backups(db, tmp_path):
    import sqlite3
    old = tmp_path / "vieille.db"
    con = sqlite3.connect(old)
    con.executescript(
        "CREATE TABLE decks(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, title TEXT NOT NULL, source TEXT,"
        " sha256 TEXT UNIQUE, engine TEXT NOT NULL, created TEXT NOT NULL);"
        "CREATE TABLE cards(id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL, kind TEXT NOT NULL, question TEXT NOT NULL,"
        " answer TEXT NOT NULL, page INTEGER, section TEXT NOT NULL DEFAULT '', fsrs TEXT, due TEXT NOT NULL,"
        " suspended INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);"
        "CREATE TABLE reviews(id INTEGER PRIMARY KEY, card_id INTEGER NOT NULL, ts TEXT NOT NULL, rating INTEGER NOT NULL,"
        " duration_ms INTEGER, state_before INTEGER);"
        "INSERT INTO decks VALUES (1, 'Algo', 'Vieux cours', NULL, NULL, 'simple', '2025-01-01');"
        "INSERT INTO cards VALUES (1, 1, 'qa', 'Q', 'R', NULL, '', NULL, '2025-01-01', 0, '2025-01-01');")
    con.close()
    db.restore_from(old)
    [c] = db.cards()
    assert c.distractors == []
    db.set_distractors(c.id, ["a", "b", "c"])                 # la colonne ajoutée en 0.4 existe
    assert db.card(c.id).distractors == ["a", "b", "c"]


def test_cli_share_backup_restore(tmp_path, capsys):
    base = tmp_path / "x.db"
    db = Database(base)
    sample(db)
    db.close()
    shared, save = tmp_path / "algo.revise", tmp_path / "s.db"
    assert cli.main(["--base", str(base), "partager", str(shared), "--cours", "CM8"]) == 0
    assert cli.main(["--base", str(base), "partager", str(tmp_path / "a.txt"), "--anki"]) == 0
    assert cli.main(["--base", str(base), "sauvegarder", str(save)]) == 0
    other = tmp_path / "y.db"
    assert cli.main(["--base", str(other), "importer", str(shared), "-m", "Info"]) == 0   # sans moteur d'IA
    assert cli.main(["--base", str(other), "importer", str(shared)]) == 0
    assert "déjà importé" in capsys.readouterr().out
    db = Database(other)
    assert [(d.subject, len(db.cards(deck_id=d.id))) for d in db.decks()] == [("Info", 2)]
    db.close()
    assert cli.main(["--base", str(other), "restaurer", str(save), "--oui"]) == 0
    assert cli.main(["--base", str(other), "restaurer", str(shared), "--oui"]) == 1
    db = Database(other)
    assert [d.subject for d in db.decks()] == ["Algo"] and len(db.cards()) == 3
    db.close()
