"""Affichage du texte d'une carte : Markdown, formules LaTeX rendues lisibles, code coloré."""

from __future__ import annotations

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QTextEdit

from revise import mathtext
from revise.gui import theme

# Du plus précis au plus général : la première famille qui contient le jeton donne sa couleur.
CODE_COLORS = (
    ("Comment", theme.MUTED), ("Keyword", "#c792ea"), ("Operator.Word", "#c792ea"),
    ("Name.Function", "#82aaff"), ("Name.Class", "#ffcb6b"), ("Name.Decorator", "#82aaff"),
    ("Name.Builtin", "#89ddff"), ("Name.Tag", "#f07178"), ("Name.Attribute", "#ffcb6b"),
    ("Literal.String", "#c3e88d"), ("Literal.Number", "#f78c6c"), ("Operator", "#89ddff"),
)


def _color(token) -> str | None:
    name = str(token).removeprefix("Token.")
    for family, color in CODE_COLORS:
        if name == family or name.startswith(family + "."):
            return color
    return None


def highlight_code(doc: QTextDocument) -> None:
    """Colore les blocs de code ```langage … ``` du document (ceux sans langage restent tels quels)."""
    try:
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError:  # sans la bibliothèque, le code reste lisible, juste sans couleurs
        return
    block = doc.begin()
    while block.isValid():
        fmt = block.blockFormat()
        if not fmt.hasProperty(QTextFormat.Property.BlockCodeFence):
            block = block.next()
            continue
        language = fmt.stringProperty(QTextFormat.Property.BlockCodeLanguage)
        start, lines = block.position(), []
        while (block.isValid() and block.blockFormat().hasProperty(QTextFormat.Property.BlockCodeFence)
               and block.blockFormat().stringProperty(QTextFormat.Property.BlockCodeLanguage) == language):
            lines.append(block.text())
            block = block.next()
        if not language:
            continue
        try:
            lexer = get_lexer_by_name(language.strip().lower(), stripnl=False, ensurenl=False)
        except (ClassNotFound, ImportError):  # langage inconnu, ou absent de l'application empaquetée
            continue
        cursor = QTextCursor(doc)
        try:
            tokens = list(lexer.get_tokens_unprocessed("\n".join(lines)))
        except Exception:  # un analyseur qui plante ne doit pas empêcher d'afficher la carte
            continue
        for index, token, value in tokens:
            color = _color(token)
            if color and value.strip():
                cursor.setPosition(start + index)
                cursor.setPosition(start + index + len(value), QTextCursor.MoveMode.KeepAnchor)
                char = QTextCharFormat()
                char.setForeground(QColor(color))
                cursor.mergeCharFormat(char)


def show_markdown(view: QTextEdit, text: str) -> None:
    """Affiche `text` (Markdown d'une carte) dans `view`."""
    view.setMarkdown(mathtext.render(text))
    highlight_code(view.document())
