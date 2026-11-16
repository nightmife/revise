"""Moteur « abonnement » : passe par Claude Code en mode non interactif (`claude -p`).

Utilise l'abonnement Claude (Pro, Max…) de l'utilisateur, sans clé API. Il faut que Claude Code
soit installé et connecté sur la machine : l'application ne propose ce moteur que dans ce cas."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from revise import config
from revise.engines import Progress, distractors
from revise.engines.prompt import CARD_SCHEMA, generate_cards
from revise.models import CardDraft, ReviseError

TIMEOUT = 1200  # secondes par appel
# Modèle choisi (réglage `claude_model`) -> nom affiché. Des alias de Claude Code : toujours la dernière version.
MODELS = {
    "": "Automatique (celui de Claude Code)",
    "opus": "Opus — le meilleur, le plus lent",
    "sonnet": "Sonnet — très bon et rapide",
    "haiku": "Haiku — le plus rapide, moins précis",
}
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
        saved = config.load().get("claude_model")
        self.model = (model or os.environ.get("REVISE_MODELE") or (saved if saved in MODELS else "")) or None
        self.progress: Progress = lambda m: None

    def check(self) -> None:
        if not claude_binary():
            raise ReviseError("Claude Code est introuvable sur cet ordinateur : installe-le et connecte-toi "
                              "(commande `claude`, puis /login).")

    def chat(self, system: str, user: str, schema: dict = CARD_SCHEMA) -> str:
        return self._ask(["--output-format", "json"], system, user, schema)

    def chat_pdf(self, system: str, user: str, document: bytes, schema: dict = CARD_SCHEMA) -> str:
        """Comme `chat`, avec un PDF joint que Claude regarde (pages scannées, schémas). Toujours sans outil :
        le PDF est donné dans le message lui-même, Claude Code ne lit aucun fichier."""
        message = {"type": "user", "message": {"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.b64encode(document).decode("ascii")}},
            {"type": "text", "text": user}]}}
        return self._ask(["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"], system,
                         json.dumps(message) + "\n", schema)

    def _ask(self, formats: list[str], system: str, user: str, schema: dict) -> str:
        self.check()
        cmd = [claude_binary(), "-p", *formats, "--json-schema", json.dumps(schema),
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
        outer = None
        for line in reversed(out.splitlines()):  # la réponse finale est la dernière ligne de type « result »
            try:
                found = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(found, dict) and (outer is None or found.get("type") == "result"):
                outer = found
                if found.get("type") == "result":
                    break
        if outer is None:
            detail = (proc.stderr or out or "pas de sortie").strip()[:400]
            raise ReviseError(f"Claude Code a échoué (code {proc.returncode}) : {detail}")
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
        title, cards = generate_cards(pdf, subject, progress, self.chat, "Claude", self.chat_pdf)
        distractors.add_to_drafts(cards, subject, self.chat, progress, "Claude")
        return title, cards
