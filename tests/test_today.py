from datetime import date, timedelta

from fsrs import Rating

from revise import today
from revise.models import CardDraft
from revise.scheduler import Session


def test_today_counts_work_done_and_left(db):
    empty = today.today(db)
    assert (empty.decks, empty.remaining, empty.minutes, empty.mastery_percent, empty.next_exam) == (0, 0, 0, 0, None)

    deck = db.add_deck("Algo", "Piles", None, None, "simple", [CardDraft("qa", f"Question {i} ?", "R") for i in range(50)])
    t = today.today(db, base_new_per_day=20)
    assert (t.decks, t.due, t.new, t.done, t.streak, t.known, t.total) == (1, 0, 20, 0, 0, 0, 50)
    assert t.remaining == 20 and t.minutes == 5

    s = Session(db, new_per_day=20)
    for _ in range(4):
        s.answer(s.current(), Rating.Easy)
    t = today.today(db, base_new_per_day=20)
    assert (t.new, t.done, t.streak, t.known) == (16, 4, 1, 4) and t.mastery_percent == 8
    assert today.mastery(db) == {deck: (4, 50)}

    # Un examen proche relève la limite du jour : 46 cartes encore jamais vues + 4 vues aujourd'hui, en 4 jours
    db.set_exam_date([deck], (date.today() + timedelta(days=5)).isoformat())
    t = today.today(db, base_new_per_day=5)
    assert t.new_per_day == 13 and t.new == 9
    assert t.next_exam == ("Piles", 5, 8)
    assert today.new_per_day_for(db, [deck], 40) == 40            # le réglage suffit déjà
