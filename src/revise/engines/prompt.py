"""Ce qui est commun aux moteurs à IA : consignes, schéma de sortie, découpage du
texte du cours, vérification des cartes produites."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from revise.engines import Progress
from revise.engines.simple import title_from_filename
from revise.models import CardDraft, ReviseError
from revise.pdf import page_texts

CHUNK_CHARS = 7000
CHUNK_PAGES = 8

SYSTEM = """Tu es un enseignant qui prépare des cartes de révision (répétition espacée) \
pour un étudiant, à partir des diapositives d'un cours magistral.

Règles pour de bonnes cartes :
- Une seule idée par carte (atomique). Préfère plusieurs petites cartes à une grosse.
- La question doit se comprendre sans voir la diapositive : donne le contexte nécessaire.
- Couvre les notions importantes : définitions, propriétés, théorèmes, algorithmes, \
complexités, différences entre notions voisines, pièges classiques, exemples à savoir refaire.
- Ignore le plan du cours, les consignes administratives, la bibliographie, les remerciements.
- Réponses courtes et exactes (1 à 4 phrases ou une courte liste). N'invente rien qui ne soit \
pas dans le cours ou qui ne soit pas une conséquence directe et sûre de son contenu.
- Types :
  * "qa" : question / réponse.
  * "cloze" : texte à trous ; la question contient une phrase du cours où l'élément clé est \
remplacé par [...], la réponse est l'élément masqué.
  * "code" : la question demande d'écrire, de compléter ou de prédire la sortie d'un court \
morceau de code ; mets le code en Markdown avec des blocs ``` et le bon langage.
- Utilise le Markdown simple ; formules en texte lisible (ex. O(n log n), x^2).
- "page" = numéro de la page du PDF où se trouve l'information.
- "section" = titre court de la partie du cours.
- Écris dans la langue du cours."""

CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Titre court du cours"},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["qa", "cloze", "code"]},
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "page": {"type": "integer"},
                    "section": {"type": "string"},
                },
                "required": ["kind", "question", "answer", "page", "section"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "cards"],
    "additionalProperties": False,
}

RULES = """

Consignes supplémentaires :
- Le cours t'est donné sous forme de texte extrait d'un PDF ; chaque page commence \
par une ligne « === Page N === ». Le texte peut contenir des coupures de ligne \
parasites : reconstitue les phrases.
- Vise 2 à 4 cartes par page qui contient de la matière, 0 pour une page de titre \
ou de plan.
- N'utilise que ce qui est écrit dans le texte fourni. Si tu n'es pas sûr, ne fais \
pas la carte.
- Ne fais jamais de question du type « Que dit la page 3 ? » ou « De quoi parle ce \
cours ? ».
- Réponds uniquement avec un objet JSON, sans texte autour, de la forme :
{"title": "Tris par comparaison", "cards": [
{"kind": "qa", "question": "Quelle est la complexité dans le pire cas du tri \
fusion ?", "answer": "O(n log n), quel que soit l'ordre initial du tableau.", \
"page": 4, "section": "Tri fusion"},
{"kind": "cloze", "question": "Un tri est dit [...] s'il conserve l'ordre relatif \
des éléments de même clé.", "answer": "stable", "page": 2, "section": "Définitions"}]}
"""

Chat = Callable[[str, str], str]  # (consignes système, message) -> réponse brute du modèle


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-zà-ÿ0-9]{4,}", s.lower()))


def grounded(card: CardDraft, source_words: set[str]) -> bool:
    """Vrai si la carte reprend assez de vocabulaire du texte source.

    Sert à écarter les cartes inventées de toutes pièces par le modèle."""
    words = _words(card.question + " " + card.answer)
    if len(words) < 3:
        return True
    return len(words & source_words) / len(words) >= 0.4


def text_chunks(pages: list[str]) -> list[tuple[int, int, str]]:
    """Regroupe les pages en morceaux (première page, dernière page, texte)."""
    chunks: list[tuple[int, int, str]] = []
    first = 0
    parts: list[str] = []
    size = 0
    for n, text in enumerate(pages, start=1):
        text = text.strip()
        if not text:
            continue
        text = text[:CHUNK_CHARS]
        if parts and (size + len(text) > CHUNK_CHARS or n - first >= CHUNK_PAGES):
            chunks.append((first, n - 1, "\n\n".join(parts)))
            parts, size = [], 0
        if not parts:
            first = n
        parts.append(f"=== Page {n} ===\n{text}")
        size += len(text)
    if parts:
        chunks.append((first, len(pages), "\n\n".join(parts)))
    return chunks


def parse_cards(raw: str, first: int, last: int) -> tuple[str, list[CardDraft]] | None:
    """Cartes contenues dans la réponse du modèle, ou None si elle est inexploitable."""
    raw = raw.strip()
    if raw.startswith("```"):  # certains modèles entourent le JSON d'un bloc de code
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        return None
    cards = []
    for c in data["cards"]:
        if not isinstance(c, dict):
            continue
        page = c.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or not first <= page <= last:
            page = first if first == last else None
        draft = CardDraft(str(c.get("kind") or "qa"), str(c.get("question") or ""), str(c.get("answer") or ""),
                          page, str(c.get("section") or "")).normalized()
        if draft:
            cards.append(draft)
    return str(data.get("title") or "").strip(), cards


def generate_cards(pdf: Path, subject: str, progress: Progress, chat: Chat, label: str) -> tuple[str, list[CardDraft]]:
    """Génère les cartes d'un PDF morceau par morceau avec la fonction `chat` d'un moteur."""
    pages = page_texts(pdf)
    chunks = text_chunks(pages)
    if not chunks:
        raise ReviseError(f"{pdf.name} ne contient pas de texte (PDF scanné ?) : l'IA lit le texte du PDF.")
    title = ""
    cards: list[CardDraft] = []
    seen: set[str] = set()
    for i, (first, last, text) in enumerate(chunks, start=1):
        progress(f"{label} : pages {first}-{last} — morceau {i}/{len(chunks)}")
        where = (f"Voici le texte complet du cours ({len(pages)} pages)." if first == 1 and last == len(pages)
                 else f"Voici le texte des pages {first} à {last} d'un cours de {len(pages)} pages.")
        user = (f"Matière : {subject}.\n{where}\n\n{text}\n\n"
                "Crée toutes les cartes utiles pour maîtriser ce contenu à l'examen.")
        parsed = None
        for _ in range(2):  # une seconde chance si la réponse n'est pas du JSON valide
            parsed = parse_cards(chat(SYSTEM + RULES, user), first, last)
            if parsed is not None:
                break
        if parsed is None:
            continue
        title = title or parsed[0]
        source = _words(text)
        for c in parsed[1]:
            key = " ".join(c.question.lower().split())
            if key in seen or len(c.question) < 8 or not grounded(c, source):
                continue
            seen.add(key)
            cards.append(c)
    if not cards:
        raise ReviseError(f"{label} n'a produit aucune carte exploitable pour {pdf.name}.")
    return title or title_from_filename(pdf.stem), cards
