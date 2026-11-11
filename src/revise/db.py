"""Stockage SQLite : paquets (un par PDF importé), cartes, historique des révisions."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from revise.models import CardDraft

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks(
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,
    sha256 TEXT UNIQUE,
    engine TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards(
    id INTEGER PRIMARY KEY,
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    page INTEGER,
    section TEXT NOT NULL DEFAULT '',
    fsrs TEXT,                 -- état FSRS sérialisé (NULL = jamais révisée)
    due TEXT NOT NULL,         -- ISO 8601 UTC, comparable lexicographiquement
    suspended INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cards_due ON cards(due);
CREATE INDEX IF NOT EXISTS cards_deck ON cards(deck_id);
CREATE TABLE IF NOT EXISTS reviews(
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    rating INTEGER NOT NULL,
    duration_ms INTEGER,
    state_before INTEGER        -- 0 nouvelle, 1 apprentissage, 2 révision, 3 réapprentissage
);
CREATE INDEX IF NOT EXISTS reviews_ts ON reviews(ts);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Format unique (UTC, microsecondes) pour que les comparaisons de chaînes soient justes."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def default_path() -> Path:
    if env := os.environ.get("REVISE_DB"):
        return Path(env)
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "revise" / "revise.db"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Deck:
    id: int
    subject: str
    title: str
    source: str | None
    engine: str
    created: str


@dataclass
class Card:
    id: int
    deck_id: int
    kind: str
    question: str
    answer: str
    page: int | None
    section: str
    fsrs: str | None
    due: str
    suspended: bool

    @property
    def is_new(self) -> bool:
        return self.fsrs is None


def deck_label(d: Deck) -> str:
    """Nom affiché d'un cours : celui du fichier PDF (« CM8 - Pile et file ») s'il existe."""
    if d.source:
        from revise.engines.simple import title_from_filename
        name = title_from_filename(Path(d.source).stem)
        if len(name) >= 4 and any(ch.isalpha() for ch in name):
            return name
    return d.title


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or default_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- paquets
    def find_deck_by_hash(self, sha: str) -> Deck | None:
        row = self.conn.execute("SELECT * FROM decks WHERE sha256 = ?", (sha,)).fetchone()
        return self._deck(row) if row else None

    def add_deck(self, subject: str, title: str, source: str | None, sha: str | None, engine: str,
                 cards: list[CardDraft]) -> int:
        now = iso(utcnow())
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO decks(subject, title, source, sha256, engine, created) VALUES (?,?,?,?,?,?)",
                (subject, title, source, sha, engine, now))
            deck_id = int(cur.lastrowid)
            for c in cards:
                self._insert_card(deck_id, c, now)
        return deck_id

    def _insert_card(self, deck_id: int, c: CardDraft, now: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO cards(deck_id, kind, question, answer, page, section, fsrs, due, created)"
            " VALUES (?,?,?,?,?,?,NULL,?,?)",
            (deck_id, c.kind, c.question, c.answer, c.page, c.section, now, now))
        return int(cur.lastrowid)

    def add_card(self, deck_id: int, c: CardDraft) -> int:
        with self.conn:
            return self._insert_card(deck_id, c, iso(utcnow()))

    def decks(self, subject: str | None = None) -> list[Deck]:
        if subject:
            rows = self.conn.execute("SELECT * FROM decks WHERE subject = ? COLLATE NOCASE ORDER BY id", (subject,))
        else:
            rows = self.conn.execute("SELECT * FROM decks ORDER BY subject, id")
        return [self._deck(r) for r in rows]

    def deck(self, deck_id: int) -> Deck | None:
        row = self.conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
        return self._deck(row) if row else None

    def delete_deck(self, deck_id: int) -> bool:
        with self.conn:
            return self.conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,)).rowcount > 0

    def subjects(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT subject FROM decks ORDER BY subject COLLATE NOCASE")]

    # ----------------------------------------------------------------- cartes
    @staticmethod
    def _scope(subject: str | None, deck_ids: list[int] | None) -> tuple[str, list]:
        sql, args = "", []
        if subject:
            sql += " AND d.subject = ? COLLATE NOCASE"
            args.append(subject)
        if deck_ids is not None:
            ids = [int(x) for x in deck_ids] or [-1]
            sql += f" AND c.deck_id IN ({','.join('?' * len(ids))})"
            args += ids
        return sql, args

    def cards(self, deck_id: int | None = None, subject: str | None = None, include_suspended: bool = True,
              deck_ids: list[int] | None = None) -> list[Card]:
        if deck_id is not None:
            deck_ids = [deck_id]
        scope, args = self._scope(subject, deck_ids)
        sql = "SELECT c.* FROM cards c JOIN decks d ON d.id = c.deck_id WHERE 1=1" + scope
        if not include_suspended:
            sql += " AND c.suspended = 0"
        sql += " ORDER BY c.deck_id, c.page IS NULL, c.page, c.id"
        return [self._card(r) for r in self.conn.execute(sql, args)]

    def card(self, card_id: int) -> Card | None:
        row = self.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return self._card(row) if row else None

    def update_card_content(self, card_id: int, kind: str, question: str, answer: str, page: int | None) -> None:
        with self.conn:
            self.conn.execute("UPDATE cards SET kind=?, question=?, answer=?, page=? WHERE id=?",
                              (kind, question, answer, page, card_id))

    def delete_card(self, card_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))

    def set_suspended(self, card_id: int, value: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE cards SET suspended = ? WHERE id = ?", (int(value), card_id))

    def record_review(self, card_id: int, fsrs_json: str, due: datetime, rating: int, ts: datetime,
                      duration_ms: int | None, state_before: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE cards SET fsrs = ?, due = ? WHERE id = ?", (fsrs_json, iso(due), card_id))
            self.conn.execute(
                "INSERT INTO reviews(card_id, ts, rating, duration_ms, state_before) VALUES (?,?,?,?,?)",
                (card_id, iso(ts), rating, duration_ms, state_before))

    def due_cards(self, now: datetime, subject: str | None = None, deck_ids: list[int] | None = None) -> list[Card]:
        """Cartes déjà vues dont l'échéance est passée."""
        scope, sargs = self._scope(subject, deck_ids)
        sql = ("SELECT c.* FROM cards c JOIN decks d ON d.id = c.deck_id"
               " WHERE c.suspended = 0 AND c.fsrs IS NOT NULL AND c.due <= ?" + scope + " ORDER BY c.due")
        args: list = [iso(now), *sargs]
        return [self._card(r) for r in self.conn.execute(sql, args)]

    def new_cards(self, limit: int, subject: str | None = None, deck_ids: list[int] | None = None) -> list[Card]:
        """Nouvelles cartes, dans l'ordre du cours (paquet puis page)."""
        scope, sargs = self._scope(subject, deck_ids)
        sql = ("SELECT c.* FROM cards c JOIN decks d ON d.id = c.deck_id"
               " WHERE c.suspended = 0 AND c.fsrs IS NULL" + scope +
               " ORDER BY c.deck_id, c.page IS NULL, c.page, c.id LIMIT ?")
        args: list = [*sargs, max(0, limit)]
        return [self._card(r) for r in self.conn.execute(sql, args)]

    def new_introduced_since(self, since: datetime, subject: str | None = None,
                             deck_ids: list[int] | None = None) -> int:
        """Nombre de cartes vues pour la première fois depuis `since`."""
        scope, sargs = self._scope(subject, deck_ids)
        sql = ("SELECT COUNT(*) FROM reviews r JOIN cards c ON c.id = r.card_id JOIN decks d ON d.id = c.deck_id"
               " WHERE r.state_before = 0 AND r.ts >= ?" + scope)
        args: list = [iso(since), *sargs]
        return int(self.conn.execute(sql, args).fetchone()[0])

    def last_ratings(self) -> dict[int, int]:
        """Note de la dernière révision de chaque carte."""
        rows = self.conn.execute(
            "SELECT r.card_id, r.rating FROM reviews r"
            " JOIN (SELECT card_id, MAX(id) AS mid FROM reviews GROUP BY card_id) l ON l.mid = r.id")
        return {int(a): int(b) for a, b in rows}

    def rename_deck(self, deck_id: int, title: str, subject: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE decks SET title = ?, subject = ? WHERE id = ?", (title, subject, deck_id))

    def reviews_since(self, since: datetime) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM reviews WHERE ts >= ? ORDER BY ts", (iso(since),)))

    # ------------------------------------------------------------- conversions
    @staticmethod
    def _deck(r: sqlite3.Row) -> Deck:
        return Deck(r["id"], r["subject"], r["title"], r["source"], r["engine"], r["created"])

    @staticmethod
    def _card(r: sqlite3.Row) -> Card:
        return Card(r["id"], r["deck_id"], r["kind"], r["question"], r["answer"], r["page"], r["section"],
                    r["fsrs"], r["due"], bool(r["suspended"]))
