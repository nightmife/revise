"""Partage de cours : fichier « .revise » (cartes et réponses pièges, sans la progression) et export pour Anki.

Un fichier .revise est du JSON. Il vient de quelqu'un d'autre : tout ce qu'il contient est vérifié à la lecture."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from revise import __version__
from revise.db import Database, deck_label
from revise.models import CardDraft, ReviseError

EXTENSION = ".revise"
FORMAT = "revise-cours"
FORMAT_VERSION = 2  # 2 : `quiz_answer` (bonne réponse au format des pièges)
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TEXT = 20_000        # longueur maximale d'une question ou d'une réponse
MAX_DISTRACTORS = 10


@dataclass
class Received:
    name: str
    cards: int
    deck_id: int | None
    skipped: bool = False  # déjà présent


def is_share_file(path: Path) -> bool:
    return path.suffix.lower() == EXTENSION


def _file_name(source: str | None) -> str:
    """Nom du fichier d'origine, sans son dossier (qui contient souvent le nom de l'utilisateur)."""
    if not source:
        return ""
    return PureWindowsPath(source).name if "\\" in source else PurePosixPath(source).name


def _cards_payload(db: Database, deck_id: int) -> list[dict]:
    out = []
    for c in db.cards(deck_id=deck_id, include_suspended=False):
        card = {"kind": c.kind, "question": c.question, "answer": c.answer, "page": c.page, "section": c.section}
        if c.distractors:
            card["distractors"] = c.distractors
        if c.quiz_answer:
            card["quiz_answer"] = c.quiz_answer
        out.append(card)
    return out


def _fingerprint(cards: list[dict]) -> str:
    raw = json.dumps(cards, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------------ export ---

def export_courses(db: Database, deck_ids: list[int], dest: Path) -> int:
    """Écrit les cours dans `dest` ; renvoie le nombre de cartes. Les cartes « à ne plus poser » sont laissées."""
    courses = []
    total = 0
    for deck_id in deck_ids:
        d = db.deck(deck_id)
        if d is None:
            continue
        cards = _cards_payload(db, deck_id)
        if not cards:
            continue
        row = db.conn.execute("SELECT sha256 FROM decks WHERE id = ?", (deck_id,)).fetchone()
        courses.append({"subject": d.subject, "title": d.title, "file": _file_name(d.source), "engine": d.engine,
                        "sha256": row["sha256"] or _fingerprint(cards), "cards": cards})
        total += len(cards)
    if not courses:
        raise ReviseError("Aucune carte à partager dans les cours choisis.")
    data = {"format": FORMAT, "version": FORMAT_VERSION, "app": __version__, "courses": courses}
    try:
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        raise ReviseError(f"Impossible d'écrire {dest.name} ({e.strerror or e})") from e
    return total


# ------------------------------------------------------------------ import ---

def _text(value, limit: int = MAX_TEXT) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _draft(raw) -> CardDraft | None:
    if not isinstance(raw, dict):
        return None
    page = raw.get("page")
    wrong = raw.get("distractors")
    distractors = [_text(w, 2000) for w in wrong if isinstance(w, str)][:MAX_DISTRACTORS] if isinstance(wrong, list) else []
    draft = CardDraft(_text(raw.get("kind"), 20), _text(raw.get("question")), _text(raw.get("answer")),
                      page if isinstance(page, int) and not isinstance(page, bool) else None,
                      _text(raw.get("section"), 300), [w for w in distractors if w],
                      _text(raw.get("quiz_answer"), 2000))
    return draft.normalized()


def read_courses(path: Path) -> list[dict]:
    """Cours d'un fichier .revise, vérifiés : [{subject, title, file, engine, sha256, cards: [CardDraft]}]."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ReviseError(f"{path.name} est trop gros pour être un cours partagé.")
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ReviseError(f"Impossible de lire {path.name} ({e.strerror or e})") from e
    except ValueError as e:  # JSON invalide ou texte qui n'est pas de l'UTF-8
        raise ReviseError(f"{path.name} n'est pas un cours partagé par revise (fichier abîmé ?).") from e
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("courses"), list):
        raise ReviseError(f"{path.name} n'est pas un cours partagé par revise.")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ReviseError(f"{path.name} n'est pas un cours partagé par revise.")
    if version > FORMAT_VERSION:
        raise ReviseError(f"{path.name} vient d'une version plus récente de revise : mets l'application à jour.")
    out = []
    for raw in data["courses"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("cards"), list):
            continue
        cards = [c for c in map(_draft, raw["cards"]) if c is not None]
        if not cards:
            continue
        sha = raw.get("sha256")
        if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
            sha = None
        file = _file_name(_text(raw.get("file"), 300))
        out.append({"subject": _text(raw.get("subject"), 200) or "Mes cours",
                    "title": _text(raw.get("title"), 300) or Path(file).stem or path.stem,
                    "file": file, "engine": _text(raw.get("engine"), 40) or "partage", "sha256": sha, "cards": cards})
    if not out:
        raise ReviseError(f"{path.name} ne contient aucune carte.")
    return out


def import_file(db: Database, path: Path, subject: str | None = None) -> list[Received]:
    """Ajoute les cours d'un fichier .revise (ceux déjà présents sont laissés tels quels)."""
    path = path.expanduser()
    if not path.is_file():
        raise ReviseError(f"Fichier introuvable : {path}")
    results = []
    for course in read_courses(path):
        sha = course["sha256"] or _fingerprint(
            [{"q": c.question, "a": c.answer} for c in course["cards"]])
        existing = db.find_deck_by_hash(sha)
        if existing:
            results.append(Received(deck_label(existing), 0, existing.id, skipped=True))
            continue
        deck_id = db.add_deck(subject or course["subject"], course["title"], course["file"] or None, sha,
                              course["engine"], course["cards"])
        added = db.deck(deck_id)
        results.append(Received(deck_label(added) if added else course["title"], len(course["cards"]), deck_id))
    return results


# -------------------------------------------------------------------- Anki ---

def _anki_field(text: str) -> str:
    """Markdown simple → HTML d'Anki, sur une seule ligne (un champ ne contient ni tabulation ni saut de ligne)."""
    out = html.escape(text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    "), quote=False)
    out = re.sub(r"```[^\n]*\n(.*?)```", lambda m: "<pre>" + m.group(1).rstrip("\n") + "</pre>", out, flags=re.S)
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
    return out.replace("\n", "<br>")


def _anki_tag(text: str) -> str:
    return re.sub(r"\s+", "_", text.strip()) or "revise"


def export_anki(db: Database, deck_ids: list[int], dest: Path) -> int:
    """Fichier texte à importer dans Anki (Fichier → Importer) : recto, verso, étiquettes."""
    lines = ["#separator:tab", "#html:true", "#columns:Recto\tVerso\tÉtiquettes", "#tags column:3"]
    total = 0
    for deck_id in deck_ids:
        d = db.deck(deck_id)
        if d is None:
            continue
        tags = f"{_anki_tag(d.subject)} {_anki_tag(deck_label(d))}"
        for c in db.cards(deck_id=deck_id, include_suspended=False):
            lines.append(f"{_anki_field(c.question)}\t{_anki_field(c.answer)}\t{tags}")
            total += 1
    if not total:
        raise ReviseError("Aucune carte à exporter dans les cours choisis.")
    try:
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        raise ReviseError(f"Impossible d'écrire {dest.name} ({e.strerror or e})") from e
    return total
