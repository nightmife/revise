import asyncio

from revise.models import CardDraft
from revise.tui import ReviewApp


def test_review_flow(db, tmp_path):
    db.add_deck("Algo", "CM8 - Pile", None, None, "simple",
                [CardDraft("qa", "Qu'est-ce qu'une **pile** ?", "Structure **LIFO**.", 3, "Piles"),
                 CardDraft("cloze", "Une file est de type [...]", "FIFO", 33, "Files")])

    async def scenario():
        app = ReviewApp(db, None, 20)
        async with app.run_test(size=(100, 30)) as pilot:
            first = app.card.id                # l'ordre des cartes est tiré au hasard
            await pilot.press("3")            # noter avant d'avoir vu la réponse : ignoré
            assert app.session.done == 0
            await pilot.press("space")
            assert app.revealed
            app.save_screenshot(str(tmp_path / "revise.svg"))
            await pilot.press("4")            # Facile
            assert app.session.done == 1
            assert app.card.id != first
            await pilot.press("s")            # suspendre
            await pilot.pause()
            assert app.card is None           # séance terminée
        return app

    app = asyncio.run(scenario())
    cards = db.cards()
    assert sorted((c.fsrs is not None, c.suspended) for c in cards) == [(False, True), (True, False)]
    assert (tmp_path / "revise.svg").exists()
