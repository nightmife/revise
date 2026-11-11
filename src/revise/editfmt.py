"""Édition des cartes d'un paquet en Markdown.

Format :
    ## carte 12 · qa · p.4
    Q: question (plusieurs lignes possibles)
    R: réponse (plusieurs lignes possibles)

Supprimer un bloc supprime la carte ; un bloc « ## nouvelle · qa » en crée une."""

from __future__ import annotations

import re
from dataclasses import dataclass

from revise.db import Card, Database
from revise.models import KINDS, CardDraft, ReviseError

HEADER = re.compile(r"^## (?:carte (?P<id>\d+)|(?P<new>nouvelle))\s*(?:·\s*(?P<kind>\w+))?\s*(?:·\s*p\.?\s*(?P<page>\d+))?\s*$")


def render(deck_title: str, cards: list[Card]) -> str:
    lines = [
        f"<!-- Paquet : {deck_title}",
        "     Modifie les questions (Q:) et réponses (R:), supprime un bloc pour supprimer la carte,",
        "     ajoute un bloc « ## nouvelle · qa · p.3 » pour en créer une. Types : qa, cloze, code. -->",
        "",
    ]
    for c in cards:
        page = f" · p.{c.page}" if c.page else ""
        lines += [f"## carte {c.id} · {c.kind}{page}", f"Q: {c.question}", f"R: {c.answer}", ""]
    lines += ["## nouvelle · qa", "Q: ", "R: ", ""]
    return "\n".join(lines)


@dataclass
class Block:
    card_id: int | None
    kind: str
    page: int | None
    question: str
    answer: str


def parse(text: str) -> list[Block]:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    blocks: list[Block] = []
    cur: dict | None = None
    field_name: str | None = None
    buf: dict[str, list[str]] = {}

    def flush() -> None:
        if cur is None:
            return
        q = "\n".join(buf.get("Q", [])).strip()
        a = "\n".join(buf.get("R", [])).strip()
        if cur["id"] is None and not q and not a:
            return  # bloc « nouvelle » laissé vide
        if not q or not a:
            where = f"carte {cur['id']}" if cur["id"] else "nouvelle carte"
            raise ReviseError(f"{where} : il faut une question (Q:) et une réponse (R:)")
        blocks.append(Block(cur["id"], cur["kind"], cur["page"], q, a))

    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            flush()
            kind = (m.group("kind") or "qa").lower()
            if kind not in KINDS:
                raise ReviseError(f"type inconnu « {kind} » (attendu : {', '.join(KINDS)})")
            cur = {"id": int(m.group("id")) if m.group("id") else None, "kind": kind,
                   "page": int(m.group("page")) if m.group("page") else None}
            buf, field_name = {}, None
            continue
        if line.startswith("## "):
            raise ReviseError(f"en-tête illisible : {line}")
        if cur is None:
            if line.strip():
                raise ReviseError(f"texte hors d'une carte : {line[:60]}")
            continue
        if line.startswith(("Q:", "R:")):
            field_name = line[0]
            buf[field_name] = [line[2:].lstrip()]
        elif field_name:
            buf[field_name].append(line)
        elif line.strip():
            raise ReviseError(f"ligne avant Q: dans la carte {cur['id'] or 'nouvelle'} : {line[:60]}")
    flush()
    return blocks


@dataclass
class Changes:
    updated: int = 0
    created: int = 0
    deleted: list[int] | None = None


def diff(db: Database, deck_id: int, original: list[Card], blocks: list[Block]) -> Changes:
    """Calcule les changements sans les appliquer."""
    by_id = {c.id: c for c in original}
    seen = set()
    ch = Changes(deleted=[])
    for b in blocks:
        if b.card_id is None:
            ch.created += 1
            continue
        if b.card_id not in by_id:
            raise ReviseError(f"la carte {b.card_id} n'appartient pas à ce paquet")
        if b.card_id in seen:
            raise ReviseError(f"la carte {b.card_id} apparaît deux fois")
        seen.add(b.card_id)
        c = by_id[b.card_id]
        if (c.kind, c.question, c.answer, c.page) != (b.kind, b.question, b.answer, b.page):
            ch.updated += 1
    ch.deleted = [cid for cid in by_id if cid not in seen]
    return ch


def apply(db: Database, deck_id: int, original: list[Card], blocks: list[Block]) -> Changes:
    ch = diff(db, deck_id, original, blocks)
    by_id = {c.id: c for c in original}
    for b in blocks:
        if b.card_id is None:
            db.add_card(deck_id, CardDraft(b.kind, b.question, b.answer, b.page))
        else:
            c = by_id[b.card_id]
            if (c.kind, c.question, c.answer, c.page) != (b.kind, b.question, b.answer, b.page):
                db.update_card_content(b.card_id, b.kind, b.question, b.answer, b.page)
    for cid in ch.deleted or []:
        db.delete_card(cid)
    return ch
