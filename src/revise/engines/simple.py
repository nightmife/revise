"""Moteur sans IA : repère dans le texte du cours ce qui s'apprend à coup sûr et en fait des cartes.

Ce qu'il cherche, du plus sûr au moins sûr :
- énoncés (« Théorème (Pythagore) : … », « Définition : … ») ;
- sigles (« SGBD (Système de Gestion de Bases de Données) »), dont les initiales sont vérifiées ;
- arrêts et décisions (« CE, 28 juin 1963, Narcy ») ;
- complexités (« la complexité du tri fusion est en O(n log n) ») ;
- définitions (« Une pile est une structure… », « On appelle X… », « L'impôt : somme due… »),
  rôles (« X permet de… », « X sert à… ») et « X consiste à… » ;
- énumérations (« Les trois critères sont : … », ou une ligne qui finit par « : » suivie d'une liste) ;
- dates : une phrase qui contient une année devient un texte à trous ;
- en dernier recours, la liste à puces d'une diapositive.

Les en-têtes, pieds de page et pages « à étapes » sont retirés avant (`pdf.clean_pages`). Chaque terme
défini passe un filtre strict (pas de verbe, pas de mot vide, pas de code) : mieux vaut moins de cartes que
des cartes fausses."""

from __future__ import annotations

import re
from pathlib import Path

from revise.engines import Progress, Step
from revise.models import CardDraft
from revise.pdf import clean_pages, page_texts

BULLET = re.compile(r"^\s*(?:[•▪◦‣∙●○■□➢➤►▶✓✔\-–—*]|\d{1,2}[.)]|[a-z][.)])\s+(.+)$")
L = r"A-Za-zÀ-ÖØ-öø-ÿ"
ART = r"(?P<art>Une|Un|Les|Le|La|L['’]\s*)"
# « Terme : définition » (terme court, commençant par une lettre). Le « = » n'en est pas un : c'est une formule.
COLON_DEF = re.compile(rf"^(?:{ART}\s*)?(?P<term>[{L}][\w'’ ()/-]{{1,60}}?)\s*(?::|—|–)\s+(?P<def>.{{15,}})$")
# « Un/Une/Le/La X est un/une … »
IS_DEF = re.compile(
    rf"^(?:{ART}\s*)?(?P<term>[{L}][\w'’ -]{{1,60}}?)\s+"
    r"(?:est|sont|désigne|désignent|correspond à|correspondent à|représente|représentent|se définit comme)\s+"
    r"(?P<def>(?:un|une|le|la|les|l['’]|des|ce|celle|celui|ceux|l'ensemble|toute?|tous)\b.{15,})$",
    re.IGNORECASE)
CALLED = re.compile(r"^On (?:appelle|nomme|dit qu['’]\s*(?:un|une)?)\s+(?P<term>.{2,60}?)\s+"
                    r"(?P<def>(?:un|une|le|la|les|l['’]|si|tout|toute|quand|lorsque)\b.{10,})$", re.IGNORECASE)
PURPOSE = re.compile(rf"^(?:{ART}\s*)?(?P<term>[{L}][\w'’ -]{{1,60}}?)\s+"
                     r"(?P<verb>permet(?:tent)? (?:de|d['’])|sert à|servent à|a pour (?:but|rôle|objectif) de|"
                     r"ont pour (?:but|rôle|objectif) de)\s*(?P<def>.{10,})$", re.IGNORECASE)
CONSISTS = re.compile(rf"^(?:{ART}\s*)?(?P<term>[{L}][\w'’ -]{{1,60}}?)\s+consistent? (?:à|en)\s+(?P<def>.{{10,}})$",
                      re.IGNORECASE)
STATEMENT = re.compile(r"^(?P<kw>Définition|Théorème|Propriété|Proposition|Lemme|Corollaire|Principe|Loi|Règle|Algorithme)"
                       r"\b\s*(?P<num>[\d.]*)\s*(?:[:.—–-]\s*|\((?P<name>[^)]{2,60})\)\s*[:.]?\s*)?(?P<rest>.*)$",
                       re.IGNORECASE)
SKIP_TITLES = re.compile(r"^(plan|sommaire|table des mati|bibliograph|références|questions\s*\??|merci|introduction$|"
                         r"conclusion$|contact|à suivre|pour en savoir plus|mcc\b|modalités|.*contrôle des connaissances|"
                         r"évaluation de l|calendrier|planning|organisation de l|déroulement de l)", re.IGNORECASE)
NOISE = re.compile(r"^(?:\d{1,4}|\d{1,4}\s*/\s*\d{1,4}|page \d+.*|©.*|https?://\S+)$", re.IGNORECASE)
NUMBERS = {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10}
NUM = r"(?P<n>deux|trois|quatre|cinq|six|sept|huit|neuf|dix|[2-9])"
ENUMERATION = re.compile(rf"^(?:Les|Il (?:existe|y a)|On (?:distingue|retrouve|compte))\s+{NUM}\s+"
                         rf"(?P<what>[{L}][^:]{{2,70}}?)\s*(?:sont|:)\s*:?\s*(?P<items>.*)$", re.IGNORECASE)
ENUM_TAIL = re.compile(rf"(?:^|[,;]\s*|\b)(?:on (?:retrouve|distingue|compte)\s+|il (?:existe|y a)\s+|les\s+)?{NUM}\s+"
                       rf"(?P<what>[{L}][^:;,]{{2,60}}?)\s*:?\s*$", re.IGNORECASE)
COURT = (r"(?P<court>CE|C\.E\.|TC|T\.C\.|CC|Cons\.?\s*const\.?|Conseil constitutionnel|Conseil d['’]État|CJUE|CJCE|"
         r"CEDH|Cass\.?(?:\s*(?:civ|crim|soc|com)\.?(?:\s*\d(?:re|e|ème))?|\s*ass\.?\s*plén\.?|\s*ch\.?\s*mixte)?|"
         r"CAA\s+[A-Z][\w-]+)")
ARRET = re.compile(COURT + r"\s*,\s*(?:(?:Ass|Sect|ass|sect)\.?\s*,\s*)?"
                   r"(?P<date>\d{1,2}(?:er)?\s+(?:janv(?:ier)?|févr(?:ier)?|mars|avr(?:il)?|mai|juin|juil(?:let)?|"
                   r"août|sept(?:embre)?|oct(?:obre)?|nov(?:embre)?|déc(?:embre)?)\.?\s+\d{4})"
                   r"\s*,\s*(?P<name>(?:[A-ZÉÈ«\"]|[dl]['’]|de\s|des\s|du\s)[^,;.()\n]{1,70})")
YEAR = re.compile(r"(?<![\d/.,-])(1[0-9]{3}|20[0-9]{2})(?![\d/]|\s*[-–]\s*\d)")
COMPLEXITY = re.compile(r"(?P<lead>complexit[ée](?:\s+[^:=]{0,70}?)?)\s*(?:est|:|=|vaut)\s*(?:en\s+|de\s+|égale à\s+)?"
                        r"(?P<o>[OΘΩθ]\s*\([^()]{1,30}(?:\([^()]*\))?[^()]{0,10}\))", re.IGNORECASE)
ACRONYM_AFTER = re.compile(r"\b(?P<acro>[A-Z][A-Za-z]?[A-Z]{1,7}s?)\s*\(\s*(?P<exp>[^()]{5,90}?)\s*\)")
ACRONYM_BEFORE = re.compile(r"\(\s*(?P<acro>[A-Z][A-Za-z]?[A-Z]{1,7}s?)\s*\)")
SMALL_WORDS = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "of", "the", "and", "à", "a", "en", "pour", "un",
               "une", "au", "aux", "sur", "par", "for", "in", "to", "on"}

MONTH_BEFORE = re.compile(r"\b(?:janv|févr|mars|avr|mai|juin|juil|août|sept|oct|nov|déc)\w*\.?\s*$", re.IGNORECASE)
PRONOUN_START = re.compile(r"^(?:il|elle|ils|elles|on|cela|ceci|ça|c['’]est)\b", re.IGNORECASE)

MAX_ANSWER = 600
MAX_YEAR_CLOZES_PER_PAGE = 2

# Étiquettes de spécification : la question reprend la ligne de contexte (ex. « Procédure dépiler () »).
SPEC_LABELS = {"précondition", "préconditions", "postcondition", "postconditions", "résultat", "résultats",
               "paramètre", "paramètres", "paramètre en mode donnée", "paramètre en mode donnée-résultat",
               "paramètre en mode résultat", "retour", "valeur de retour"}
# Étiquettes qui se rapportent au titre de la diapositive.
TITLE_LABELS = {"rôle", "but", "objectif", "principe", "méthode", "idée", "solution", "complexité",
                "avantage", "avantages", "inconvénient", "inconvénients", "intérêt", "définition", "algorithme",
                "limites", "limite", "caractéristiques", "propriétés", "conséquences", "conditions", "causes",
                "effets", "étapes", "exceptions"}
# Débuts de « termes » qui n'en sont pas.
NOT_TERMS = re.compile(r"^(?:par|pour|avec|en|dans|sur|si|sinon|ex|exemples?|remarques?|attention|note|nb|n\.b|"
                       r"rappels?|importer|exporter|variables?|variables locales|début|fin|il|elle|on|ce|cela|ceci|"
                       r"c['’]est|il y a|ici|alors|donc|mais|or|et|ou|cette|cet|ces|son|sa|ses|leur|leurs|notre|"
                       r"votre|tout|toute|tous|chaque|même|aussi|puis|ensuite|enfin|selon|d['’]après|depuis|"
                       r"lorsque|quand|comme|soit)\b", re.IGNORECASE)
# Mots qui ne font jamais partie d'un terme défini (consignes, renvois, mots de liaison, pronoms).
BAD_TERM_WORDS = {"exercice", "exercices", "exemple", "exemples", "sujet", "objectifs", "tp", "td", "cm", "code",
                  "étape", "suite", "remarque", "question", "questions", "réponse", "voir", "slide", "diapositive",
                  "page", "figure", "cette", "cet", "ces", "cela", "ceci", "il", "elle", "ils", "elles", "nous",
                  "vous", "je", "tu", "première", "deuxième", "troisième", "premier", "second", "seconde",
                  "dernière", "dernier", "différence", "différences", "fondement", "suivant", "suivante",
                  "suivants", "ci-dessous", "ci-dessus", "dessous", "dessus", "fichier", "ligne", "lignes", "gauche",
                  "droite", "haut", "bas", "choses", "chose", "trucs", "contexte", "rappel", "rappels"}
MATH = re.compile(r"[=×≈÷√∑∫^]|[\U0001D400-\U0001D7FF]")
FORMULA = re.compile(r"=\s*[\w(]+\s*[-+*/×]")
# Verbes conjugués : un « terme » qui en contient un est une phrase, pas une notion.
VERBS = {"est", "sont", "a", "ont", "fait", "font", "peut", "peuvent", "doit", "doivent", "déclare", "adopte",
         "donne", "donnent", "retrouve", "permet", "permettent", "va", "vont", "était", "étaient", "sera", "seront",
         "avait", "avaient", "existe", "existent", "signifie", "devient", "deviennent", "prend", "prennent",
         "considère", "rejoint", "affirme", "estime", "juge", "reconnaît", "pose", "précise", "dit", "rappelle",
         "contient", "contiennent", "utilise", "utilisent", "renvoie", "retourne", "appelle", "crée", "définit"}
END_WORDS = {"de", "du", "des", "la", "le", "les", "à", "au", "aux", "en", "et", "ou", "un", "une", "par", "pour",
             "d", "l", "sur", "dans", "avec", "que", "qui"}
CODE_LIKE = re.compile(r"[{}←]|[\w)\]\"'];\s*$|;\s*\w+\s*[=<>+-]|\w\(\)|\w\[\w*\]|\b(?:int|void|char|return|cout|cin|new|delete|def|class|"
                       r"printf|scanf|std|include|struct|float|bool)\b|[=!<>]=|\+\+|->|::")
BAD_TITLE = re.compile(r"\b(?:exemples?|exercices?|code|tp|td|démo|correction|corrigé)\b", re.IGNORECASE)


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
            joiner = "" if out[-1].endswith("-") and out[-1][-2:-1].isalpha() else " "
            out[-1] += joiner + line
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


def _words(s: str) -> list[str]:
    return re.findall(r"[\wÀ-ÿ]+", s.lower())


def is_term(term: str, strict: bool = True) -> bool:
    """Vrai si `term` ressemble à une notion qu'on définit (un groupe nominal court), pas à une phrase."""
    term = term.strip()
    words = _words(term)
    if not 1 <= len(words) <= (5 if strict else 6) or not 2 <= len(term) <= 60:
        return False
    if term.count("(") != term.count(")") or NOT_TERMS.match(term) or CODE_LIKE.search(term):
        return False
    if any(w in BAD_TERM_WORDS or w in VERBS for w in words) or words[-1] in END_WORDS:
        return False
    if any(ch.isdigit() for ch in term) and not (len(words) == 1 and len(term) <= 10):
        return False
    if re.search(r"[a-z][A-Z]", term) or "_" in term:
        return False  # nomVariable, nom_fichier : du code, pas une notion
    return True


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


def what_is(art: str | None, term: str) -> str:
    """« Qu'est-ce qu'une pile ? », « Qu'est-ce que l'impôt ? », « Que sont les SP… ? », « Qu'est-ce que « X » ? »"""
    art = (art or "").strip()
    a = art.lower().replace("’", "'")
    if a:
        term = _lower_first(term)
    if a in ("le", "la"):
        return f"Qu'est-ce que {a} {term} ?"
    if a == "l'":
        return f"Qu'est-ce que l'{term} ?"
    if a == "les":
        return f"Que sont les {term} ?"
    if a in ("un", "une"):
        return f"Qu'est-ce qu'{a} {term} ?"
    return f"Qu'est-ce que « {term} » ?"


def _with_art(art: str | None, term: str) -> str:
    art = (art or "").strip()
    if not art:
        return f"« {term} »"
    return f"{art.lower()}{term}" if art.endswith(("'", "’")) else f"{art.lower()} {term}"


def _answer(text: str) -> str:
    text = text.strip()
    return shorten(text[:1].upper() + text[1:] if text else text)


# --------------------------------------------------------------------------- sigles
def _initials(words: list[str]) -> list[str]:
    return [w[0].lower() for w in words if w.lower() not in SMALL_WORDS and w[:1].isalpha()]


def acronym_matches(acro: str, expansion: str) -> bool:
    """Les lettres du sigle sont les initiales des mots importants de l'expansion (un mot de trop toléré)."""
    letters = [c.lower() for c in acro.rstrip("s") if c.isupper()] or [acro[0].lower()]
    initials = _initials(re.findall(r"[\wÀ-ÿ]+", expansion))
    if not initials or initials[0] != letters[0] or not 0 <= len(initials) - len(letters) <= 1:
        return False
    it = iter(initials)
    return all(any(c == i for i in it) for c in letters)


def acronym_cards(line: str, page: int, section: str) -> list[CardDraft]:
    out = []
    for m in ACRONYM_AFTER.finditer(line):
        if acronym_matches(m.group("acro"), m.group("exp")):
            out.append((m.group("acro"), m.group("exp")))
    for m in ACRONYM_BEFORE.finditer(line):
        acro = m.group("acro")
        before = re.findall(r"[\wÀ-ÿ'’-]+", line[:m.start()])[-12:]
        best = None
        for k in range(len(before), 0, -1):  # le plus petit groupe de mots qui donne les initiales
            candidate = before[len(before) - k:]
            if candidate[0][:1].lower() == acro[0].lower() and acronym_matches(acro, " ".join(candidate)):
                best = " ".join(candidate)
        if best:
            out.append((acro, best))
    cards = []
    for acro, exp in out:
        exp = exp.strip(" ,;:")
        cards.append(CardDraft("qa", f"Que signifie le sigle {acro} ?", _answer(exp), page, section))
    return cards


# --------------------------------------------------------------------------- arrêts, dates, complexité
def arret_cards(line: str, page: int, section: str) -> list[CardDraft]:
    cards = []
    for m in ARRET.finditer(line):
        name = re.split(r"\s+(?:et|–|—|-)\s+|\s*:|\s{2,}", m.group("name").strip())[0].strip(" «»\"")
        if (len(name) < 2 or len(name.split()) > 8 or name.count("«") != name.count("»")
                or _words(name)[-1] in END_WORDS):
            continue
        court = " ".join(m.group("court").split())
        cards.append(CardDraft("qa", f"Arrêt {name} : quelle juridiction et quelle date ?",
                               f"{court}, {m.group('date')}", page, section))
    return cards


def year_cloze(line: str, page: int, section: str) -> CardDraft | None:
    """« En 2007, le CE donne un mode d'emploi… » → « En […], le CE donne… » / « 2007 »."""
    if (ARRET.search(line) or len(line.split()) < 7 or len(line) > 400 or CODE_LIKE.search(line)
            or not line[:1].isupper() or line.count("(") != line.count(")") or MATH.search(line)):
        return None
    years = YEAR.findall(line)
    if len(years) != 1 or MONTH_BEFORE.search(line[:YEAR.search(line).start()]):
        return None  # une date complète (« 21 février 2013 ») est une référence, pas un fait à retenir
    hidden = YEAR.sub("[…]", line, count=1)
    if "[…]" not in hidden:
        return None
    return CardDraft("cloze", hidden, years[0], page, section)


def complexity_card(line: str, title: str, page: int) -> CardDraft | None:
    m = COMPLEXITY.search(line)
    if not m:
        return None
    lead = " ".join(m.group("lead").split()).rstrip(" ,")
    lead = _lower_first(lead)
    if not re.search(r"\b(?:de|du|des|d['’])\s", lead):
        if not title:
            return None
        lead += f" de « {title} »"
    return CardDraft("qa", f"Quelle est la {lead} ?", m.group("o").replace(" ", ""), page, title)


# --------------------------------------------------------------------------- définitions
def definition_card(content: str, title: str, context: str, page: int) -> list[CardDraft]:
    """Cartes pour une ligne de définition, ou [] si la ligne n'en est pas une."""
    if content.endswith("?"):
        return []  # question posée sur la diapositive, pas une définition
    for rx in (CALLED, PURPOSE, CONSISTS, IS_DEF, COLON_DEF):
        m = rx.match(content)
        if not m:
            continue
        art = m.groupdict().get("art")
        term = m.group("term").strip(" :-")
        definition = m.group("def").strip()
        if PRONOUN_START.match(definition):
            return []  # « Les ordres : ils constituent des SP » : une remarque, pas une définition
        low = term.lower().replace("-", "")
        if rx is COLON_DEF:
            if low in {x.replace("-", "") for x in SPEC_LABELS}:
                ctx = context if context and context != title else title
                if not ctx:
                    return []
                label = term.lower()
                label = label.rstrip("s") if label.endswith(("conditions", "résultats")) else label
                return [CardDraft("qa", f"{ctx} — {label} ?", _answer(definition), page, title)]
            if low in TITLE_LABELS:
                if not title or BAD_TITLE.search(title):
                    return []
                return [CardDraft("qa", f"{title} — {term.lower()} ?", _answer(definition), page, title)]
            if term.isupper() and acronym_matches(term, definition):
                return [CardDraft("qa", f"Que signifie le sigle {term} ?", _answer(definition), page, title)]
            if (CODE_LIKE.search(definition) or MATH.search(definition) or len(_words(definition)) < 4
                    or re.search(r"\w\s:\s\w", definition)  # « jour : entier mois : entier » (déclarations)
                    or not is_term(term)
                    or (art is None and len(_words(term)) > 3)):
                return []
        elif not is_term(term, strict=rx is not CALLED):
            return []
        if rx is PURPOSE:
            verb = " ".join(m.group("verb").split()).lower()
            return [CardDraft("qa", f"À quoi sert {_with_art(art, term)} ?", _answer(f"{verb} {definition}"),
                              page, title)]
        if rx is CONSISTS:
            return [CardDraft("qa", f"En quoi consiste {_with_art(art, term)} ?", _answer(definition), page, title)]
        question = what_is(art, term)
        if rx is COLON_DEF and not art and title and not BAD_TITLE.search(title) and term.lower() not in title.lower():
            question = question.removesuffix(" ?") + f" ({title}) ?"  # « Initialisation » seul ne dit rien
        cards = [CardDraft("qa", question, _answer(definition), page, title)]
        if rx is not COLON_DEF:
            # Texte à trous uniquement sur une vraie phrase de définition.
            hidden = re.sub(re.escape(term), "[…]", content, count=1, flags=re.IGNORECASE)
            if hidden != content:
                cards.append(CardDraft("cloze", shorten(hidden), term, page, title))
        return cards
    return []


def title_from_filename(stem: str) -> str:
    t = re.sub(r"^\s*\[[^\]]*\]\s*", "", stem)        # préfixe « [LIFAPSD] »
    t = re.sub(r"\s*\(\d+\)\s*$", "", t)                 # suffixe « (1) » des téléchargements
    return t.replace("_", " ").strip() or stem


def _split_items(text: str) -> list[str]:
    parts = re.split(r"\s*;\s*|\s*,\s*(?:et\s+)?|\s+et\s+", text.strip().rstrip("."))
    return [p.strip() for p in parts if p.strip()]


def list_question(lead: str, title: str) -> str | None:
    """Question pour une liste annoncée par `lead` (ligne qui finit par « : »), ou None."""
    lead = lead.rstrip(" :").strip()
    if m := ENUMERATION.match(lead + " :"):
        return f"Cite les {m.group('n')} {m.group('what').strip()}."
    if m := ENUM_TAIL.search(lead):
        before = lead[:m.start()].strip(" ,;")
        if before and (len(_words(before)) > 8 or _words(before)[-1] in END_WORDS
                       or any(w in VERBS for w in _words(before))):
            before = ""
        if m.group("what").split()[0].lower() in BAD_TERM_WORDS:
            return f"Complète : « {lead} : … »" if lead[:1].isupper() else None
        return f"Cite les {m.group('n')} {m.group('what').strip()}" + (f" ({before})." if before else ".")
    label = lead.lower()
    if label in TITLE_LABELS:
        return f"Quels sont les {label} de « {title} » ?" if title and not BAD_TITLE.search(title) else None
    if (3 <= len(_words(lead)) <= 25 and lead[:1].isupper() and not CODE_LIKE.search(lead)
            and not BAD_TITLE.search(lead)):
        return f"Complète : « {lead} : … »"
    return None


def cards_from_page(text: str, page: int) -> list[CardDraft]:
    lines = merge_wrapped(clean_lines(text))
    if not lines:
        return []
    title = guess_title(lines)
    if title and SKIP_TITLES.match(title):
        return []
    body = lines[1:] if title and lines[0] == title else lines
    code_page = sum(bool(CODE_LIKE.search(ln)) for ln in body) > 0.3 * max(1, len(body))
    cards: list[CardDraft] = []
    context = title
    used_bullets: set[int] = set()
    defined: set[int] = set()  # lignes déjà transformées en définition
    years = 0

    i = 0
    while i < len(body):
        line = body[i]
        bullet = BULLET.match(line)
        content = bullet.group(1) if bullet else line

        # Énoncé : « Théorème (Pythagore) : … » + lignes suivantes jusqu'à un nouvel énoncé
        if (m := STATEMENT.match(content)) and not code_page and (m.group("rest") == "" or m.group("name")
                                                                 or re.match(r"\w+\s*[\d.]*\s*[:.—–-]", content)):
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
            used_bullets.update(range(i, j))
            i = j
            continue

        cards += acronym_cards(content, page, title)
        cards += arret_cards(content, page, title)
        if not code_page and (c := complexity_card(content, title, page)):
            cards.append(c)

        # Liste annoncée : « Les trois critères sont : » / « Avantages : » suivis de puces
        if content.endswith(":") and not code_page:
            j = i + 1
            items = []
            while j < len(body) and (b := BULLET.match(body[j])) and len(items) < 10:
                items.append(b.group(1))
                j += 1
            q = list_question(content, title) if 2 <= len(items) <= 10 else None
            if q and all(len(x) <= 200 for x in items):
                cards.append(CardDraft("qa", q, shorten("\n".join(f"- {x}" for x in items), 900), page, title))
                used_bullets.update(range(i, j))
                i = j
                continue
        if (m := ENUMERATION.match(content)) and m.group("items"):
            items = _split_items(m.group("items"))
            if 2 <= len(items) <= 10:
                cards.append(CardDraft("qa", f"Cite les {m.group('n')} {m.group('what').strip()}.",
                                       "\n".join(f"- {x}" for x in items), page, title))
                i += 1
                continue

        if not code_page and (found := definition_card(content, title, context, page)):
            cards.extend(found)
            defined.add(i)
        elif not COLON_DEF.match(content) and 3 <= len(content) <= 90 and not content.endswith((".", "?")):
            context = content  # ligne d'intitulé (ex. « Procédure empiler (e: ElementP) »)
        if years < MAX_YEAR_CLOZES_PER_PAGE and (c := year_cloze(content, page, title)):
            cards.append(c)
            years += 1
        i += 1

    # Liste à puces significative : « points clés » de la diapositive.
    bullet_rows = [k for k, line in enumerate(body) if k not in used_bullets and BULLET.match(line)]
    bullets = [BULLET.match(body[k]).group(1) for k in bullet_rows]
    if (sum(k in defined for k in bullet_rows) * 2 < len(bullet_rows) and title and not code_page and not BAD_TITLE.search(title) and 2 <= len(bullets) <= 8
            and all(8 <= len(b) <= 160 for b in bullets)
            and not any(CODE_LIKE.search(b) or FORMULA.search(b) for b in bullets)):
        answer = "\n".join(f"- {b}" for b in bullets)
        cards.append(CardDraft("qa", f"Quels sont les points clés de « {title} » ?", shorten(answer, 900), page, title))
    return cards


def _key(s: str) -> str:
    return " ".join(_words(s))


def course_cards(texts: list[str], slides: bool = True) -> list[CardDraft]:
    """Toutes les cartes d'un cours (texte page par page), sans doublon."""
    cards: list[CardDraft] = []
    seen_q: set[str] = set()
    seen_qa: set[tuple[str, str]] = set()
    for n, text in enumerate(clean_pages(texts, slides), start=1):
        for c in cards_from_page(text, n):
            norm = c.normalized()
            if norm is None:
                continue
            q, a = _key(norm.question), _key(norm.answer)
            # Même question, ou même réponse à une question qui porte sur la même chose : doublon.
            if q in seen_q or (a, q[:40]) in seen_qa or not a or a == q:
                continue
            seen_q.add(q)
            seen_qa.add((a, q[:40]))
            cards.append(norm)
    return cards


class SimpleEngine:
    name = "simple"

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        progress(Step("Lecture du texte du cours…", 0.1))
        texts = page_texts(pdf)
        if not any(t.strip() for t in texts):
            from revise.models import ReviseError
            raise ReviseError("Aucun texte dans ce cours (pages scannées ?). "
                              "Sans IA, l'application ne lit que le texte.")
        progress(Step(f"Recherche des notions sur {len(texts)} pages…", 0.5))
        cards = course_cards(texts, pdf.suffix.lower() in (".pdf", ".pptx"))
        title = title_from_filename(pdf.stem)
        progress(Step(f"{len(cards)} cartes trouvées sur {len(texts)} pages", 1.0))
        return title, cards
