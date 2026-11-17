"""« Cette carte est mal faite » : l'IA la réécrit à partir de la page du cours."""

from __future__ import annotations

import json
from collections.abc import Callable

from revise.models import ReviseError

SCHEMA = {
    "type": "object",
    "properties": {"question": {"type": "string"}, "answer": {"type": "string"}, "change": {"type": "string"}},
    "required": ["question", "answer", "change"],
    "additionalProperties": False,
}

SYSTEM = """Tu corriges une carte de révision (question / réponse) qu'un étudiant juge mal faite : question \
floue ou incomplète, réponse fausse, coupée ou hors sujet, texte à trous qui ne veut rien dire.

- Réécris la carte pour qu'elle porte sur la même notion, se comprenne seule et ait une réponse exacte, \
courte (1 à 4 phrases ou une courte liste).
- Appuie-toi d'abord sur le texte de la page du cours s'il est donné. N'invente rien qui n'y soit pas ou qui \
ne soit pas une conséquence directe et sûre.
- Garde la langue de la carte. Markdown simple ; blocs ``` pour du code ; formules en texte lisible.
- "change" : une phrase qui dit ce que tu as corrigé.
- Réponds uniquement avec un objet JSON, sans texte autour, de la forme :
{"question": "…", "answer": "…", "change": "…"}"""

Chat = Callable[[str, str, dict], str]


def rewrite(question: str, answer: str, page_text: str, subject: str, course: str, chat: Chat
            ) -> tuple[str, str, str]:
    """(nouvelle question, nouvelle réponse, ce qui a changé)."""
    source = page_text.strip()[:6000] or "(texte de la page indisponible)"
    user = (f"Matière : {subject or 'non précisée'}.\nCours : {course or 'non précisé'}.\n\n"
            f"Texte de la page du cours :\n{source}\n\nCarte à corriger :\nQuestion : {question}\n"
            f"Réponse : {answer}\n\nRéécris cette carte.")
    raw = chat(SYSTEM, user, SCHEMA).strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise ReviseError("L'IA n'a pas su réécrire la carte : réessaie.")
    q, a = str(data.get("question") or "").strip(), str(data.get("answer") or "").strip()
    if not q or not a:
        raise ReviseError("L'IA n'a pas su réécrire la carte : réessaie.")
    return q, a, str(data.get("change") or "").strip()
