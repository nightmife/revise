"""Mauvaises réponses de QCM (« pièges ») écrites par une IA.

Sans elles, le QCM ne peut proposer que les réponses d'autres cartes : elles ne répondent
pas à la question posée, et la bonne réponse se devine sans connaître le cours."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from revise.engines import Progress
from revise.models import CardDraft, ReviseError

BATCH = 10            # questions par appel à l'IA
WANTED = 3            # mauvaises réponses par question
MAX_ANSWER_CHARS = 700

SYSTEM = """Tu fabriques les mauvaises réponses d'un QCM de révision pour un étudiant.
Pour chaque question numérotée, on te donne la bonne réponse. Écris exactement 3 mauvaises réponses.

Règles :
- Chaque mauvaise réponse répond à LA MÊME question, sur le même sujet, avec le vocabulaire du \
cours : quelqu'un qui n'a pas appris le cours doit hésiter entre les quatre propositions.
- Chaque mauvaise réponse est FAUSSE sans discussion pour quelqu'un qui connaît le cours. Jamais \
une reformulation de la bonne réponse, jamais une réponse à moitié juste.
- Même forme que la bonne réponse : à peu près la même longueur, le même niveau de détail, le \
même style (phrase, liste, formule, code, date, nom propre…). La bonne réponse ne doit pas se \
repérer parce qu'elle est plus longue ou plus précise que les autres.
- Appuie-toi sur les confusions classiques : notion voisine, propriété inversée, valeur proche, \
cause et conséquence échangées, mauvais auteur ou mauvaise date, condition oubliée ou ajoutée.
- Texte à trous (question contenant [...]) : donne 3 autres mots ou expressions qui s'insèrent \
correctement dans la phrase, du même domaine que la bonne réponse.
- Si la bonne réponse commence par « Oui » ou « Non », une mauvaise réponse au moins commence \
par l'inverse.
- Interdits : « toutes les réponses », « aucune de ces réponses », les blagues, les explications.
- Écris dans la langue de la question, avec le même Markdown que la bonne réponse.
- Réponds uniquement avec un objet JSON, sans texte autour, de la forme :
{"items": [{"n": 1, "wrong": ["…", "…", "…"]}, {"n": 2, "wrong": ["…", "…", "…"]}]}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "wrong": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["n", "wrong"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

# (consignes système, message, schéma JSON attendu) -> réponse brute du modèle
SchemaChat = Callable[[str, str, dict], str]

_BANNED = re.compile(r"toutes? (les|ces) (réponses|propositions)|aucune (de ces|des) (réponses|propositions)"
                     r"|all of the above|none of the above", re.IGNORECASE)


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[`*_.,;:!?«»\"'’()]", " ", s.lower()).split())


def clean(answer: str, wrong: list) -> list[str]:
    """Mauvaises réponses utilisables : non vides, différentes de la bonne et entre elles."""
    seen = {_norm(answer)}
    out: list[str] = []
    for w in wrong:
        if not isinstance(w, str):
            continue
        w = w.strip()
        key = _norm(w)
        if not key or key in seen or _BANNED.search(w) or len(w) > 4 * max(len(answer), 60):
            continue
        seen.add(key)
        out.append(w)
    return out[:WANTED]


def parse(raw: str, count: int) -> dict[int, list]:
    """Réponse du modèle -> {numéro de question (à partir de 1) : mauvaises réponses}."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    out: dict[int, list] = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and isinstance(it.get("n"), int) and not isinstance(it["n"], bool) \
                and 1 <= it["n"] <= count and isinstance(it.get("wrong"), list):
            out.setdefault(it["n"], it["wrong"])
    return out


def ask(items: list[tuple[str, str, str]], subject: str, chat: SchemaChat) -> list[list[str]]:
    """Mauvaises réponses pour un lot de (type, question, bonne réponse). Liste vide si l'IA n'a rien
    donné d'utilisable pour une question."""
    parts = [f"Matière : {subject}."]
    for n, (kind, question, answer) in enumerate(items, start=1):
        label = " (texte à trous)" if kind == "cloze" else " (code)" if kind == "code" else ""
        parts.append(f"### Question {n}{label}\n{question.strip()}\n\nBonne réponse :\n"
                     f"{answer.strip()[:MAX_ANSWER_CHARS]}")
    found = parse(chat(SYSTEM, "\n\n".join(parts), SCHEMA), len(items))
    return [clean(answer, found.get(n, [])) for n, (_, _, answer) in enumerate(items, start=1)]


def add_to_drafts(cards: list[CardDraft], subject: str, chat: SchemaChat, progress: Progress, label: str) -> None:
    """Complète les cartes d'un import. Une panne de l'IA ici ne fait pas perdre les cartes :
    celles qui restent sans mauvaises réponses pourront être préparées plus tard depuis l'onglet QCM."""
    for start in range(0, len(cards), BATCH):
        batch = cards[start:start + BATCH]
        progress(f"{label} : réponses pièges du QCM — {min(start + BATCH, len(cards))}/{len(cards)}")
        try:
            wrong = ask([(c.kind, c.question, c.answer) for c in batch], subject, chat)
        except ReviseError:
            return
        for c, w in zip(batch, wrong):
            c.distractors = w


def prepare(db, deck_ids: list[int], chat: SchemaChat, progress: Progress,
            should_stop: Callable[[], bool] = lambda: False) -> int:
    """Prépare les mauvaises réponses des cartes déjà enregistrées qui n'en ont pas.
    Chaque lot est enregistré aussitôt : on peut arrêter et reprendre. Retourne le nombre de cartes complétées."""
    todo = [c for c in db.cards(deck_ids=deck_ids, include_suspended=False) if not c.distractors]
    subjects = {d.id: d.subject for d in db.decks()}
    done = filled = 0
    for deck_id in dict.fromkeys(c.deck_id for c in todo):
        cards = [c for c in todo if c.deck_id == deck_id]
        for start in range(0, len(cards), BATCH):
            if should_stop():
                return filled
            batch = cards[start:start + BATCH]
            progress(f"Préparation des réponses pièges : {done}/{len(todo)} questions")
            wrong = ask([(c.kind, c.question, c.answer) for c in batch], subjects.get(deck_id, ""), chat)
            for c, w in zip(batch, wrong):
                if w:
                    db.set_distractors(c.id, w)
                    filled += 1
            done += len(batch)
    return filled


def default_engine_name() -> str:
    """IA utilisée pour préparer les pièges de cours déjà importés : celle choisie pour les imports,
    sinon l'IA en ligne si une clé est enregistrée (rapide), sinon l'IA intégrée."""
    from revise import config
    from revise.engines import online

    wanted = config.load().get("engine")
    return "en-ligne" if wanted == "en-ligne" or (wanted != "ia" and online.settings()["key"]) else "ia"


def default_engine():
    from revise.engines import online
    from revise.engines.embedded import EmbeddedEngine

    return online.OnlineEngine() if default_engine_name() == "en-ligne" else EmbeddedEngine()
