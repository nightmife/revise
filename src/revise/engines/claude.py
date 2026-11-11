"""Moteur Claude : le PDF est envoyé tel quel (texte, schémas, formules, code),
Claude renvoie les cartes au format JSON imposé par un schéma (sortie structurée)."""

from __future__ import annotations

import base64
import os
import json
import math
from dataclasses import dataclass
from pathlib import Path

import anthropic
from pypdf import PdfReader

from revise.engines import Progress
from revise.models import CardDraft, ReviseError
from revise.pdf import PdfChunk, extract_pages, open_pdf

MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT = 4.0, 20.0           # $ par million de jetons (Claude Opus 5.5)
PAGES_PER_CHUNK = 40                      # au-delà, la couverture du cours baisse
MAX_REQUEST_BYTES = 30 * 1024 * 1024      # limite API : 32 Mo par requête (base64 compris)
OUTPUT_TOKENS_PER_PAGE = 260              # estimation (cartes + réflexion) pour le devis
MAX_TOKENS = 64000

SYSTEM = """Tu es un enseignant qui prépare des cartes de révision (répétition espacée) \
pour un étudiant en licence d'informatique, à partir des diapositives d'un cours magistral.

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


@dataclass
class Estimate:
    pages: int
    chunks: int
    input_tokens: int
    output_tokens: int

    @property
    def dollars(self) -> float:
        return (self.input_tokens * PRICE_IN + self.output_tokens * PRICE_OUT) / 1e6


def _document_block(data: bytes) -> dict:
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf",
                   "data": base64.standard_b64encode(data).decode("ascii")},
    }


def _user_content(chunk: PdfChunk, subject: str, total_pages: int) -> list[dict]:
    if chunk.first_page == 1 and chunk.last_page == total_pages:
        where = f"Le PDF complet ({total_pages} pages) est joint."
    else:
        where = (f"Le PDF joint contient les pages {chunk.first_page} à {chunk.last_page} "
                 f"d'un cours de {total_pages} pages : la page 1 du document joint est la page "
                 f"{chunk.first_page} du cours. Donne les numéros de page du cours.")
    text = (f"Matière : {subject}.\n{where}\n"
            "Crée toutes les cartes utiles pour maîtriser ce contenu à l'examen.")
    return [_document_block(chunk.data), {"type": "text", "text": text}]


def _chunks(reader: PdfReader, size: int) -> list[PdfChunk]:
    n = len(reader.pages)
    out: list[PdfChunk] = []
    for start in range(0, n, size):
        out.extend(_chunks_range(reader, start, min(n, start + size)))
    return out


def _chunks_range(reader: PdfReader, start: int, end: int) -> list[PdfChunk]:
    """Coupe en deux une plage trop lourde, récursivement."""
    data = extract_pages(reader, start, end)
    if len(data) * 4 / 3 <= MAX_REQUEST_BYTES or end - start == 1:
        if len(data) * 4 / 3 > MAX_REQUEST_BYTES:
            raise ReviseError(f"La page {start + 1} pèse plus de 30 Mo : impossible de l'envoyer.")
        return [PdfChunk(start + 1, end, data)]
    mid = (start + end) // 2
    return _chunks_range(reader, start, mid) + _chunks_range(reader, mid, end)


def _explain_api_error(e: Exception) -> ReviseError:
    if isinstance(e, anthropic.AuthenticationError):
        return ReviseError("Clé API refusée. Vérifie ANTHROPIC_API_KEY (console.anthropic.com → API Keys).")
    if isinstance(e, anthropic.PermissionDeniedError):
        return ReviseError("Ta clé API n'a pas accès à ce modèle.")
    if isinstance(e, anthropic.RateLimitError):
        return ReviseError("Limite de débit de l'API atteinte : réessaie dans une minute.")
    if isinstance(e, anthropic.BadRequestError):
        msg = getattr(e, "message", str(e))
        if "credit" in msg.lower() or "billing" in msg.lower():
            return ReviseError("Crédit API insuffisant : ajoute du crédit sur console.anthropic.com (Billing).")
        return ReviseError(f"Requête refusée par l'API : {msg}")
    if isinstance(e, anthropic.APIStatusError):
        return ReviseError(f"Erreur du serveur Anthropic ({e.status_code}) : réessaie plus tard.")
    if isinstance(e, anthropic.APIConnectionError):
        return ReviseError("Impossible de joindre l'API Anthropic (connexion internet ?).")
    return ReviseError(str(e))


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key and (key.endswith("...") or len(key) < 40):
        raise ReviseError("ANTHROPIC_API_KEY contient un exemple, pas une vraie clé. Crée une clé sur "
                          "console.anthropic.com → API Keys, puis : export ANTHROPIC_API_KEY='la clé copiée'")
    try:
        # Identifiants : ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN ou profil `ant auth login`.
        return anthropic.Anthropic(max_retries=3, timeout=900.0)
    except anthropic.AnthropicError as e:
        raise ReviseError("Pas d'identifiants pour l'API Claude. Crée une clé sur console.anthropic.com "
                          "puis : export ANTHROPIC_API_KEY=sk-ant-...") from e


class ClaudeEngine:
    name = "claude"

    def __init__(self, client: anthropic.Anthropic | None = None, pages_per_chunk: int = PAGES_PER_CHUNK):
        self._client = client
        self.pages_per_chunk = pages_per_chunk

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = make_client()
        return self._client

    # ----------------------------------------------------------------- devis
    def estimate(self, pdf: Path, subject: str) -> Estimate:
        reader = open_pdf(pdf)
        total = len(reader.pages)
        chunks = _chunks(reader, self.pages_per_chunk)
        tokens = 0
        try:
            for c in chunks:
                r = self.client.messages.count_tokens(
                    model=MODEL, system=SYSTEM,
                    messages=[{"role": "user", "content": _user_content(c, subject, total)}],
                    output_config={"format": {"type": "json_schema", "schema": CARD_SCHEMA}},
                )
                tokens += r.input_tokens
        except anthropic.AnthropicError as e:
            raise _explain_api_error(e) from e
        return Estimate(total, len(chunks), tokens, total * OUTPUT_TOKENS_PER_PAGE)

    # ------------------------------------------------------------ génération
    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        reader = open_pdf(pdf)
        total = len(reader.pages)
        if total == 0:
            raise ReviseError("Le PDF ne contient aucune page.")
        chunks = _chunks(reader, self.pages_per_chunk)
        title = ""
        cards: list[CardDraft] = []
        for i, chunk in enumerate(chunks, start=1):
            label = f"pages {chunk.first_page}-{chunk.last_page}"
            progress(f"Claude lit les {label} ({i}/{len(chunks)})…")
            t, cs = self._generate_chunk(reader, chunk, subject, total, progress)
            title = title or t
            cards.extend(cs)
        # Dédoublonnage (les morceaux se recoupent parfois sur une notion)
        seen: set[str] = set()
        unique = []
        for c in cards:
            key = " ".join(c.question.lower().split())
            if key not in seen:
                seen.add(key)
                unique.append(c)
        progress(f"{len(unique)} cartes générées")
        return title or pdf.stem, unique

    def _generate_chunk(self, reader: PdfReader, chunk: PdfChunk, subject: str, total: int,
                        progress: Progress) -> tuple[str, list[CardDraft]]:
        try:
            with self.client.beta.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                messages=[{"role": "user", "content": _user_content(chunk, subject, total)}],
                output_config={"effort": "medium",
                               "format": {"type": "json_schema", "schema": CARD_SCHEMA}},
                # Si une politique de sécurité refuse la requête, l'API bascule d'elle-même
                # sur un modèle de repli plutôt que d'échouer.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                message = stream.get_final_message()
        except anthropic.AnthropicError as e:
            raise _explain_api_error(e) from e

        if message.stop_reason == "refusal":
            raise ReviseError(f"Claude a refusé de traiter les pages {chunk.first_page}-{chunk.last_page}.")
        if message.stop_reason == "max_tokens":
            # Trop de contenu pour une réponse : on coupe le morceau en deux.
            n = chunk.last_page - chunk.first_page + 1
            if n <= 2:
                raise ReviseError(f"Réponse tronquée sur les pages {chunk.first_page}-{chunk.last_page}.")
            progress(f"Morceau trop dense, découpage des pages {chunk.first_page}-{chunk.last_page}…")
            mid = chunk.first_page - 1 + n // 2
            a = PdfChunk(chunk.first_page, mid, extract_pages(reader, chunk.first_page - 1, mid))
            b = PdfChunk(mid + 1, chunk.last_page, extract_pages(reader, mid, chunk.last_page))
            t1, c1 = self._generate_chunk(reader, a, subject, total, progress)
            _, c2 = self._generate_chunk(reader, b, subject, total, progress)
            return t1, c1 + c2
        return parse_cards(message, chunk)


def parse_cards(message, chunk: PdfChunk) -> tuple[str, list[CardDraft]]:
    text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ReviseError(f"Réponse illisible de l'API sur les pages {chunk.first_page}-{chunk.last_page}.") from e
    cards = []
    for raw in data.get("cards", []):
        page = raw.get("page")
        # Page hors du morceau : probablement relative au document joint, on la recale.
        if isinstance(page, int) and not chunk.first_page <= page <= chunk.last_page:
            rel = chunk.first_page - 1 + page
            page = rel if chunk.first_page <= rel <= chunk.last_page else None
        c = CardDraft(raw.get("kind", "qa"), raw.get("question", ""), raw.get("answer", ""), page,
                      raw.get("section", "")).normalized()
        if c:
            cards.append(c)
    return str(data.get("title", "")).strip(), cards


def format_estimate(e: Estimate) -> str:
    cents = math.ceil(e.dollars * 100)
    return (f"{e.pages} pages en {e.chunks} envoi(s) · ~{e.input_tokens:,} jetons lus, "
            f"~{e.output_tokens:,} écrits · coût estimé ≈ {cents} centimes de dollar").replace(",", " ")
