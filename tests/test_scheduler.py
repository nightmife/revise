from datetime import datetime, timedelta, timezone

from fsrs import Rating

from revise.db import parse_iso, utcnow
from revise.models import CardDraft
from revise.scheduler import Session, format_interval, preview, start_of_day


def setup(db, n=5, subject="Algo"):
    return db.add_deck(subject, "CM", None, None, "simple",
                       [CardDraft("qa", f"Q{i}", f"R{i}", i + 1) for i in range(n)])


def test_new_cards_are_limited_and_random_across_courses(db):
    import random
    first = setup(db, 30)
    second = db.add_deck("Algo", "CM2", None, None, "simple", [CardDraft("qa", f"Autre{i}", "R", i + 1) for i in range(30)])
    s = Session(db, new_per_day=3)
    assert s.remaining == 3
    assert s.current().id == s.current().id                       # stable tant qu'on n'a pas répondu
    # Sur plusieurs séances : pas toujours les mêmes cartes, pas toujours le même ordre, et les deux cours servent
    drawn = [[c.id for c in Session(db, new_per_day=10, rng=random.Random(seed)).queue] for seed in range(8)]
    assert len({tuple(sorted(d)) for d in drawn}) > 1
    decks = {db.card(i).deck_id for d in drawn for i in d}
    assert decks == {first, second}
    firsts = {Session(db, new_per_day=10, rng=random.Random(seed)).current().id for seed in range(8)}
    assert len(firsts) > 1
    # Une séance déroulée en entier pose chaque carte une seule fois, dans un ordre qui n'est pas celui du cours
    s = Session(db, new_per_day=20, deck_ids=[first], rng=random.Random(3))
    asked = []
    while (c := s.current()) is not None and len(asked) < 50:
        asked.append(c.question)
        s.answer(c, Rating.Easy)
    assert len(asked) == 20 and len(set(asked)) == 20 and asked != sorted(asked, key=lambda q: int(q[1:]))


def test_due_cards_are_asked_in_random_order(db):
    import random
    setup(db, 12)
    past = "2000-01-01T00:00:00.000000+00:00"
    s = Session(db, new_per_day=12)
    while (c := s.current()) is not None:
        s.answer(c, Rating.Easy)
    orders = set()
    for seed in range(6):
        db.conn.execute("UPDATE cards SET due = ?", (past,))
        db.conn.commit()
        s = Session(db, new_per_day=0, rng=random.Random(seed))
        order = []
        while (c := s.current()) is not None:
            order.append(c.id)
            s.answer(c, Rating.Easy)
        assert sorted(order) == sorted(c.id for c in db.cards())
        orders.add(tuple(order))
    assert len(orders) > 1


def test_again_keeps_card_in_session_good_eventually_leaves(db):
    setup(db, 1)
    s = Session(db, new_per_day=10)
    c = s.current()
    c = s.answer(c, Rating.Again)
    assert s.remaining == 1  # due dans ~1 min : reste dans la séance
    for _ in range(5):
        cur = s.current(utcnow() + timedelta(minutes=30))
        if cur is None:
            break
        s.answer(cur, Rating.Good, now=utcnow() + timedelta(minutes=30))
    assert s.remaining == 0
    card = db.cards()[0]
    assert parse_iso(card.due) > utcnow() + timedelta(hours=12)
    assert s.done >= 2 and s.new_seen == 1


def test_daily_new_limit_counts_previous_sessions(db):
    setup(db, 10)
    s = Session(db, new_per_day=4)
    for _ in range(4):
        s.answer(s.current(), Rating.Easy)
    s2 = Session(db, new_per_day=4)
    assert all(c.fsrs is not None for c in s2.queue)  # plus aucune nouvelle aujourd'hui


def test_due_cards_come_first(db):
    setup(db, 3)
    s = Session(db, new_per_day=10)
    first = s.current()
    s.answer(first, Rating.Easy)
    # On force l'échéance dans le passé
    db.conn.execute("UPDATE cards SET due = '2000-01-01T00:00:00.000000+00:00' WHERE id = ?", (first.id,))
    s2 = Session(db, new_per_day=10)
    assert s2.current().id == first.id


def test_preview_is_monotonic(db):
    setup(db, 1)
    card = db.cards()[0]
    iv = preview(Session(db).scheduler, card, utcnow())
    assert iv[Rating.Again] <= iv[Rating.Hard] <= iv[Rating.Good] <= iv[Rating.Easy]
    assert db.cards()[0].fsrs is None  # rien d'enregistré


def test_format_interval():
    assert format_interval(timedelta(seconds=30)) == "<1 min"
    assert format_interval(timedelta(minutes=10)) == "10 min"
    assert format_interval(timedelta(hours=5)) == "5 h"
    assert format_interval(timedelta(days=3)) == "3 j"
    assert "mois" in format_interval(timedelta(days=90))


def test_start_of_day_before_and_after_4am():
    tz = datetime.now().astimezone().tzinfo
    late = datetime(2026, 11, 11, 23, 0, tzinfo=tz)
    early = datetime(2026, 11, 12, 2, 0, tzinfo=tz)
    assert start_of_day(late) == start_of_day(early)
    assert start_of_day(late).tzinfo == timezone.utc


def test_deck_filter_and_cram_mode(db):
    a = setup(db, 3, "Algo")
    b = setup(db, 4, "Algo")
    s = Session(db, new_per_day=2, deck_ids=[b])
    assert s.remaining == 2 and all(c.deck_id == b for c in s.queue)
    # Mode examen : tout le paquet, sans limite, jusqu'à « Bien » partout
    s = Session(db, deck_ids=[b], cram=True)
    assert s.remaining == 4
    first = s.current()
    s.answer(first, Rating.Again)
    assert s.remaining == 4 and s.queue[-1].id == first.id  # repasse en fin de file
    assert s.counts()[1] == 1
    while (c := s.current()) is not None:
        s.answer(c, Rating.Good)
    assert s.done == 5
    assert all(c.fsrs is not None for c in db.cards(deck_id=b))
    assert all(c.fsrs is None for c in db.cards(deck_id=a))


def test_cram_skips_known_cards_on_restart(db):
    d = setup(db, 4)
    s = Session(db, deck_ids=[d], cram=True)
    s.answer(s.current(), Rating.Good)
    s.answer(s.current(), Rating.Again)
    # On quitte et on relance : la carte sue ne revient pas, la ratée oui
    s2 = Session(db, deck_ids=[d], cram=True)
    assert s2.remaining == 3 and s2.known_skipped == 1
    s3 = Session(db, deck_ids=[d], cram=True, include_known=True)
    assert s3.remaining == 4
