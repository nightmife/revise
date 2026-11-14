"""Moteur « abonnement » : passe par Claude Code en mode non interactif (`claude -p`).

Utilise l'abonnement Claude (Pro, Max…) de l'utilisateur, sans clé API. Il faut que Claude Code
soit installé et connecté sur la machine : l'application ne propose ce moteur que dans ce cas."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from revise.engines import Progress, distractors
from revise.engines.prompt import CARD_SCHEMA, generate_cards
from revise.models import CardDraft, ReviseError

TIMEOUT = 1200  # secondes par appel
# Une application lancée depuis le Finder ou le menu ne connaît pas le PATH du terminal.
EXTRA_DIRS = ("~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin")


def claude_binary() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    for folder in EXTRA_DIRS:
        for name in ("claude", "claude.exe", "claude.cmd"):
            path = Path(folder).expanduser() / name
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def _env() -> dict[str, str]:
    # Sans ces variables, Claude Code utilise la connexion de l'abonnement (et pas une clé API payante).
    env = dict(os.environ)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(var, None)
    return env


class ClaudeCodeEngine:
    name = "abonnement"

    def __init__(self, runner=subprocess.run, model: str | None = None):
        self.runner = runner
        self.model = model or os.environ.get("REVISE_MODELE") or None
        self.progress: Progress = lambda m: None

    def check(self) -> None:
        if not claude_binary():
            raise ReviseError("Claude Code est introuvable sur cet ordinateur : installe-le et connecte-toi "
                              "(commande `claude`, puis /login).")

    def chat(self, system: str, user: str, schema: dict = CARD_SCHEMA) -> str:
        self.check()
        cmd = [claude_binary(), "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
               "--system-prompt", system, "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
               "--no-session-persistence"]
        if self.model:
            cmd += ["--model", self.model]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with tempfile.TemporaryDirectory(prefix="revise-") as tmp:  # dossier vide : aucun projet à lire
            try:
                proc = self.runner(cmd, cwd=tmp, env=_env(), input=user, capture_output=True, text=True,
                                   encoding="utf-8", timeout=TIMEOUT, creationflags=flags)
            except subprocess.TimeoutExpired as e:
                raise ReviseError(f"Claude n'a pas répondu en {TIMEOUT // 60} min.") from e
            except OSError as e:
                raise ReviseError(f"Impossible de lancer Claude Code ({e}).") from e
        out = (proc.stdout or "").strip()
        try:
            outer = json.loads(out.splitlines()[-1] if out else "")
        except (json.JSONDecodeError, IndexError):
            detail = (proc.stderr or out or "pas de sortie").strip()[:400]
            raise ReviseError(f"Claude Code a échoué (code {proc.returncode}) : {detail}") from None
        if not isinstance(outer, dict) or outer.get("is_error") or outer.get("subtype") != "success":
            msg = str(outer.get("result") or outer.get("subtype") or "erreur inconnue")[:400] \
                if isinstance(outer, dict) else "réponse inattendue"
            if "limit" in msg.lower():
                msg += " (limite d'utilisation de l'abonnement atteinte : réessaie plus tard)"
            if "login" in msg.lower() or "auth" in msg.lower():
                msg += " (lance `claude` dans un terminal, puis /login)"
            raise ReviseError(f"Claude Code : {msg}")
        data = outer.get("structured_output")
        return json.dumps(data) if data is not None else str(outer.get("result") or "")

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        self.check()
        self.progress = progress
        title, cards = generate_cards(pdf, subject, progress, self.chat, "Claude")
        distractors.add_to_drafts(cards, subject, self.chat, progress, "Claude")
        return title, cards
