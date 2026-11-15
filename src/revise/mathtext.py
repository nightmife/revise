"""Formules LaTeX des cartes (`$x^2$`, `\\(\\alpha\\)`, `$$\\frac{a}{b}$$`) réécrites en texte lisible : x², α, a/b.

Ce n'est pas un vrai moteur de rendu mathématique : juste de quoi lire une formule de cours sans les
codes LaTeX. Le code (`…` et blocs ```) n'est jamais touché."""

from __future__ import annotations

import re

SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈", "equiv": "≡", "sim": "∼",
    "simeq": "≃", "propto": "∝", "ll": "≪", "gg": "≫", "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "ast": "∗", "star": "⋆", "circ": "∘", "oplus": "⊕", "otimes": "⊗", "infty": "∞", "partial": "∂", "nabla": "∇",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇",
    "cup": "∪", "cap": "∩", "setminus": "∖", "emptyset": "∅", "varnothing": "∅", "forall": "∀", "exists": "∃",
    "nexists": "∄", "neg": "¬", "lnot": "¬", "land": "∧", "wedge": "∧", "lor": "∨", "vee": "∨",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←", "leftrightarrow": "↔", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "Leftrightarrow": "⇔", "implies": "⇒", "iff": "⇔", "mapsto": "↦", "longrightarrow": "⟶",
    "uparrow": "↑", "downarrow": "↓", "sum": "Σ", "prod": "Π", "int": "∫", "iint": "∬", "oint": "∮",
    "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "langle": "⟨", "rangle": "⟩", "mid": "|", "vert": "|", "Vert": "‖", "parallel": "∥", "perp": "⊥",
    "angle": "∠", "triangle": "△", "degree": "°", "prime": "′", "ell": "ℓ", "hbar": "ℏ", "Re": "ℜ", "Im": "ℑ",
    "aleph": "ℵ", "top": "⊤", "bot": "⊥", "vdash": "⊢", "models": "⊨", "bullet": "•", "quad": "  ", "qquad": "    ",
    "lbrace": "{", "rbrace": "}", "backslash": "\\", "colon": ":", "bmod": " mod ", "land ": "∧",
}
FUNCTIONS = {"log", "ln", "lg", "exp", "sin", "cos", "tan", "cot", "arcsin", "arccos", "arctan", "sinh", "cosh",
             "tanh", "min", "max", "sup", "inf", "lim", "det", "dim", "ker", "gcd", "deg", "arg", "mod", "Pr"}
PLAIN = {"text", "textrm", "textbf", "textit", "texttt", "mathrm", "mathbf", "mathit", "mathsf", "mathtt",
         "mathcal", "mathscr", "mathfrak", "operatorname", "boldsymbol", "bm", "mbox", "hbox"}
IGNORED = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "displaystyle",
           "textstyle", "limits", "nolimits", "scriptstyle"}
SPACES = {",": " ", ";": " ", ":": " ", "!": "", " ": " ", ">": " "}
BLACKBOARD = {"N": "ℕ", "Z": "ℤ", "Q": "ℚ", "R": "ℝ", "C": "ℂ", "P": "ℙ", "E": "𝔼", "K": "𝕂", "1": "𝟙"}
ACCENTS = {"vec": "⃗", "hat": "̂", "widehat": "̂", "bar": "̄", "overline": "̅",
           "tilde": "̃", "widetilde": "̃", "dot": "̇", "ddot": "̈"}
SUPER = dict(zip("0123456789+-=()abcdefghijklmnoprstuvwxyz",
                 "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"))
SUB = dict(zip("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"))

_ATOM = re.compile(r"[\w.,′°∞α-ωΑ-Ωℕℤℚℝℂ]+")


def _wrap(text: str) -> str:
    """Parenthèses autour d'une expression composée (pour qu'une fraction reste lisible : (a+b)/2)."""
    return text if not text or _ATOM.fullmatch(text) or re.fullmatch(r"\(.*\)|\[.*\]", text) else f"({text})"


def _script(text: str, table: dict[str, str], mark: str) -> str:
    if text and all(ch in table for ch in text):
        return "".join(table[ch] for ch in text)
    return mark + (text if len(text) <= 1 else f"({text})")


class _Parser:
    def __init__(self, source: str):
        self.s = source
        self.i = 0

    def parse(self, stop: str = "") -> str:
        """Convertit jusqu'à la fin, ou jusqu'au caractère `stop` (consommé)."""
        out: list[str] = []
        while self.i < len(self.s):
            ch = self.s[self.i]
            if stop and ch == stop:
                self.i += 1
                break
            out.append(self.item())
        return "".join(out)

    def item(self) -> str:
        ch = self.s[self.i]
        self.i += 1
        if ch == "\\":
            return self.command()
        if ch == "{":
            return self.parse("}")
        if ch == "}":
            return ""
        if ch == "^":
            return _script(self.argument(), SUPER, "^")
        if ch == "_":
            return _script(self.argument(), SUB, "_")
        if ch == "~":
            return " "
        if ch == "&":
            return "  "
        return ch

    def argument(self) -> str:
        """Ce sur quoi porte une commande : un groupe {…}, une commande, ou un seul caractère."""
        while self.i < len(self.s) and self.s[self.i] == " ":
            self.i += 1
        if self.i >= len(self.s):
            return ""
        if self.s[self.i] == "{":
            self.i += 1
            return self.parse("}").strip()
        return self.item().strip()

    def command(self) -> str:
        m = re.compile(r"[A-Za-z]+").match(self.s, self.i)
        if not m:  # \{ \} \% \, \\ …
            if self.i >= len(self.s):
                return ""
            ch = self.s[self.i]
            self.i += 1
            return SPACES.get(ch, " " if ch == "\\" else ch)
        name = m.group()
        self.i = m.end()
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            top, bottom = self.argument(), self.argument()
            return f"{_wrap(top)}/{_wrap(bottom)}"
        if name in ("binom", "dbinom", "tbinom"):
            top, bottom = self.argument(), self.argument()
            return f"C({top}, {bottom})"
        if name == "sqrt":
            degree = ""
            if self.i < len(self.s) and self.s[self.i] == "[":
                self.i += 1
                degree = _script(self.parse("]").strip(), SUPER, "")
            return f"{degree}√{_wrap(self.argument())}"
        if name in ("mathbb", "mathbbm", "mathds"):
            arg = self.argument()
            return "".join(BLACKBOARD.get(ch, ch) for ch in arg)
        if name in PLAIN:
            return self.argument()
        if name in ACCENTS:
            arg = self.argument()
            return arg + ACCENTS[name] if len(arg) == 1 else f"{arg}{ACCENTS[name]}" if arg else ""
        if name in ("begin", "end"):
            self.argument()
            return " "
        if name in IGNORED:
            if self.i < len(self.s) and self.s[self.i] == ".":  # \left. \right. : délimiteur invisible
                self.i += 1
            return ""
        if name in SYMBOLS:
            return SYMBOLS[name]
        if name in FUNCTIONS:
            follows = self.s[self.i] if self.i < len(self.s) else ""
            return name + (" " if follows.isalnum() or follows == "\\" else "")
        return name  # commande inconnue : on garde au moins son nom


def to_text(tex: str) -> str:
    """Une formule LaTeX (sans ses `$`) → texte lisible."""
    out = _Parser(tex.replace("\n", " ")).parse()
    out = re.sub(r"\s*([=≤≥≠≈≡<>→⇒⇔∈∉⊂⊆∪∩±×+])\s*", r" \1 ", out)  # opérateurs aérés
    out = re.sub(r"([(\[])\s+", r"\1", re.sub(r"\s+([)\],;])", r"\1", out))
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _escape_markdown(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", text)


_CODE = re.compile(r"(```.*?(?:```|\Z)|`[^`\n]+`)", re.S)
_MATH = re.compile(r"\$\$(?P<d1>.+?)\$\$|\\\[(?P<d2>.+?)\\\]|\\\((?P<i1>.+?)\\\)|"
                   r"(?<![\\$\w])\$(?!\s)(?P<i2>[^$\n]+?)(?<![\s\\])\$(?![\w$])", re.S)
_LOOKS_LIKE_MATH = re.compile(r"[\\^_{}=<>+]|^[A-Za-z]{1,2}\d?$|^\d+[A-Za-z]$|^\S*\(.*\)\S*$")


def _replace(m: re.Match) -> str:
    display = m.group("d1") or m.group("d2")
    if display is not None:
        return f"\n\n{_escape_markdown(to_text(display))}\n\n"
    inline = m.group("i1")
    if inline is None:
        inline = m.group("i2")
        if not _LOOKS_LIKE_MATH.search(inline):  # « 5$ et 10$ » : des prix, pas une formule
            return m.group()
    return _escape_markdown(to_text(inline))


def render(markdown: str) -> str:
    """Remplace les formules LaTeX d'un texte Markdown par leur version lisible."""
    if "$" not in markdown and "\\(" not in markdown and "\\[" not in markdown:
        return markdown
    parts = _CODE.split(markdown)
    return "".join(part if i % 2 else _MATH.sub(_replace, part) for i, part in enumerate(parts))
