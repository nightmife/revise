"""« Explique-moi » : l'IA explique la réponse d'une carte avec d'autres mots."""

from __future__ import annotations

import json
from collections.abc import Callable

from revise.models import ReviseError

SCHEMA = {
    "type": "object",
    "properties": {"explanation": {"type": "string"}},
    "required": ["explanation"],
    "additionalProperties": False,
}

SYSTEM = """Tu es un enseignant patient. Un étudiant révise avec des cartes question/réponse et n'a pas compris \
la réponse d'une carte. Explique-la-lui.

- 3 à 6 phrases simples, dans la langue de la carte, en le tutoyant.
- Reformule l'idée avec d'autres mots que la réponse, puis donne un exemple concret ou une image qui aide à \
s'en souvenir. S'il existe un piège classique sur cette notion, signale-le en une phrase.
- Reste dans le sujet de la carte. N'ajoute aucun fait dont tu n'es pas sûr.
- Markdown simple (gras, `code`, blocs ``` pour du code) ; formules en texte lisible (x^2, O(n log n)).
- Réponds uniquement avec un objet JSON, sans texte autour, de la forme : {"explanation": "ton explication"}"""

Chat = Callable[[str, str, dict], str]


def explain(question: str, answer: str, subject: str, course: str, chat: Chat) -> str:
    """Explication de la carte, écrite par l'IA (`chat` d'un moteur)."""
    user = (f"Matière : {subject or 'non précisée'}.\nCours : {course or 'non précisé'}.\n\n"
            f"Question de la carte :\n{question}\n\nRéponse de la carte :\n{answer}\n\nExplique cette réponse.")
    raw = chat(SYSTEM, user, SCHEMA).strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    text = data.get("explanation") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ReviseError("L'IA n'a pas su répondre : réessaie.")
    return text.strip()
