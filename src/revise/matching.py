"""Rapprochement des cartes d'un cours refait avec les anciennes : une carte qui dit la même chose garde
la progression de l'ancienne (planning, historique)."""

from __future__ import annotations

import re
import unicodedata

from revise.db import Card
from revise.models import CardDraft

MIN_SCORE = 0.45  # en dessous, deux cartes ne parlent pas de la même chose


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def words(s: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", _plain(s)) if len(w) >= 3)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def similarity(q1: str, a1: str, q2: str, a2: str) -> float:
    """Ressemblance de deux cartes (0 à 1) : surtout la question, un peu la réponse."""
    return 0.6 * _jaccard(words(q1), words(q2)) + 0.4 * _jaccard(words(a1), words(a2))


def match_cards(old: list[Card], new: list[CardDraft]) -> dict[int, int]:
    """Indice de chaque nouvelle carte → identifiant de l'ancienne carte la plus proche (chacune au plus une
    fois, les paires les plus ressemblantes d'abord)."""
    old_w = [(c, words(c.question), words(c.answer)) for c in old]
    pairs = []
    for i, d in enumerate(new):
        qw, aw = words(d.question), words(d.answer)
        for c, oq, oa in old_w:
            score = 0.6 * _jaccard(qw, oq) + 0.4 * _jaccard(aw, oa)
            if score >= MIN_SCORE:
                pairs.append((score, i, c.id))
    out: dict[int, int] = {}
    taken: set[int] = set()
    for _, i, cid in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
        if i not in out and cid not in taken:
            out[i] = cid
            taken.add(cid)
    return out
