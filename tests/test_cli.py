from revise import cli
from revise.db import Database


def test_import_simple_engine_and_list(tmp_path, pdf_factory, monkeypatch, capsys):
    pdf = pdf_factory(2, "[UE] CM1 - Piles.pdf")
    monkeypatch.setattr("revise.engines.simple.page_texts", lambda p: [
        "Les piles\n• Une pile est une structure de donnée de type LIFO\n",
        "Opérations\n• Procédure empiler (e)\n• Postcondition : e est au sommet\n"])
    base = tmp_path / "x.db"
    assert cli.main(["--base", str(base), "importer", str(pdf), "-m", "Algo", "--moteur", "simple"]) == 0
    db = Database(base)
    [deck] = db.decks()
    assert (deck.subject, deck.title, deck.engine) == ("Algo", "CM1 - Piles", "simple")
    assert len(db.cards(deck_id=deck.id)) >= 3
    db.close()
    # Réimport du même fichier : ignoré
    assert cli.main(["--base", str(base), "importer", str(pdf), "-m", "Algo", "--moteur", "simple"]) == 0
    assert "déjà importé" in capsys.readouterr().out
    assert cli.main(["--base", str(base), "liste"]) == 0
    assert cli.main(["--base", str(base), "stats"]) == 0


def test_errors_are_reported(tmp_path, pdf_factory, capsys):
    base = tmp_path / "x.db"
    assert cli.main(["--base", str(base), "importer", str(tmp_path / "absent.pdf"), "--moteur", "simple"]) == 1
    assert cli.main(["--base", str(base), "importer", str(pdf_factory(1)), "--moteur", "simple"]) == 1  # sans texte
    assert cli.main(["--base", str(base), "editer", "42"]) == 1


def test_resolve_decks(tmp_path):
    from revise.models import CardDraft
    db = Database(tmp_path / "y.db")
    ids = [db.add_deck("Algo", t, None, None, "simple", [CardDraft("qa", "Q", "R")])
           for t in ("CM8 - Pile et file", "CM80 - Autre", "CM9 - Arbre")]
    assert cli.resolve_decks(db, ["CM8"], None) == [ids[0]]
    assert cli.resolve_decks(db, ["cm9,1"], None) == [ids[2], ids[0]]
    assert cli.resolve_decks(db, ["arbre"], None) == [ids[2]]
    import pytest
    from revise.models import ReviseError
    with pytest.raises(ReviseError):
        cli.resolve_decks(db, ["CM42"], None)
    db.close()
