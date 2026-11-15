"""Le programme du jour : ce qu'il y a à réviser, ce qui est déjà fait, où on en est."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fsrs import Rating

from revise import exam
from revise.db import Database, deck_label, utcnow
from revise.scheduler import KNOWN_RETRIEVABILITY, load_state, make_scheduler, start_of_day

DEFAULT_NEW_PER_DAY = 20
SECONDS_PER_CARD = 15  # pour annoncer une durée approximative


def mastery(db: Database, now: datetime | None = None) -> dict[int, tuple[int, int]]:
    """Par cours : (cartes sues, cartes en tout). « Sue » = dernière note Bien ou Facile, et encore fraîche."""
    now = now or utcnow()
    last = db.last_ratings()
    scheduler = make_scheduler()
    out: dict[int, tuple[int, int]] = {}
    for card in db.cards(include_suspended=False):
        known, total = out.get(card.deck_id, (0, 0))
        if (card.fsrs is not None and last.get(card.id, 0) >= int(Rating.Good)
                and scheduler.get_card_retrievability(load_state(card), now) >= KNOWN_RETRIEVABILITY):
            known += 1
        out[card.deck_id] = (known, total + 1)
    return out


def exam_plan(db: Database, deck_ids: list[int], now: datetime | None = None) -> tuple[int, int | None]:
    """(nouvelles cartes par jour qu'il faut pour les examens à venir de ces cours,
    jours avant le plus proche de ces examens — None s'il n'y en a pas)."""
    needed, soonest = 0, None
    today_start = start_of_day(now or utcnow())
    for deck_id in deck_ids:
        deck = db.deck(deck_id)
        days = exam.days_left(deck.exam_date) if deck else None
        if days is None or days < 0:
            continue
        soonest = days if soonest is None else min(soonest, days)
        # Les nouvelles cartes déjà vues aujourd'hui comptent dans la part du jour.
        todo = (len(db.new_cards(1_000_000, deck_ids=[deck_id]))
                + db.new_introduced_since(today_start, deck_ids=[deck_id]))
        needed += exam.new_per_day(todo, days)
    return needed, soonest


def new_per_day_for(db: Database, deck_ids: list[int], base: int, now: datetime | None = None) -> int:
    """Nouvelles cartes par jour pour ces cours : le réglage, relevé si un examen approche."""
    return max(base, exam_plan(db, deck_ids, now)[0])


@dataclass
class Today:
    decks: int             # nombre de cours
    due: int               # cartes à revoir maintenant
    new: int               # nouvelles cartes encore prévues aujourd'hui
    done: int              # réponses données aujourd'hui
    streak: int            # jours d'affilée avec au moins une révision
    known: int
    total: int
    new_per_day: int       # limite du jour (réglage ou examen)
    next_exam: tuple[str, int, int] | None  # (cours, jours restants, % de cartes sues) de l'examen le plus proche

    @property
    def remaining(self) -> int:
        return self.due + self.new

    @property
    def minutes(self) -> int:
        return max(1, round(self.remaining * SECONDS_PER_CARD / 60)) if self.remaining else 0

    @property
    def mastery_percent(self) -> int:
        return exam.readiness(self.known, self.total)


def today(db: Database, base_new_per_day: int = DEFAULT_NEW_PER_DAY, now: datetime | None = None) -> Today:
    from revise import stats

    now = now or utcnow()
    decks = db.decks()
    ids = [d.id for d in decks]
    limit = new_per_day_for(db, ids, base_new_per_day, now)
    quota = max(0, limit - db.new_introduced_since(start_of_day(now)))
    summary = stats.summary_data(db, now)
    levels = mastery(db, now)
    next_exam = None
    for d in decks:
        days = exam.days_left(d.exam_date)
        if days is not None and days >= 0 and (next_exam is None or days < next_exam[1]):
            known, total = levels.get(d.id, (0, 0))
            next_exam = (deck_label(d), days, exam.readiness(known, total))
    return Today(decks=len(decks), due=len(db.due_cards(now)), new=min(quota, len(db.new_cards(quota))),
                 done=summary["today"], streak=summary["streak"],
                 known=sum(k for k, _ in levels.values()), total=sum(t for _, t in levels.values()),
                 new_per_day=limit, next_exam=next_exam)
