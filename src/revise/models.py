"""Types partagés."""

from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("qa", "cloze", "code")


@dataclass
class CardDraft:
    """Carte générée, pas encore enregistrée."""

    kind: str
    question: str
    answer: str
    page: int | None = None
    section: str = ""
    distractors: list[str] = field(default_factory=list)  # mauvaises réponses de QCM écrites par l'IA

    def normalized(self) -> CardDraft | None:
        q, a = self.question.strip(), self.answer.strip()
        if not q or not a:
            return None
        kind = self.kind if self.kind in KINDS else "qa"
        page = self.page if isinstance(self.page, int) and self.page > 0 else None
        return CardDraft(kind, q, a, page, self.section.strip(), list(self.distractors))


class ReviseError(Exception):
    """Erreur destinée à l'utilisateur (message affiché tel quel)."""
