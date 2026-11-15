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
from revise.pdf import page_texts, pages_pdf, visual_pages

CHUNK_CHARS = 7000
CHUNK_PAGES = 8
VISUAL_CHUNK_PAGES = 6               # pages envoyées en image : morceaux plus petits
MAX_PDF_BYTES = 20 * 1024 * 1024     # au-delà, le morceau est envoyé page par page
NO_TEXT = "(aucun texte lisible sur cette page : regarde-la dans le PDF joint)"

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

VISUAL_RULES = """
- Un PDF est joint : il contient les pages de ce morceau du cours, telles que l'étudiant les voit. Sers-toi \
de ce que tu y vois (pages scannées, schémas, figures, tableaux, formules) en plus du texte extrait.
- Une question ne doit jamais dépendre d'une image que l'étudiant n'aura pas sous les yeux : décris en mots \
ce qu'il faut savoir du schéma (« Dans une liste chaînée, vers quoi pointe le dernier maillon ? »).
- La première page du PDF joint porte le numéro indiqué dans le message ; "page" est toujours le numéro \
dans le cours complet.
"""

Chat = Callable[[str, str], str]  # (consignes système, message) -> réponse brute du modèle
ChatPdf = Callable[[str, str, bytes], str]  # idem, avec les pages du morceau en PDF


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-zà-ÿ0-9]{4,}", s.lower()))


def grounded(card: CardDraft, source_words: set[str]) -> bool:
    """Vrai si la carte reprend assez de vocabulaire du texte source.

    Sert à écarter les cartes inventées de toutes pièces par le modèle."""
    words = _words(card.question + " " + card.answer)
    if len(words) < 3:
        return True
    return len(words & source_words) / len(words) >= 0.4


def text_chunks(pages: list[str], visual: frozenset[int] | set[int] = frozenset()) -> list[tuple[int, int, str]]:
    """Regroupe les pages en morceaux (première page, dernière page, texte).

    `visual` : pages à regarder (scannées, schémas). Elles sont gardées même sans texte, et un morceau
    ne mélange jamais pages à regarder et pages de texte seul."""
    chunks: list[tuple[int, int, str]] = []
    first = 0
    parts: list[str] = []
    size = 0
    seeing = False
    previous = 0
    for n, text in enumerate(pages, start=1):
        text = text.strip()
        if not text and n not in visual:
            continue
        text = text[:CHUNK_CHARS] or NO_TEXT
        limit = VISUAL_CHUNK_PAGES if seeing else CHUNK_PAGES
        if parts and (size + len(text) > CHUNK_CHARS or n - first >= limit or (n in visual) != seeing):
            # Un morceau « à regarder » s'arrête à sa dernière page utile : son PDF ne contient qu'elles.
            chunks.append((first, previous if seeing else n - 1, "\n\n".join(parts)))
            parts, size = [], 0
        if not parts:
            seeing = n in visual
        previous = n
        if not parts:
            first = n
        parts.append(f"=== Page {n} ===\n{text}")
        size += len(text)
    if parts:
        chunks.append((first, previous if seeing else len(pages), "\n\n".join(parts)))
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


def _split_for_size(pdf: Path, chunks: list[tuple[int, int, str]], pages: list[str], visual: set[int]
                    ) -> list[tuple[int, int, str, bytes | None]]:
    """Ajoute à chaque morceau « à regarder » le PDF de ses pages ; un morceau trop lourd est envoyé page par
    page, et une page trop lourde à elle seule est traitée avec son texte uniquement."""
    out: list[tuple[int, int, str, bytes | None]] = []
    for first, last, text in chunks:
        if first not in visual:
            out.append((first, last, text, None))
            continue
        data = pages_pdf(pdf, first, last)
        if len(data) <= MAX_PDF_BYTES:
            out.append((first, last, text, data))
            continue
        for n in range(first, last + 1):
            one = pages_pdf(pdf, n, n)
            page_text = pages[n - 1].strip()[:CHUNK_CHARS]
            if len(one) <= MAX_PDF_BYTES:
                out.append((n, n, f"=== Page {n} ===\n{page_text or NO_TEXT}", one))
            elif page_text:
                out.append((n, n, f"=== Page {n} ===\n{page_text}", None))
    return out


def generate_cards(pdf: Path, subject: str, progress: Progress, chat: Chat, label: str,
                   chat_pdf: ChatPdf | None = None) -> tuple[str, list[CardDraft]]:
    """Génère les cartes d'un cours morceau par morceau avec la fonction `chat` d'un moteur.

    `chat_pdf` (moteurs qui savent regarder un PDF) : les pages scannées et celles qui portent un schéma
    lui sont envoyées en PDF, en plus de leur texte."""
    pages = page_texts(pdf)
    visual = visual_pages(pdf, pages) if chat_pdf is not None else set()
    chunks = _split_for_size(pdf, text_chunks(pages, visual), pages, visual)
    if not chunks:
        raise ReviseError(f"{pdf.name} ne contient pas de texte (pages scannées ?). Cette IA ne lit que le texte ; "
                          "« Mon abonnement Claude » lit aussi les pages scannées et les schémas.")
    title = ""
    cards: list[CardDraft] = []
    seen: set[str] = set()
    for i, (first, last, text, document) in enumerate(chunks, start=1):
        progress(f"{label} : pages {first}-{last} — morceau {i}/{len(chunks)}"
                 + (" (avec les images)" if document else ""))
        where = (f"Voici le texte complet du cours ({len(pages)} pages)." if first == 1 and last == len(pages)
                 else f"Voici le texte des pages {first} à {last} d'un cours de {len(pages)} pages.")
        if document:
            where += (f"\nLe PDF joint contient ces mêmes pages : sa première page est la page {first} du cours"
                      + (f", sa dernière la page {last}." if last > first else "."))
        user = (f"Matière : {subject}.\n{where}\n\n{text}\n\n"
                "Crée toutes les cartes utiles pour maîtriser ce contenu à l'examen.")
        parsed = None
        for _ in range(2):  # une seconde chance si la réponse n'est pas du JSON valide
            raw = (chat_pdf(SYSTEM + RULES + VISUAL_RULES, user, document) if document and chat_pdf
                   else chat(SYSTEM + RULES, user))
            parsed = parse_cards(raw, first, last)
            if parsed is not None:
                break
        if parsed is None:
            continue
        title = title or parsed[0]
        source = _words(text)
        for c in parsed[1]:
            key = " ".join(c.question.lower().split())
            # Une carte tirée d'une image ne reprend pas forcément les mots du texte extrait.
            if key in seen or len(c.question) < 8 or not (document or grounded(c, source)):
                continue
            seen.add(key)
            cards.append(c)
    if not cards:
        raise ReviseError(f"{label} n'a produit aucune carte exploitable pour {pdf.name}.")
    return title or title_from_filename(pdf.stem), cards
