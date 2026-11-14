"""Planification FSRS et constitution de la file d'une séance de révision."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fsrs import Card as FsrsCard
from fsrs import Rating, Scheduler, State

from revise.db import Card, Database, parse_iso, utcnow

RATING_LABELS = {Rating.Again: "À revoir", Rating.Hard: "Difficile", Rating.Good: "Bien", Rating.Easy: "Facile"}
LEARN_AHEAD = timedelta(minutes=20)  # une carte en apprentissage due dans moins de 20 min reste dans la séance
KNOWN_RETRIEVABILITY = 0.85          # mode examen : carte « sue » si dernière note ≥ Bien et rappel probable


def make_scheduler() -> Scheduler:
    return Scheduler(desired_retention=0.9, enable_fuzzing=True)


def load_state(card: Card) -> FsrsCard:
    if card.fsrs is None:
        return FsrsCard(card_id=card.id)
    return FsrsCard.from_json(card.fsrs)


def state_code(card: Card) -> int:
    """0 = nouvelle, sinon valeur de fsrs.State (1 apprentissage, 2 révision, 3 réapprentissage)."""
    return 0 if card.fsrs is None else int(load_state(card).state)


def preview(scheduler: Scheduler, card: Card, now: datetime) -> dict[Rating, timedelta]:
    """Intervalle obtenu pour chaque note, sans rien enregistrer."""
    st = load_state(card)
    out = {}
    for r in Rating:
        new, _ = scheduler.review_card(st, r, now)
        out[r] = new.due - now
    return out


def format_interval(d: timedelta) -> str:
    s = max(0, int(d.total_seconds()))
    if s < 60:
        return "<1 min"
    if s < 3600:
        return f"{round(s / 60)} min"
    if s < 86400:
        return f"{round(s / 3600)} h"
    days = s / 86400
    if days < 31:
        return f"{round(days)} j"
    if days < 365:
        return f"{days / 30.4:.1f} mois".replace(".0 ", " ")
    return f"{days / 365:.1f} ans"


def apply_review(db: Database, scheduler: Scheduler, card: Card, rating: Rating, now: datetime | None = None,
                 duration_ms: int | None = None) -> Card:
    now = now or utcnow()
    before = state_code(card)
    st = load_state(card)
    new, _ = scheduler.review_card(st, rating, now, review_duration=duration_ms)
    db.record_review(card.id, new.to_json(), new.due, int(rating), now, duration_ms, before)
    updated = db.card(card.id)
    assert updated is not None
    return updated


def start_of_day(now: datetime) -> datetime:
    """Début de la « journée de révision » locale (4 h du matin), en UTC.
    La limite de nouvelles cartes est comptée à partir de là."""
    local = now.astimezone()
    boundary = local.replace(hour=4, minute=0, second=0, microsecond=0)
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary.astimezone(timezone.utc)


@dataclass
class Session:
    """File d'une séance.

    Mode normal : cartes dues d'abord, puis nouvelles cartes (dans la limite du jour) ;
    les cartes ratées ou en apprentissage reviennent tant qu'elles sont dues dans la séance.

    Mode examen (`cram`) : toutes les cartes des cours choisis, dans un ordre aléatoire, sans
    limite ni échéance ; une carte notée « À revoir » ou « Difficile » repasse en fin de file,
    jusqu'à ce que chacune ait été notée « Bien » ou « Facile ». Les réponses sont enregistrées
    normalement : FSRS en tient compte pour la suite."""

    db: Database
    subject: str | None = None
    new_per_day: int = 20
    deck_ids: list[int] | None = None
    cram: bool = False
    include_known: bool = False
    scheduler: Scheduler = field(default_factory=make_scheduler)
    known_skipped: int = 0
    queue: list[Card] = field(default_factory=list)
    done: int = 0
    new_seen: int = 0
    to_retry: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        now = utcnow()
        if self.cram:
            cards = self.db.cards(subject=self.subject, deck_ids=self.deck_ids, include_suspended=False)
            if not self.include_known:
                # Les cartes déjà sues (dernière note Bien/Facile, encore fraîches en mémoire) ne repassent pas :
                # on peut quitter et reprendre le bachotage sans tout refaire.
                last = self.db.last_ratings()
                kept = []
                for c in cards:
                    if (c.fsrs is not None and last.get(c.id, 0) >= int(Rating.Good)
                            and self.scheduler.get_card_retrievability(load_state(c), now) >= KNOWN_RETRIEVABILITY):
                        self.known_skipped += 1
                    else:
                        kept.append(c)
                cards = kept
            random.shuffle(cards)
            self.queue = cards
            return
        due = self.db.due_cards(now + LEARN_AHEAD, self.subject, self.deck_ids)
        already = self.db.new_introduced_since(start_of_day(now), self.subject, self.deck_ids)
        quota = max(0, self.new_per_day - already)
        new = self.db.new_cards(quota, self.subject, self.deck_ids)
        self.queue = due + new

    @property
    def remaining(self) -> int:
        return len(self.queue)

    def counts(self) -> tuple[int, int, int]:
        """Normal : (nouvelles, en apprentissage, à réviser). Examen : (jamais vues, à revoir, déjà vues)."""
        new = learning = review = 0
        for c in self.queue:
            code = state_code(c)
            if self.cram:
                if c.id in self.to_retry:
                    learning += 1
                elif code == 0:
                    new += 1
                else:
                    review += 1
            elif code == 0:
                new += 1
            elif code == int(State.Review):
                review += 1
            else:
                learning += 1
        return new, learning, review

    def current(self, now: datetime | None = None) -> Card | None:
        if self.cram:
            return self.queue[0] if self.queue else None
        now = now or utcnow()
        # Priorité aux cartes dues ; les nouvelles (échéance = date de création) passent après.
        ready = [c for c in self.queue if parse_iso(c.due) <= now + LEARN_AHEAD]
        if not ready:
            return None
        seen = [c for c in ready if c.fsrs is not None and parse_iso(c.due) <= now]
        if seen:
            return min(seen, key=lambda c: c.due)
        new = [c for c in ready if c.fsrs is None]
        if new:
            return new[0]
        return min(ready, key=lambda c: c.due)  # apprentissage en avance (< 20 min)

    def answer(self, card: Card, rating: Rating, duration_ms: int | None = None,
               now: datetime | None = None) -> Card:
        now = now or utcnow()
        was_new = card.fsrs is None
        updated = apply_review(self.db, self.scheduler, card, rating, now, duration_ms)
        self.queue = [c for c in self.queue if c.id != card.id]
        self.done += 1
        if was_new:
            self.new_seen += 1
        if self.cram:
            if rating in (Rating.Again, Rating.Hard):
                self.to_retry.add(card.id)
                self.queue.append(updated)
            else:
                self.to_retry.discard(card.id)
        elif parse_iso(updated.due) <= now + LEARN_AHEAD:
            self.queue.append(updated)
        return updated

    def skip(self, card: Card) -> None:
        """Retire la carte de la séance (suspendue ou supprimée)."""
        self.queue = [c for c in self.queue if c.id != card.id]

    def refresh(self, card_id: int) -> None:
        """Recharge une carte modifiée (édition pendant la séance)."""
        fresh = self.db.card(card_id)
        self.queue = [fresh if (c.id == card_id and fresh) else c for c in self.queue if c.id != card_id or fresh]
