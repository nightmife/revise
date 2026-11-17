"""Stockage SQLite : paquets (un par PDF importé), cartes, historique des révisions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from revise.config import data_dir
from revise.models import CardDraft, ReviseError

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks(
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,
    sha256 TEXT UNIQUE,
    engine TEXT NOT NULL,
    created TEXT NOT NULL,
    exam_date TEXT,            -- date de l'examen (AAAA-MM-JJ), NULL = pas de date
    gen_version INTEGER        -- version de la fabrication des cartes (NULL = avant la 0.9 ou cours partagé)
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
    created TEXT NOT NULL,
    distractors TEXT,          -- mauvaises réponses de QCM (liste JSON), NULL = pas encore préparées
    quiz_answer TEXT           -- bonne réponse au format des mauvaises (QCM), NULL = prendre `answer`
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
CREATE TABLE IF NOT EXISTS quiz_answers(   -- réponses aux QCM et examens blancs (ne touchent pas au planning)
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    correct INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'qcm'      -- 'qcm' ou 'examen'
);
CREATE INDEX IF NOT EXISTS quiz_answers_card ON quiz_answers(card_id);
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
    return data_dir() / "revise.db"


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
    exam_date: str | None = None  # AAAA-MM-JJ
    gen_version: int | None = None  # version de la fabrication des cartes (None = ancienne ou inconnue)


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
    distractors: list[str] = field(default_factory=list)
    quiz_answer: str = ""  # bonne réponse telle que le QCM la montre ("" = `answer`)

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
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(SCHEMA)
        # Bases créées avant la version 0.4 : la colonne des mauvaises réponses de QCM n'existe pas.
        if "distractors" not in {r["name"] for r in self.conn.execute("PRAGMA table_info(cards)")}:
            with self.conn:
                self.conn.execute("ALTER TABLE cards ADD COLUMN distractors TEXT")
        # Bases créées avant la version 0.8 : pas de bonne réponse réécrite pour le QCM.
        if "quiz_answer" not in {r["name"] for r in self.conn.execute("PRAGMA table_info(cards)")}:
            with self.conn:
                self.conn.execute("ALTER TABLE cards ADD COLUMN quiz_answer TEXT")
        # Bases créées avant la version 0.6 : pas de date d'examen.
        deck_columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(decks)")}
        if "exam_date" not in deck_columns:
            with self.conn:
                self.conn.execute("ALTER TABLE decks ADD COLUMN exam_date TEXT")
        # Bases créées avant la version 0.9 : version de fabrication des cartes inconnue.
        if "gen_version" not in deck_columns:
            with self.conn:
                self.conn.execute("ALTER TABLE decks ADD COLUMN gen_version INTEGER")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------ sauvegarde
    def backup_to(self, dest: Path) -> None:
        """Copie complète de la base (cours, cartes, progression) dans un fichier."""
        dest = Path(dest)
        if str(self.path) != ":memory:" and dest.resolve() == Path(self.path).resolve():
            raise ReviseError("Choisis un autre fichier : celui-ci est la base utilisée par l'application.")
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            tmp.unlink(missing_ok=True)
            out = sqlite3.connect(str(tmp))
            try:
                self.conn.backup(out)
            finally:
                out.close()
            os.replace(tmp, dest)  # jamais de sauvegarde à moitié écrite
        except (OSError, sqlite3.Error) as e:
            tmp.unlink(missing_ok=True)
            raise ReviseError(f"Sauvegarde impossible dans {dest.name} ({e})") from e

    def restore_from(self, src: Path) -> Path | None:
        """Remplace tout le contenu de la base par celui d'une sauvegarde (vérifiée avant d'y toucher).
        Les données remplacées sont d'abord copiées dans « avant-restauration.db », à côté de la base :
        renvoie ce fichier (None s'il n'a pas été écrit)."""
        src = Path(src)
        if not src.is_file():
            raise ReviseError(f"Fichier introuvable : {src}")
        if str(self.path) != ":memory:" and src.resolve() == Path(self.path).resolve():
            raise ReviseError("Ce fichier est déjà la base utilisée par l'application.")
        bad = ReviseError(f"{src.name} n'est pas une sauvegarde de revise.")
        try:
            source = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.Error as e:
            raise bad from e
        try:
            try:
                tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                columns = {r[1] for r in source.execute("PRAGMA table_info(cards)")}
                healthy = source.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            except sqlite3.Error as e:
                raise bad from e
            needed = {"deck_id", "kind", "question", "answer", "fsrs", "due", "suspended"}
            if not {"decks", "cards", "reviews"} <= tables or not needed <= columns:
                raise bad
            if not healthy:
                raise ReviseError(f"{src.name} est abîmé : la restauration est annulée.")
            previous = None
            if str(self.path) != ":memory:":
                previous = Path(self.path).with_name("avant-restauration.db")
                if previous.resolve() == src.resolve():
                    previous = None  # on restaure justement cette copie : ne pas l'écraser pendant sa lecture
                else:
                    self.backup_to(previous)
            try:
                source.backup(self.conn)
            except sqlite3.Error as e:
                raise ReviseError(f"Restauration impossible ({e}). Tes données n'ont pas été modifiées.") from e
        finally:
            source.close()
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        return previous

    # ---------------------------------------------------------------- paquets
    def find_deck_by_hash(self, sha: str) -> Deck | None:
        row = self.conn.execute("SELECT * FROM decks WHERE sha256 = ?", (sha,)).fetchone()
        return self._deck(row) if row else None

    def add_deck(self, subject: str, title: str, source: str | None, sha: str | None, engine: str,
                 cards: list[CardDraft], gen_version: int | None = None) -> int:
        now = iso(utcnow())
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO decks(subject, title, source, sha256, engine, created, gen_version)"
                " VALUES (?,?,?,?,?,?,?)", (subject, title, source, sha, engine, now, gen_version))
            deck_id = int(cur.lastrowid)
            for c in cards:
                self._insert_card(deck_id, c, now)
        return deck_id

    def _insert_card(self, deck_id: int, c: CardDraft, now: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO cards(deck_id, kind, question, answer, page, section, fsrs, due, created, distractors,"
            " quiz_answer) VALUES (?,?,?,?,?,?,NULL,?,?,?,?)",
            (deck_id, c.kind, c.question, c.answer, c.page, c.section, now, now,
             json.dumps(c.distractors, ensure_ascii=False) if c.distractors else None,
             c.quiz_answer or None))
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
        """Une carte dont la question ou la réponse change perd ses propositions de QCM."""
        with self.conn:
            self.conn.execute(
                "UPDATE cards SET distractors = CASE WHEN question = ? AND answer = ? THEN distractors END,"
                " quiz_answer = CASE WHEN question = ? AND answer = ? THEN quiz_answer END,"
                " kind=?, question=?, answer=?, page=? WHERE id=?",
                (question, answer, question, answer, kind, question, answer, page, card_id))

    def set_distractors(self, card_id: int, distractors: list[str], quiz_answer: str = "") -> None:
        with self.conn:
            self.conn.execute("UPDATE cards SET distractors = ?, quiz_answer = ? WHERE id = ?",
                              (json.dumps(distractors, ensure_ascii=False) if distractors else None,
                               quiz_answer or None, card_id))

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

    def set_exam_date(self, deck_ids: list[int], exam_date: str | None) -> None:
        """Date d'examen (AAAA-MM-JJ) de ces cours ; None l'enlève."""
        with self.conn:
            self.conn.executemany("UPDATE decks SET exam_date = ? WHERE id = ?",
                                  [(exam_date, int(d)) for d in deck_ids])

    def set_deck_source(self, deck_id: int, source: str) -> None:
        """Nouvel emplacement du fichier d'un cours (déplacé ou renommé)."""
        with self.conn:
            self.conn.execute("UPDATE decks SET source = ? WHERE id = ?", (source, deck_id))

    def replace_deck_cards(self, deck_id: int, drafts: list[CardDraft], matches: dict[int, int], *,
                           source: str | None, sha: str | None, engine: str, gen_version: int) -> tuple[int, int, int]:
        """Remplace les cartes d'un cours par une nouvelle fabrication. `matches` : indice dans `drafts` →
        identifiant de l'ancienne carte qui dit la même chose ; celle-ci prend le nouveau texte et garde sa
        progression (planning, historique, mise de côté). Les anciennes cartes sans équivalent sont retirées.
        Retourne (cartes qui gardent leur progression, nouvelles cartes, cartes retirées)."""
        now = iso(utcnow())
        old_ids = {int(r[0]) for r in self.conn.execute("SELECT id FROM cards WHERE deck_id = ?", (deck_id,))}
        kept = {old for old in matches.values() if old in old_ids}
        with self.conn:
            for i, c in enumerate(drafts):
                old = matches.get(i)
                if old in kept:
                    self.conn.execute(
                        "UPDATE cards SET kind=?, question=?, answer=?, page=?, section=?, distractors=?, quiz_answer=?"
                        " WHERE id=?",
                        (c.kind, c.question, c.answer, c.page, c.section,
                         json.dumps(c.distractors, ensure_ascii=False) if c.distractors else None,
                         c.quiz_answer or None, old))
                else:
                    self._insert_card(deck_id, c, now)
            gone = old_ids - kept
            self.conn.executemany("DELETE FROM cards WHERE id = ?", [(i,) for i in gone])
            self.conn.execute("UPDATE decks SET source = ?, sha256 = ?, engine = ?, gen_version = ? WHERE id = ?",
                              (source, sha, engine, gen_version, deck_id))
        return len(kept), len(drafts) - len(kept), len(gone)

    # ------------------------------------------------------------ résultats
    def record_quiz_answer(self, card_id: int, correct: bool, source: str = "qcm") -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO quiz_answers(card_id, ts, correct, source) VALUES (?,?,?,?)",
                                    (card_id, iso(utcnow()), int(bool(correct)), source))
        return int(cur.lastrowid)

    def set_quiz_answer(self, answer_id: int, correct: bool) -> None:
        """Corrige un résultat (l'étudiant estime que sa réponse écrite était juste)."""
        with self.conn:
            self.conn.execute("UPDATE quiz_answers SET correct = ? WHERE id = ?", (int(bool(correct)), answer_id))

    def answer_history(self) -> dict[int, list[float]]:
        """Pour chaque carte, ses résultats du plus ancien au plus récent : 1 = juste, 0 = faux, 0,5 = de justesse.
        Révisions (« Bien »/« Facile » = juste, « Difficile » = de justesse) et QCM / examens blancs."""
        out: dict[int, list[float]] = {}
        rows = self.conn.execute(
            "SELECT card_id, ts, CASE WHEN rating >= 3 THEN 1.0 WHEN rating = 2 THEN 0.5 ELSE 0.0 END FROM reviews"
            " UNION ALL SELECT card_id, ts, CAST(correct AS REAL) FROM quiz_answers ORDER BY 2")
        for card_id, _, result in rows:
            out.setdefault(int(card_id), []).append(float(result))
        return out

    def reviews_since(self, since: datetime) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM reviews WHERE ts >= ? ORDER BY ts", (iso(since),)))

    # ------------------------------------------------------------- conversions
    @staticmethod
    def _deck(r: sqlite3.Row) -> Deck:
        return Deck(r["id"], r["subject"], r["title"], r["source"], r["engine"], r["created"], r["exam_date"],
                    r["gen_version"])

    @staticmethod
    def _card(r: sqlite3.Row) -> Card:
        try:
            wrong = json.loads(r["distractors"]) if r["distractors"] else []
        except ValueError:
            wrong = []
        return Card(r["id"], r["deck_id"], r["kind"], r["question"], r["answer"], r["page"], r["section"],
                    r["fsrs"], r["due"], bool(r["suspended"]),
                    [str(w) for w in wrong] if isinstance(wrong, list) else [], r["quiz_answer"] or "")
