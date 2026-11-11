"""Moteur sans IA : repère dans le texte des diapositives les définitions, les énoncés
(théorème, propriété…) et les listes à puces, et en fait des cartes.

La qualité dépend de la mise en page du PDF ; les cartes sont à relire (`revise editer`)."""

from __future__ import annotations

import re
from pathlib import Path

from revise.engines import Progress
from revise.models import CardDraft
from revise.pdf import page_texts

BULLET = re.compile(r"^\s*(?:[•▪◦‣∙●○■□➢➤►▶✓✔\-–—*]|\d{1,2}[.)]|[a-z][.)])\s+(.+)$")
# « Terme : définition » (terme court, commençant par une lettre)
COLON_DEF = re.compile(r"^(?P<term>[A-Za-zÀ-ÖØ-öø-ÿ][\w'’ ()/-]{1,50}?)\s*(?::|=|—|–)\s+(?P<def>.{20,})$")
# « Un/Une/Le/La X est un/une … »
IS_DEF = re.compile(
    r"^(?:(?:Une|Un|Les|Le|La)\s+|L['’]\s*)?(?P<term>[A-Za-zÀ-ÖØ-öø-ÿ][\w'’ -]{1,50}?)\s+"
    r"(?:est|sont|désigne|désignent|correspond à|représente)\s+"
    r"(?P<def>(?:un|une|le|la|les|l['’]|des|ce|celle|celui|l'ensemble|toute?)\b.{15,})$",
    re.IGNORECASE)
CALLED = re.compile(r"^On (?:appelle|nomme|dit qu['’]\s*(?:un|une)?)\s+(?P<term>.{2,60}?)\s+(?P<def>(?:un|une|le|la|les|l['’]|si|tout|toute|quand|lorsque)\b.{10,})$",
                    re.IGNORECASE)
STATEMENT = re.compile(r"^(?P<kw>Définition|Théorème|Propriété|Proposition|Lemme|Corollaire|Principe|Loi|Règle|Algorithme)"
                       r"\b\s*(?P<num>[\d.]*)\s*(?:[:.—–-]\s*|\((?P<name>[^)]{2,60})\)\s*[:.]?\s*)?(?P<rest>.*)$",
                       re.IGNORECASE)
SKIP_TITLES = re.compile(r"^(plan|sommaire|table des mati|bibliograph|références|questions\s*\??|merci|introduction$|conclusion$|contact|à suivre)",
                         re.IGNORECASE)
NOISE = re.compile(r"^(?:\d{1,4}|\d{1,4}\s*/\s*\d{1,4}|page \d+.*|©.*|https?://\S+)$", re.IGNORECASE)

MAX_ANSWER = 600

# Étiquettes de spécification : la question reprend la ligne de contexte (ex. « Procédure dépiler () »).
SPEC_LABELS = {"précondition", "préconditions", "postcondition", "postconditions", "résultat", "résultats",
               "paramètre", "paramètres", "paramètre en mode donnée", "paramètre en mode donnée-résultat",
               "paramètre en mode résultat", "retour", "valeur de retour"}
# Étiquettes qui se rapportent au titre de la diapositive.
TITLE_LABELS = {"rôle", "but", "objectif", "principe", "méthode", "idée", "solution", "complexité",
                "avantage", "avantages", "inconvénient", "inconvénients", "intérêt", "définition", "algorithme"}
# Débuts de « termes » qui n'en sont pas.
NOT_TERMS = re.compile(r"^(?:par|pour|avec|en|dans|sur|si|sinon|ex|exemples?|remarques?|attention|note|nb|n\.b|"
                       r"rappels?|importer|exporter|variables?|variables locales|début|fin|il|elle|on|ce|cela|ceci|"
                       r"c['’]est|il y a|ici|alors|donc|mais|or|et|ou)\b", re.IGNORECASE)
CODE_LIKE = re.compile(r"[;{}←]|\w\(\)|\b(?:int|void|char|return|cout|cin|new|delete)\b")


def clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or NOISE.match(line):
            continue
        lines.append(line)
    return lines


def merge_wrapped(lines: list[str]) -> list[str]:
    """Recolle les lignes coupées par la mise en page (ligne suivante en minuscule, pas de puce)."""
    out: list[str] = []
    for line in lines:
        if (out and not BULLET.match(line) and line[:1].islower()
                and not out[-1].endswith((".", ":", "?", "!"))):
            out[-1] += " " + line
        else:
            out.append(line)
    return out


def guess_title(lines: list[str]) -> str:
    for line in lines[:3]:
        if 3 <= len(line) <= 80 and not BULLET.match(line) and not line.endswith("."):
            return line
    return ""


def shorten(s: str, n: int = MAX_ANSWER) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + " …"


def definition_card(content: str, title: str, context: str, page: int) -> list[CardDraft]:
    """Cartes pour une ligne de définition, ou [] si la ligne n'en est pas une."""
    if content.endswith("?"):
        return []  # question posée sur la diapositive, pas une définition
    for rx in (CALLED, IS_DEF, COLON_DEF):
        m = rx.match(content)
        if not m:
            continue
        term = m.group("term").strip(" :-")
        definition = m.group("def").strip()
        if term.count("(") != term.count(")"):
            return []  # coupé au milieu d'une parenthèse : ce n'est pas un terme
        low = term.lower()
        if low.replace("-", "") in {x.replace("-", "") for x in SPEC_LABELS}:
            low = low.replace("-", "")
        if rx is COLON_DEF:
            if low in SPEC_LABELS or low.replace("-", "") in SPEC_LABELS:
                ctx = context if context and context != title else title
                if not ctx:
                    return []
                label = low.rstrip("s") if low.endswith(("conditions", "résultats")) else low
                return [CardDraft("qa", f"{ctx} — {label} ?", shorten(definition), page, title)]
            if low in TITLE_LABELS:
                if not title:
                    return []
                return [CardDraft("qa", f"{title} — {low} ?", shorten(definition), page, title)]
            if (NOT_TERMS.match(term) or len(term) <= 2 or CODE_LIKE.search(term) or CODE_LIKE.search(definition)
                    or any(ch.isdigit() for ch in term)):
                return []
        if len(term.split()) > 6 or NOT_TERMS.match(term):
            return []
        cards = [CardDraft("qa", f"Qu'est-ce que « {term} » ?", shorten(definition), page, title)]
        if rx is not COLON_DEF:
            # Texte à trous uniquement sur une vraie phrase de définition.
            hidden = re.sub(re.escape(term), "[…]", content, count=1, flags=re.IGNORECASE)
            if hidden != content:
                cards.append(CardDraft("cloze", hidden, term, page, title))
        return cards
    return []


def title_from_filename(stem: str) -> str:
    t = re.sub(r"^\s*\[[^\]]*\]\s*", "", stem)        # préfixe « [LIFAPSD] »
    t = re.sub(r"\s*\(\d+\)\s*$", "", t)                 # suffixe « (1) » des téléchargements
    return t.replace("_", " ").strip() or stem


def cards_from_page(text: str, page: int) -> list[CardDraft]:
    lines = merge_wrapped(clean_lines(text))
    if not lines:
        return []
    title = guess_title(lines)
    if title and SKIP_TITLES.match(title):
        return []
    body = lines[1:] if title and lines[0] == title else lines
    cards: list[CardDraft] = []
    context = title

    i = 0
    while i < len(body):
        line = body[i]
        bullet = BULLET.match(line)
        content = bullet.group(1) if bullet else line

        # Énoncé : « Théorème (Pythagore) : … » + lignes suivantes jusqu'à une ligne vide/puce/nouvel énoncé
        if m := STATEMENT.match(content):
            kw = m.group("kw").capitalize()
            label = m.group("name") or title or kw
            ask_title = kw.lower() in TITLE_LABELS and label != kw
            parts = [m.group("rest")] if m.group("rest") else []
            j = i + 1
            while j < len(body) and len(" ".join(parts)) < MAX_ANSWER and not STATEMENT.match(body[j]):
                parts.append(body[j])
                j += 1
            statement = " ".join(p for p in parts if p).strip()
            if len(statement) >= 15:
                if ask_title:
                    q = f"{label} — {kw.lower()} ?"
                else:
                    q = f"Énonce : {kw.lower()} « {label} »" if label != kw else f"Énonce : {kw.lower()} (p. {page})"
                cards.append(CardDraft("qa", q, shorten(statement), page, title))
            i = j
            continue

        if card := definition_card(content, title, context, page):
            cards.extend(card)
        elif not COLON_DEF.match(content) and 3 <= len(content) <= 90 and not content.endswith((".", "?")):
            context = content  # ligne d'intitulé (ex. « Procédure empiler (e: ElementP) »)
        i += 1

    # Liste à puces significative : « points clés » de la diapositive.
    bullets = [m.group(1) for line in body if (m := BULLET.match(line))]
    if title and 2 <= len(bullets) <= 8 and all(len(b) <= 160 for b in bullets):
        answer = "\n".join(f"- {b}" for b in bullets)
        cards.append(CardDraft("qa", f"Quels sont les points clés de « {title} » ?", shorten(answer, 900), page, title))
    return cards


class SimpleEngine:
    name = "simple"

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        progress("Lecture du texte du PDF…")
        texts = page_texts(pdf)
        if not any(t.strip() for t in texts):
            from revise.models import ReviseError
            raise ReviseError("Aucun texte dans ce PDF (diapositives scannées ?). "
                              "Le moteur sans IA ne lit que le texte : essaie --moteur claude.")
        cards: list[CardDraft] = []
        seen: set[str] = set()
        for n, text in enumerate(texts, start=1):
            for c in cards_from_page(text, n):
                key = c.question.lower()
                if key in seen:
                    continue
                seen.add(key)
                if norm := c.normalized():
                    cards.append(norm)
        title = title_from_filename(pdf.stem)
        progress(f"{len(cards)} cartes trouvées sur {len(texts)} pages")
        return title, cards
