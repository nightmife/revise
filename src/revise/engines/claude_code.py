"""Moteur « abonnement » : passe par Claude Code en mode non interactif (`claude -p`).
Utilise l'abonnement Claude de l'utilisateur au lieu de l'API facturée à l'usage."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from revise.engines import Progress
from revise.engines.claude import CARD_SCHEMA, SYSTEM, cards_from_data
from revise.models import CardDraft, ReviseError
from revise.pdf import PdfChunk, extract_pages, open_pdf

PAGES_PER_CHUNK = 20      # l'outil Read de Claude Code lit au plus 20 pages par appel
TIMEOUT = 1200            # secondes par morceau


def claude_binary() -> str | None:
    return shutil.which("claude")


def _prompt(chunk: PdfChunk, subject: str, total: int) -> str:
    n = chunk.last_page - chunk.first_page + 1
    if n == total:
        where = f"Le fichier ./cours.pdf contient le cours complet ({total} pages)."
    else:
        where = (f"Le fichier ./cours.pdf contient les pages {chunk.first_page} à {chunk.last_page} d'un cours de "
                 f"{total} pages : sa page 1 est la page {chunk.first_page} du cours. "
                 "Donne les numéros de page du cours.")
    return (f"Matière : {subject}.\n{where}\n"
            f"Lis tout le fichier avec l'outil Read (paramètre pages, ex. \"1-{min(n, 20)}\"), images comprises, "
            "puis crée toutes les cartes utiles pour maîtriser ce contenu à l'examen. "
            "Réponds uniquement avec le JSON demandé.")


def _env() -> dict[str, str]:
    # Sans ces variables, Claude Code utilise la connexion de l'abonnement (et pas une clé API payante).
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


class ClaudeCodeEngine:
    name = "abonnement"

    def __init__(self, runner=subprocess.run, model: str | None = None, pages_per_chunk: int = PAGES_PER_CHUNK):
        self.runner = runner
        self.model = model or os.environ.get("REVISE_MODELE") or None
        self.pages_per_chunk = pages_per_chunk

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        exe = claude_binary()
        if not exe:
            raise ReviseError("Commande `claude` introuvable : installe Claude Code et connecte-toi (claude puis /login).")
        reader = open_pdf(pdf)
        total = len(reader.pages)
        if total == 0:
            raise ReviseError("Le PDF ne contient aucune page.")
        title, cards = "", []
        starts = list(range(0, total, self.pages_per_chunk))
        for i, start in enumerate(starts, start=1):
            end = min(total, start + self.pages_per_chunk)
            chunk = PdfChunk(start + 1, end, extract_pages(reader, start, end))
            progress(f"Claude lit les pages {chunk.first_page}-{chunk.last_page} ({i}/{len(starts)}), "
                     "ça prend une à quelques minutes…")
            t, cs = self._run_chunk(exe, chunk, subject, total)
            title = title or t
            cards.extend(cs)
        seen: set[str] = set()
        unique = []
        for c in cards:
            key = " ".join(c.question.lower().split())
            if key not in seen:
                seen.add(key)
                unique.append(c)
        progress(f"{len(unique)} cartes générées")
        return title or pdf.stem, unique

    def _run_chunk(self, exe: str, chunk: PdfChunk, subject: str, total: int) -> tuple[str, list[CardDraft]]:
        with tempfile.TemporaryDirectory(prefix="revise-") as tmp:
            Path(tmp, "cours.pdf").write_bytes(chunk.data)
            cmd = [exe, "-p", _prompt(chunk, subject, total),
                   "--output-format", "json",
                   "--json-schema", json.dumps(CARD_SCHEMA),
                   "--append-system-prompt", SYSTEM,
                   "--tools", "Read", "--allowedTools", "Read",
                   "--no-session-persistence"]
            if self.model:
                cmd += ["--model", self.model]
            try:
                proc = self.runner(cmd, cwd=tmp, env=_env(), capture_output=True, text=True, timeout=TIMEOUT)
            except subprocess.TimeoutExpired as e:
                raise ReviseError(f"Claude Code n'a pas répondu en {TIMEOUT // 60} min "
                                  f"(pages {chunk.first_page}-{chunk.last_page}).") from e
        out = (proc.stdout or "").strip()
        try:
            outer = json.loads(out.splitlines()[-1] if out else "")
        except (json.JSONDecodeError, IndexError):
            detail = (proc.stderr or out or "pas de sortie").strip()[:400]
            raise ReviseError(f"Claude Code a échoué (code {proc.returncode}) : {detail}") from None
        if outer.get("is_error") or outer.get("subtype") != "success":
            msg = str(outer.get("result") or outer.get("subtype") or "erreur inconnue")[:400]
            if "limit" in msg.lower():
                msg += " (limite d'utilisation de l'abonnement atteinte : réessaie plus tard)"
            if "login" in msg.lower() or "auth" in msg.lower():
                msg += " (lance `claude` puis /login)"
            raise ReviseError(f"Claude Code : {msg}")
        data = outer.get("structured_output")
        if data is None:
            try:
                data = json.loads(outer.get("result", ""))
            except json.JSONDecodeError as e:
                raise ReviseError(f"Réponse illisible sur les pages {chunk.first_page}-{chunk.last_page}.") from e
        return cards_from_data(data, chunk)
