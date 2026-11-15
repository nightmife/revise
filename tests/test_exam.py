import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from revise import exam
from revise.db import Database
from revise.models import CardDraft

TODAY = date(2026, 11, 15)


def test_days_left_and_countdown():
    assert exam.days_left("2026-11-15", TODAY) == 0 and exam.days_left("2026-11-25", TODAY) == 10
    assert exam.days_left("2026-11-01", TODAY) == -14
    assert exam.days_left(None, TODAY) is None and exam.days_left("bientôt", TODAY) is None
    assert [exam.countdown(d) for d in (-3, 0, 1, 12)] == ["passé", "aujourd'hui", "demain", "J-12"]


@pytest.mark.parametrize("new,days,expected", [
    (60, 11, 6),      # 10 jours pour apprendre, la veille pour revoir
    (61, 11, 7),      # arrondi au-dessus : rien ne reste pour après l'examen
    (60, 2, 60), (60, 1, 60), (60, 0, 60),   # trop tard pour étaler : tout aujourd'hui
    (0, 5, 0), (60, -1, 0),                  # rien à apprendre, ou examen passé
])
def test_new_per_day(new, days, expected):
    assert exam.new_per_day(new, days) == expected


def test_readiness():
    assert exam.readiness(0, 0) == 0 and exam.readiness(1, 3) == 33 and exam.readiness(3, 3) == 100


def test_exam_date_is_stored_and_old_databases_are_upgraded(tmp_path):
    import sqlite3
    path = tmp_path / "vieille.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE decks(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, title TEXT NOT NULL, source TEXT,"
                " sha256 TEXT UNIQUE, engine TEXT NOT NULL, created TEXT NOT NULL)")
    con.execute("INSERT INTO decks VALUES (1, 'Algo', 'Vieux', NULL, NULL, 'simple', '2025-01-01')")
    con.commit()
    con.close()
    db = Database(path)
    assert db.deck(1).exam_date is None
    db.set_exam_date([1], "2026-12-18")
    assert db.deck(1).exam_date == "2026-12-18"
    db.set_exam_date([1], None)
    assert db.decks()[0].exam_date is None
    db.close()


def test_courses_page_plans_new_cards_for_the_exam(db):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from revise.gui.courses import CoursesPage
    app = QApplication.instance() or QApplication([])
    deck = db.add_deck("Algo", "Piles", None, None, "simple", [CardDraft("qa", f"Question {i} ?", "R") for i in range(90)])
    other = db.add_deck("Algo", "Files", None, None, "simple", [CardDraft("qa", "Q ?", "R")])
    page = CoursesPage(db)
    page.show()
    page._set_all(True)
    assert page.exam_plan([deck, other]) == (0, None) and not page.exam_hint.isVisible()

    page.set_exam_date((date.today() + timedelta(days=10)).isoformat())      # les deux cours cochés
    assert db.deck(deck).exam_date == db.deck(other).exam_date
    assert page.exam_plan([deck]) == (10, 10)                                  # 90 cartes en 9 jours
    assert page.exam_plan([deck, other]) == (11, 10)
    child = page.tree.topLevelItem(0).child(0)
    assert child.text(5) == "J-10 · prêt à 0 %"
    assert page.selected_decks() == [deck, other]                            # la sélection survit au rafraîchissement
    page.new_per_day.setValue(5)
    assert page.exam_hint.isVisible() and "11 nouvelles cartes" in page.exam_hint.text()
    started = []
    page.start_review.connect(lambda ids, cram, known, n: started.append((cram, n)))
    page.review_btn.click()
    page.exam_btn.click()
    assert started == [(False, 11), (True, 5)]                               # « Tout revoir » n'est pas concerné
    page.new_per_day.setValue(40)                                            # déjà assez : rien à signaler
    assert not page.exam_hint.isVisible()
    page.review_btn.click()
    assert started[-1] == (False, 40)

    db.set_exam_date([deck, other], (date.today() - timedelta(days=2)).isoformat())
    page.refresh()
    assert page.tree.topLevelItem(0).child(0).text(5) == "passé" and page.exam_plan([deck, other]) == (0, None)
    page.set_exam_date(None)
    assert page.tree.topLevelItem(0).child(0).text(5) == ""
    app.processEvents()
