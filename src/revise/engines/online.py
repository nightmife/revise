"""Moteur « en ligne » : une IA hébergée, appelée avec la clé API gratuite de l'utilisateur
(Groq, Google Gemini, ou tout service compatible avec l'API d'OpenAI). Rapide, mais il
faut Internet et le texte du cours est envoyé au service choisi."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from revise import config
from revise.engines import Progress
from revise.engines.prompt import generate_cards
from revise.models import CardDraft, ReviseError

# identifiant -> (nom affiché, adresse de l'API, modèle par défaut, page où créer une clé)
PROVIDERS = {
    "groq": ("Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "https://console.groq.com/keys"),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
               "https://aistudio.google.com/apikey"),
    "autre": ("Autre service compatible OpenAI", "", "", ""),
}
TIMEOUT = 300
MAX_RETRIES = 6

Post = Callable[[str, dict, dict, float], dict]


def http_post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def settings() -> dict:
    """Réglages effectifs : fournisseur, adresse, modèle, clé."""
    cfg = config.load()
    provider = cfg.get("online_provider") or "groq"
    if provider not in PROVIDERS:
        provider = "autre"
    _, url, model, _ = PROVIDERS[provider]
    return {
        "provider": provider,
        "url": (cfg.get("online_url") or url).rstrip("/"),
        "model": cfg.get("online_model") or model,
        "key": os.environ.get("REVISE_CLE_API") or cfg.get("online_key") or "",
    }


class OnlineEngine:
    name = "en-ligne"

    def __init__(self, post: Post = http_post, sleep: Callable[[float], None] = time.sleep, conf: dict | None = None):
        self.post = post
        self.sleep = sleep
        self.conf = conf or settings()
        self.progress: Progress = lambda m: None

    def chat(self, system: str, user: str) -> str:
        c = self.conf
        payload = {
            "model": c["model"],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {c['key']}", "User-Agent": "revise"}
        for attempt in range(MAX_RETRIES):
            try:
                data = self.post(c["url"] + "/chat/completions", headers, payload, TIMEOUT)
                return data["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                detail = _error_detail(e)
                if e.code in (429, 503) and attempt < MAX_RETRIES - 1:
                    try:
                        wait = float(e.headers.get("Retry-After", ""))
                    except (TypeError, ValueError):
                        wait = 15.0 * (attempt + 1)
                    wait = min(max(wait, 1.0), 120.0)
                    self.progress(f"limite du service atteinte, nouvelle tentative dans {round(wait)} s…")
                    self.sleep(wait)
                    continue
                if e.code in (401, 403):
                    raise ReviseError(f"Clé API refusée par le service ({e.code}). Vérifie la clé. {detail}") from e
                if e.code == 404:
                    raise ReviseError(f"Modèle « {c['model']} » ou adresse inconnus du service : change le modèle "
                                      f"dans les réglages de la clé API. {detail}") from e
                raise ReviseError(f"Le service d'IA a répondu une erreur ({e.code}). {detail}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                raise ReviseError(f"Impossible de joindre le service d'IA ({c['url']}) : vérifie ta connexion.") from e
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise ReviseError("Réponse inattendue du service d'IA.") from e
        raise ReviseError("Le service d'IA est saturé : réessaie dans quelques minutes.")

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        c = self.conf
        if not c["key"]:
            raise ReviseError("Aucune clé API enregistrée : ajoute-la avec le bouton « Clé API… » de l'onglet "
                              "Importer (ou la commande « revise cle »).")
        if not c["url"] or not c["model"]:
            raise ReviseError("Adresse ou modèle du service d'IA manquant dans les réglages de la clé API.")
        self.progress = progress
        return generate_cards(pdf, subject, progress, self.chat, f"IA en ligne ({c['model']})")


def _error_detail(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode())
    except (ValueError, OSError):
        return ""
    if isinstance(body, list) and body:
        body = body[0]
    err = body.get("error") if isinstance(body, dict) else None
    msg = err.get("message") if isinstance(err, dict) else err
    return str(msg)[:300] if msg else ""
