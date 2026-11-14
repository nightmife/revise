"""Moteur « en ligne » : une IA hébergée, appelée avec la clé API gratuite de l'utilisateur
(Groq, Google Gemini, ou tout service compatible avec l'API d'OpenAI). Rapide, mais il
faut Internet et le texte du cours est envoyé au service choisi."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from revise import config, net
from revise.engines import Progress, distractors
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
Get = Callable[[str, dict, float], dict]

# Modèles qui ne servent pas à écrire du texte (voix, images, filtres…).
NOT_CHAT = ("whisper", "tts", "guard", "embed", "image", "imagen", "audio", "live", "speech", "veo", "compound",
            "orpheus", "aqa", "robotics", "computer-use", "lite")
# Par service, morceaux de nom des modèles à préférer, du meilleur au moins bon.
PREFERRED = {"groq": ("gpt-oss-120b", "llama-3.3-70b", "qwen", "gpt-oss", "llama"), "gemini": ("flash", "pro")}


def http_post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers=headers)
    with net.urlopen(req, timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(url: str, headers: dict, timeout: float) -> dict:
    with net.urlopen(urllib.request.Request(url, headers=headers), timeout) as resp:
        return json.loads(resp.read().decode())


def pick_model(ids: list[str], provider: str) -> str:
    """Choisit un modèle de texte parmi ceux que le service propose à cette clé ("" si aucun)."""
    usable = sorted(i.removeprefix("models/") for i in ids if not any(w in i.lower() for w in NOT_CHAT))
    for wanted in PREFERRED.get(provider, ()):
        found = [m for m in usable if wanted in m.lower()]
        if found:
            return found[-1]  # le dernier dans l'ordre alphabétique : en général la version la plus récente
    return usable[0] if usable else ""


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

    def __init__(self, post: Post = http_post, sleep: Callable[[float], None] = time.sleep, conf: dict | None = None,
                 get: Get = http_get):
        self.post = post
        self.get = get
        self.replaced_model = False
        self.sleep = sleep
        self.conf = conf or settings()
        self.progress: Progress = lambda m: None

    def chat(self, system: str, user: str, schema: dict | None = None) -> str:
        """`schema` est ignoré : ces services garantissent du JSON, pas un schéma précis."""
        c = self.conf
        payload = {
            "model": c["model"],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {c['key']}", "User-Agent": "revise"}
        for attempt in range(MAX_RETRIES):
            payload["model"] = c["model"]
            try:
                data = self.post(c["url"] + "/chat/completions", headers, payload, TIMEOUT)
                return data["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                detail = _error_detail(e)
                if e.code in (429, 503) and attempt < MAX_RETRIES - 1:
                    if re.search(r"limit:\s*0\b", detail):  # aucun quota : attendre ne sert à rien
                        raise ReviseError(
                            f"Ce service n'accorde aucune utilisation gratuite à ta clé pour le modèle "
                            f"« {c['model']} » (fréquent avec Gemini en Europe). Choisis le service Groq dans "
                            f"« Configurer… », ou utilise l'IA de cet ordinateur. Détail : {detail}") from e
                    try:
                        wait = float(e.headers.get("Retry-After", ""))
                    except (TypeError, ValueError):
                        wait = 15.0 * (attempt + 1)
                    wait = min(max(wait, 1.0), 120.0)
                    self.progress(f"limite du service atteinte, nouvelle tentative dans {round(wait)} s… "
                                  f"{detail[:160]}".strip())
                    self.sleep(wait)
                    continue
                if e.code in (429, 503):
                    raise ReviseError(f"Le service d'IA refuse toujours après plusieurs essais ({e.code}) : quota "
                                      f"gratuit épuisé ou service saturé. Réessaie plus tard, change de service dans "
                                      f"« Configurer… », ou utilise l'IA de cet ordinateur. Détail : {detail}") from e
                if e.code in (401, 403):
                    raise ReviseError(f"Clé API refusée par le service ({e.code}). Vérifie la clé. {detail}") from e
                unknown = e.code == 404 or (e.code == 400 and re.search(
                    r"decommission|not found|does not exist|no longer|not supported|unknown model", detail, re.I))
                if unknown and not self.replaced_model and self._replace_model():
                    continue
                if unknown:
                    raise ReviseError(f"Modèle « {c['model']} » ou adresse inconnus du service : change le modèle "
                                      f"dans les réglages avancés de « Configurer… ». {detail}") from e
                raise ReviseError(f"Le service d'IA a répondu une erreur ({e.code}). {detail}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                raise ReviseError(f"Impossible de joindre le service d'IA ({c['url']}) : vérifie ta connexion. "
                                  f"Détail : {net.reason(e)}") from e
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise ReviseError("Réponse inattendue du service d'IA.") from e
        raise ReviseError("Le service d'IA est saturé : réessaie dans quelques minutes.")

    def _replace_model(self) -> bool:
        """Le modèle réglé n'existe plus chez le service : on prend un de ceux qu'il propose aujourd'hui."""
        self.replaced_model = True
        c = self.conf
        try:
            listing = self.get(c["url"] + "/models", {"Authorization": f"Bearer {c['key']}", "User-Agent": "revise"},
                               60)
            ids = [str(m.get("id") or "") for m in listing.get("data", []) if isinstance(m, dict)]
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, AttributeError):
            return False
        model = pick_model(ids, c["provider"])
        if not model or model == c["model"]:
            return False
        self.progress(f"le modèle « {c['model']} » n'existe plus, utilisation de « {model} »")
        c["model"] = model
        config.save({"online_model": model})
        return True

    def check(self) -> None:
        c = self.conf
        if not c["key"]:
            raise ReviseError("Aucune clé API enregistrée : ajoute-la avec le bouton « Configurer… » de l'onglet "
                              "« Ajouter un cours » (ou la commande « revise cle »).")
        if not c["url"] or not c["model"]:
            raise ReviseError("Adresse ou modèle du service d'IA manquant dans les réglages de la clé API.")

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        self.check()
        self.progress = progress
        label = f"IA en ligne ({self.conf['model']})"
        title, cards = generate_cards(pdf, subject, progress, self.chat, label)
        distractors.add_to_drafts(cards, subject, self.chat, progress, label)
        return title, cards


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
