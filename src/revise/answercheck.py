"""Correction d'une réponse tapée, sans IA : compare les mots importants de la réponse attendue avec ceux
de la réponse écrite (fautes de frappe, accents et pluriels tolérés)."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

STOP = {"dans", "avec", "pour", "sans", "sous", "vers", "chez", "entre", "elle", "elles", "ils", "nous", "vous",
        "leur", "leurs", "cette", "celle", "celui", "ceux", "sont", "être", "etre", "avoir", "fait", "faire", "plus",
        "moins", "tres", "aussi", "comme", "donc", "mais", "dont", "quand", "lorsque", "alors", "ainsi", "tout",
        "tous", "toute", "toutes", "chaque", "autre", "autres", "meme", "même", "une", "des", "les", "est", "qui",
        "que", "quoi", "par", "sur", "aux", "the", "and", "with", "from", "that", "this", "elle", "notamment",
        "exemple", "ex", "etc", "c'est", "cest", "peut", "peuvent", "doit", "permet", "ensemble"}

GOOD, CLOSE, WRONG, EMPTY = "juste", "presque", "faux", "vide"
RATING = {GOOD: 3, CLOSE: 2, WRONG: 1}  # note proposée (Bien, Difficile, À revoir)


@dataclass
class Check:
    verdict: str              # juste, presque, faux, vide
    score: float              # 0 à 1
    found: list[str]          # mots importants retrouvés
    missing: list[str]        # mots importants absents

    @property
    def rating(self) -> int | None:
        return RATING.get(self.verdict)


def plain(s: str) -> str:
    """Minuscules, sans accents, sans Markdown ni ponctuation."""
    s = re.sub(r"[`*_#>\[\]{}|~]", " ", s)
    s = unicodedata.normalize("NFKD", s.lower().replace("œ", "oe").replace("æ", "ae"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[’']", " ", s)
    return " ".join(re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", s))


def _stem(w: str) -> str:
    for suffix in ("ements", "ement", "ations", "ation", "ions", "ion", "aux", "eux", "es", "s", "e", "x"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def key_words(s: str) -> list[str]:
    """Mots qui portent le sens (les nombres comptent toujours)."""
    out = []
    for w in plain(s).split():
        if (w[0].isdigit() or (len(w) >= 3 and w not in STOP)) and w not in out:
            out.append(w)
    return out


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if a[0].isdigit() or b[0].isdigit():
        return False  # un nombre doit être exact
    if _stem(a) == _stem(b):
        return True
    return len(a) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def check_answer(typed: str, expected: str, kind: str = "qa") -> Check:
    typed_plain, expected_plain = plain(typed), plain(expected)
    if not typed_plain:
        return Check(EMPTY, 0.0, [], key_words(expected))
    # Oui / non contraires : faux quoi qu'il y ait derrière.
    yes_no = re.match(r"(oui|non|vrai|faux)\b", expected_plain)
    if yes_no:
        opposite = {"oui": "non", "non": "oui", "vrai": "faux", "faux": "vrai"}[yes_no.group(1)]
        if re.match(rf"{opposite}\b", typed_plain):
            return Check(WRONG, 0.0, [], key_words(expected))
    whole = difflib.SequenceMatcher(None, typed_plain, expected_plain).ratio()
    keys = key_words(expected) or expected_plain.split()
    typed_words = typed_plain.split()
    found = [k for k in keys if any(_same_word(k, t) for t in typed_words)]
    missing = [k for k in keys if k not in found]
    coverage = len(found) / len(keys) if keys else 0.0
    short = len(expected_plain.split()) <= 4 or kind == "cloze"
    if short:
        # Texte à trous, réponse d'un mot ou d'un nom : il faut ce mot-là (faute de frappe tolérée).
        if whole >= 0.85 or (coverage == 1.0 and len(typed_words) <= len(expected_plain.split()) + 3):
            verdict = GOOD
        elif whole >= 0.6 or coverage >= 0.5:
            verdict = CLOSE
        else:
            verdict = WRONG
        score = max(whole, coverage)
    else:
        score = max(coverage, whole)
        verdict = GOOD if score >= 0.7 else CLOSE if score >= 0.4 else WRONG
    numbers = [k for k in keys if k[0].isdigit()]
    if verdict == GOOD and any(n in missing for n in numbers):
        verdict = CLOSE  # bonne idée, mauvais chiffre
    return Check(verdict, round(score, 2), found, missing)
