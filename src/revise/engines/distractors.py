"""Mauvaises réponses de QCM (« pièges ») écrites par une IA.

Sans elles, le QCM ne peut proposer que les réponses d'autres cartes : elles ne répondent
pas à la question posée, et la bonne réponse se devine sans connaître le cours."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from revise.engines import Progress
from revise.models import CardDraft, ReviseError
from revise.quiz import is_prepared

BATCH = 10            # questions par appel à l'IA
WANTED = 3            # mauvaises réponses par question
MAX_ANSWER_CHARS = 700

SYSTEM = """Tu fabriques les quatre propositions d'un QCM de révision pour un étudiant.
Pour chaque question numérotée, on te donne la réponse du cours. Écris :
- "right" : la bonne réponse telle qu'elle sera proposée dans le QCM. Garde exactement son sens, \
mais enlève ce qui la ferait repérer : explications, exemples, justifications et précisions en \
plus. Si elle est déjà courte, recopie-la telle quelle. Ne la rends jamais fausse ni incomplète \
sur l'essentiel.
- "wrong" : exactement 3 mauvaises réponses.

Règle la plus importante : en voyant les quatre propositions (right + les 3 wrong), personne ne \
doit pouvoir deviner la bonne à sa forme. Elles ont :
- la même longueur, à 20 % près (compte les mots) ;
- la même structure (phrase, liste, formule, code, date, nom propre…) et le même début de phrase \
quand c'est possible ;
- le même niveau de détail et de vocabulaire technique. Si "right" contient une justification \
(« car… », « parce que… ») ou une condition, chaque mauvaise réponse en contient une aussi, \
fausse mais crédible. La bonne ne doit être ni la plus longue, ni la plus précise, ni la seule \
nuancée.

Autres règles :
- Chaque mauvaise réponse répond à LA MÊME question, sur le même sujet, avec le vocabulaire du \
cours : quelqu'un qui n'a pas appris le cours doit hésiter entre les quatre propositions.
- Chaque mauvaise réponse est FAUSSE sans discussion pour quelqu'un qui connaît le cours. Jamais \
une reformulation de la bonne réponse, jamais une réponse à moitié juste.
- Appuie-toi sur les confusions classiques : notion voisine, propriété inversée, valeur proche, \
cause et conséquence échangées, mauvais auteur ou mauvaise date, condition oubliée ou ajoutée.
- Texte à trous (question contenant [...]) : "right" est seulement le ou les mots qui manquent ; \
donne 3 autres mots ou expressions qui s'insèrent correctement dans la phrase, du même domaine.
- Question (code) : recopie la bonne réponse sans la changer dans "right" ; les mauvaises sont du \
code de même taille, presque juste mais faux.
- Si la bonne réponse commence par « Oui » ou « Non », une mauvaise réponse au moins commence \
par l'inverse.
- Interdits : « toutes les réponses », « aucune de ces réponses », les blagues.
- Écris dans la langue de la question, avec le même Markdown que la bonne réponse.
- Réponds uniquement avec un objet JSON, sans texte autour, de la forme :
{"items": [{"n": 1, "right": "…", "wrong": ["…", "…", "…"]}, {"n": 2, "right": "…", "wrong": ["…", "…", "…"]}]}"""

# Deuxième essai, pour les questions dont les propositions n'avaient pas la même longueur.
RETRY = """

ATTENTION : à ton premier essai, la bonne réponse se repérait à sa longueur. Pour chaque question, \
on t'indique la longueur visée : "right" ET chacune des 3 mauvaises réponses doivent la respecter \
(raccourcis la bonne, ou allonge les mauvaises avec des détails faux mais crédibles)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "right": {"type": "string"},
                    "wrong": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["n", "right", "wrong"],
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


def clean(answer: str, wrong: list, right: str = "") -> list[str]:
    """Mauvaises réponses utilisables : non vides, différentes de la bonne et entre elles."""
    seen = {_norm(answer), _norm(right)} - {""}
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


def clean_right(answer: str, right) -> str:
    """Bonne réponse réécrite par l'IA, ou celle du cours si la réécriture est vide ou suspecte."""
    if not isinstance(right, str) or not right.strip() or _BANNED.search(right):
        return answer.strip()
    right = right.strip()
    return right if len(right) <= len(answer.strip()) * 1.3 + 40 else answer.strip()


def imbalance(right: str, wrong: list[str]) -> float:
    """0 si la bonne réponse a la longueur des mauvaises ; au-delà de 1, elle se repère à sa longueur."""
    if not wrong:
        return 0.0
    mean = sum(len(w) for w in wrong) / len(wrong)
    gap = abs(len(right) - mean)
    return gap / max(25.0, 0.35 * max(len(right), mean))


def parse(raw: str, count: int) -> dict[int, tuple]:
    """Réponse du modèle -> {numéro de question (à partir de 1) : (bonne réponse réécrite, mauvaises réponses)}."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    out: dict[int, tuple] = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and isinstance(it.get("n"), int) and not isinstance(it["n"], bool) \
                and 1 <= it["n"] <= count and isinstance(it.get("wrong"), list):
            out.setdefault(it["n"], (it.get("right"), it["wrong"]))
    return out


def _request(items: list[tuple[str, str, str]], subject: str, chat: SchemaChat,
             targets: list[int] | None = None) -> list[tuple[str, list[str]]]:
    parts = [f"Matière : {subject}."]
    for n, (kind, question, answer) in enumerate(items, start=1):
        label = " (texte à trous)" if kind == "cloze" else " (code)" if kind == "code" else ""
        target = f"\n\nLongueur visée pour chaque proposition : environ {targets[n - 1]} caractères." \
            if targets else ""
        parts.append(f"### Question {n}{label}\n{question.strip()}\n\nBonne réponse :\n"
                     f"{answer.strip()[:MAX_ANSWER_CHARS]}{target}")
    found = parse(chat(SYSTEM + (RETRY if targets else ""), "\n\n".join(parts), SCHEMA), len(items))
    out = []
    for n, (kind, _, answer) in enumerate(items, start=1):
        raw_right, raw_wrong = found.get(n, (None, []))
        right = answer.strip() if kind == "code" else clean_right(answer, raw_right)
        out.append((right, clean(answer, raw_wrong, right)))
    return out


def ask(items: list[tuple[str, str, str]], subject: str, chat: SchemaChat) -> list[tuple[str, list[str]]]:
    """Propositions de QCM pour un lot de (type, question, bonne réponse) : [(bonne réponse réécrite,
    mauvaises réponses)]. Liste de mauvaises réponses vide si l'IA n'a rien donné d'utilisable.
    Les questions dont la bonne réponse se repère à sa longueur sont redemandées une fois."""
    got = _request(items, subject, chat)
    redo = [i for i, (right, wrong) in enumerate(got) if items[i][0] != "code" and imbalance(right, wrong) > 1]
    if redo:
        try:
            targets = [max(len(got[i][0]), 1) if not got[i][1] else
                       round((len(got[i][0]) + sum(len(w) for w in got[i][1]) / len(got[i][1])) / 2)
                       for i in redo]
            again = _request([items[i] for i in redo], subject, chat, targets)
        except ReviseError:
            again = []
        for i, (right, wrong) in zip(redo, again):
            if len(wrong) >= len(got[i][1]) and imbalance(right, wrong) < imbalance(*got[i]):
                got[i] = (right, wrong)
    return got


def add_to_drafts(cards: list[CardDraft], subject: str, chat: SchemaChat, progress: Progress, label: str,
                  batch_size: int = BATCH) -> None:
    """Complète les cartes d'un import. Une panne de l'IA ici ne fait pas perdre les cartes :
    celles qui restent sans mauvaises réponses pourront être préparées plus tard depuis l'onglet QCM."""
    for start in range(0, len(cards), batch_size):
        batch = cards[start:start + batch_size]
        progress(f"{label} : réponses pièges du QCM — {min(start + batch_size, len(cards))}/{len(cards)}")
        try:
            got = ask([(c.kind, c.question, c.answer) for c in batch], subject, chat)
        except ReviseError:
            return
        for c, (right, wrong) in zip(batch, got):
            if wrong:
                c.distractors, c.quiz_answer = wrong, right


def prepare(db, deck_ids: list[int], chat: SchemaChat, progress: Progress,
            should_stop: Callable[[], bool] = lambda: False, batch_size: int = BATCH) -> int:
    """Prépare les propositions de QCM des cartes qui n'en ont pas, ou qui n'ont que d'anciennes mauvaises réponses
    (d'avant la version 0.8, souvent plus courtes que la bonne). Chaque lot est enregistré aussitôt : on peut
    arrêter et reprendre. Retourne le nombre de cartes complétées."""
    todo = [c for c in db.cards(deck_ids=deck_ids, include_suspended=False) if not is_prepared(c)]
    subjects = {d.id: d.subject for d in db.decks()}
    done = filled = 0
    for deck_id in dict.fromkeys(c.deck_id for c in todo):
        cards = [c for c in todo if c.deck_id == deck_id]
        for start in range(0, len(cards), batch_size):
            if should_stop():
                return filled
            batch = cards[start:start + batch_size]
            progress(f"Préparation des réponses pièges : {done}/{len(todo)} questions")
            got = ask([(c.kind, c.question, c.answer) for c in batch], subjects.get(deck_id, ""), chat)
            for c, (right, wrong) in zip(batch, got):
                if wrong:
                    db.set_distractors(c.id, wrong, right)
                    filled += 1
            done += len(batch)
    return filled


def default_engine_name() -> str:
    """IA utilisée pour préparer les pièges de cours déjà importés : celle choisie pour les imports,
    sinon l'IA en ligne si une clé est enregistrée (rapide), sinon l'IA intégrée."""
    from revise import config
    from revise.engines import online

    wanted = config.load().get("engine")
    if wanted == "abonnement":
        return wanted
    return "en-ligne" if wanted == "en-ligne" or (wanted != "ia" and online.has_key()) else "ia"


def default_engine():
    from revise.engines import online
    from revise.engines.embedded import EmbeddedEngine

    name = default_engine_name()
    if name == "abonnement":
        from revise.engines.claude_code import ClaudeCodeEngine
        return ClaudeCodeEngine()
    return online.OnlineEngine() if name == "en-ligne" else EmbeddedEngine()
