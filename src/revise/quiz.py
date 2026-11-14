"""QCM fabriqués à partir des cartes.

Les mauvaises réponses sont, dans l'ordre de préférence :
1. celles écrites par l'IA pour cette question (`Card.distractors`) : elles répondent à la
   même question, donc il faut connaître le cours pour trancher ;
2. à défaut, les réponses d'autres cartes, choisies pour ressembler le plus possible à une
   réponse à cette question (même cours, même partie, question et réponse de même forme)."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from revise.db import Card

MAX_CHOICE_CHARS = 320
CHOICES = 4
SCORE_MARGIN = 1.5  # écart de ressemblance toléré entre les mauvaises réponses tirées au sort


@dataclass
class QuizQuestion:
    card: Card
    choices: list[str]
    correct: int  # indice de la bonne réponse dans `choices`


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def choice_text(answer: str) -> str:
    s = answer.strip()
    if len(s) <= MAX_CHOICE_CHARS:
        return s
    return s[:MAX_CHOICE_CHARS].rsplit(" ", 1)[0] + " …"


def _words(s: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-zà-ÿ0-9]{4,}", s.lower()))


def _opening(question: str) -> str:
    """Tournure de la question : « quel », « pourquoi », « comment »…"""
    m = re.match(r"[^a-zà-ÿ]*([a-zà-ÿ]+)", question.lower())
    word = m.group(1) if m else ""
    return "quel" if word.startswith(("quel", "lequel", "laquelle", "lesquel")) else word


def _form(answer: str) -> str:
    """Allure de la réponse, pour ne pas proposer « Parce que… » à une question « Combien… »."""
    s = answer.lstrip().lower()
    if s.startswith("```"):
        return "code"
    if re.match(r"([-*•]|\d+[.)])\s", s):
        return "liste"
    if re.match(r"(oui|non|vrai|faux)\b", s):
        return "oui-non"
    if re.match(r"(parce|car|pour|afin|grâce)\b", s):
        return "raison"
    if re.match(r"[\d(`$]", s):
        return "valeur"
    return "mot" if len(s.split()) <= 3 else "phrase"


@dataclass(frozen=True)
class _Features:
    words: frozenset[str]
    opening: str
    form: str


def _features(card: Card) -> _Features:
    return _Features(_words(card.question), _opening(card.question), _form(card.answer))


def _closeness(card: Card, fc: _Features, other: Card, fo: _Features) -> float:
    """Plus le score est haut, plus la réponse de `other` passe pour une réponse à `card`."""
    score = 0.0
    if other.deck_id == card.deck_id:
        score += 3
    if other.kind == card.kind:
        score += 2
    if other.section and other.section == card.section:
        score += 1.5
    if fo.form == fc.form:
        score += 2.5
    if fo.opening and fo.opening == fc.opening:
        score += 1.5
    union = len(fc.words | fo.words)
    if union:
        score += 3 * len(fc.words & fo.words) / union
    a, b = len(card.answer), len(other.answer)
    score += 2 * min(a, b) / max(a, b, 1)
    return score


def distractors(card: Card, pool: list[Card], rng: random.Random, n: int = CHOICES - 1,
                features: dict[int, _Features] | None = None) -> list[str]:
    """Jusqu'à `n` mauvaises réponses, toutes différentes entre elles et de la bonne."""
    seen = {_norm(card.answer), _norm(choice_text(card.answer))}
    out: list[str] = []
    own = list(card.distractors)
    rng.shuffle(own)
    for wrong in own:
        text = choice_text(wrong)
        key = _norm(text)
        if key and key not in seen and len(out) < n:
            seen.add(key)
            out.append(text)
    if len(out) >= n:
        return out

    feats = features if features is not None else {}
    def feat(c: Card) -> _Features:
        if c.id not in feats:
            feats[c.id] = _features(c)
        return feats[c.id]

    fc = feat(card)
    ranked = sorted(((_closeness(card, fc, o, feat(o)), o.id, o) for o in pool if o.id != card.id), reverse=True)
    missing = n - len(out)
    candidates: list[str] = []
    best = ranked[0][0] if ranked else 0.0
    for score, _, other in ranked:
        # Au-delà du nécessaire, on ne garde que des candidats presque aussi bons que le meilleur.
        if len(candidates) >= 2 * missing or (len(candidates) >= missing and score < best - SCORE_MARGIN):
            break
        text = choice_text(other.answer)
        key = _norm(text)
        if not key or key in seen or _norm(other.answer) in seen:
            continue
        seen.add(key)
        candidates.append(text)
    # Tirage parmi les meilleurs candidats, pour que le QCM change d'une fois à l'autre.
    rng.shuffle(candidates)
    return out + candidates[:missing]


def usable_count(cards: list[Card]) -> int:
    """Nombre de cartes utilisables en QCM : toutes dès qu'il existe deux réponses différentes,
    sinon seulement celles qui ont leurs propres mauvaises réponses."""
    if len({_norm(c.answer) for c in cards}) >= 2:
        return len(cards)
    return sum(1 for c in cards if c.distractors)


def prepared_count(cards: list[Card]) -> int:
    """Nombre de cartes dont les mauvaises réponses ont été écrites par l'IA."""
    return sum(1 for c in cards if c.distractors)


def build_quiz(cards: list[Card], count: int, rng: random.Random | None = None,
               pool: list[Card] | None = None) -> list[QuizQuestion]:
    """Tire `count` questions au hasard parmi `cards`. Les mauvaises réponses qui ne viennent pas
    de l'IA sont prises dans `pool` (par défaut `cards`). Une carte sans aucune mauvaise réponse
    possible est écartée."""
    rng = rng or random.Random()
    pool = cards if pool is None else pool
    order = list(cards)
    rng.shuffle(order)
    features: dict[int, _Features] = {}
    questions: list[QuizQuestion] = []
    for card in order:
        if len(questions) >= count:
            break
        wrong = distractors(card, pool, rng, features=features)
        if not wrong:
            continue
        right = choice_text(card.answer)
        choices = wrong + [right]
        rng.shuffle(choices)
        questions.append(QuizQuestion(card, choices, choices.index(right)))
    return questions
