"""Moteur « en ligne » : une IA hébergée, gratuite.

Avec la clé API gratuite de l'utilisateur (Groq, Google Gemini, Cerebras, Mistral, OpenRouter, ou tout
service compatible avec l'API d'OpenAI) — on peut en enregistrer plusieurs : quand le quota gratuit de
l'une est épuisé, on passe à la suivante. Sans aucune clé, le service gratuit de Pollinations répond
(une réponse toutes les 45 secondes environ). Il faut Internet et le texte du cours est envoyé au service."""

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

KEYLESS = "sans-cle"
# identifiant -> (nom affiché, adresse de l'API, modèle par défaut, page où créer une clé)
PROVIDERS = {
    "groq": ("Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "https://console.groq.com/keys"),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
               "https://aistudio.google.com/apikey"),
    "cerebras": ("Cerebras", "https://api.cerebras.ai/v1", "gpt-oss-120b", "https://cloud.cerebras.ai"),
    "mistral": ("Mistral AI", "https://api.mistral.ai/v1", "mistral-small-latest",
                "https://console.mistral.ai/api-keys"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "openrouter/free",
                   "https://openrouter.ai/settings/keys"),
    KEYLESS: ("Sans clé (Pollinations)", "https://text.pollinations.ai/openai", "openai", ""),
    "autre": ("Autre service compatible OpenAI", "", "", ""),
}
# Ordre dans lequel on essaie les services qui ont une clé, après celui choisi en premier.
FALLBACK_ORDER = ("groq", "cerebras", "gemini", "mistral", "openrouter", "autre")
TIMEOUT = 300
MAX_RETRIES = 6
KEYLESS_BATCH = 4  # le service sans clé coupe ses réponses vers 1500 jetons
RETRIES_BEFORE_SWITCH = 2  # un service saturé est réessayé deux fois avant de passer au suivant

Post = Callable[[str, dict, dict, float], dict]
Get = Callable[[str, dict, float], dict]

# Modèles qui ne servent pas à écrire du texte (voix, images, filtres…).
NOT_CHAT = ("whisper", "tts", "guard", "embed", "image", "imagen", "audio", "live", "speech", "veo", "compound",
            "orpheus", "aqa", "robotics", "computer-use", "lite")
# Par service, morceaux de nom des modèles à préférer, du meilleur au moins bon.
PREFERRED = {"groq": ("gpt-oss-120b", "llama-3.3-70b", "qwen", "gpt-oss", "llama"), "gemini": ("flash", "pro"),
             "cerebras": ("gpt-oss-120b", "qwen", "llama"), "mistral": ("mistral-small-latest", "mistral-medium",
                                                                       "small"),
             "openrouter": ("openrouter/free", ":free")}


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
    if provider == "openrouter":  # seulement les modèles gratuits : une clé OpenRouter peut avoir du crédit payant
        usable = [m for m in usable if m.endswith(":free") or m == "openrouter/free"]
    for wanted in PREFERRED.get(provider, ()):
        found = [m for m in usable if wanted in m.lower()]
        if found:
            return found[-1]  # le dernier dans l'ordre alphabétique : en général la version la plus récente
    return usable[0] if usable else ""


def _keys(cfg: dict) -> dict[str, str]:
    """Clés enregistrées, par service (`online_keys`, et `online_key` des versions d'avant la 0.8)."""
    raw = cfg.get("online_keys")
    keys = {p: k.strip() for p, k in raw.items() if p in PROVIDERS and isinstance(k, str) and k.strip()} \
        if isinstance(raw, dict) else {}
    legacy = cfg.get("online_key")
    if isinstance(legacy, str) and legacy.strip():  # sans service choisi, c'était Groq
        keys.setdefault(cfg.get("online_provider") if cfg.get("online_provider") in PROVIDERS else "groq",
                        legacy.strip())
    return keys


def preferred() -> str:
    """Service essayé en premier : celui choisi, sinon le premier qui a une clé, sinon le service sans clé."""
    cfg = config.load()
    chosen = cfg.get("online_provider")
    if chosen in PROVIDERS:
        return chosen
    keys = _keys(cfg)
    return next((p for p in FALLBACK_ORDER if p in keys), KEYLESS)


def settings(provider: str | None = None) -> dict:
    """Réglages effectifs d'un service (par défaut celui essayé en premier) : fournisseur, adresse, modèle, clé."""
    cfg = config.load()
    first = preferred()
    provider = provider or first
    if provider not in PROVIDERS:
        provider = "autre"
    _, url, model, _ = PROVIDERS[provider]
    models = cfg.get("online_models") if isinstance(cfg.get("online_models"), dict) else {}
    key = _keys(cfg).get(provider, "")
    if provider == first:
        key = os.environ.get("REVISE_CLE_API") or key
    chosen_model = (cfg.get("online_model") if provider == first else "") or models.get(provider) or model
    return {
        "provider": provider,
        "url": ((cfg.get("online_url") if provider == "autre" else "") or url).rstrip("/"),
        "model": chosen_model if isinstance(chosen_model, str) else model,
        "key": "" if provider == KEYLESS else key,
    }


def keyless_allowed() -> bool:
    return config.load().get("online_keyless", True) is not False


def usable(conf: dict) -> bool:
    return bool(conf["url"] and conf["model"] and (conf["key"] or conf["provider"] == KEYLESS))


def has_key() -> bool:
    """Au moins un service avec une clé (le service sans clé ne compte pas)."""
    return any(usable(settings(p)) for p in PROVIDERS if p != KEYLESS)


def chain() -> list[dict]:
    """Services à essayer, dans l'ordre : celui choisi, les autres qui ont une clé, puis le service sans clé."""
    first = preferred()
    order = [first] + [p for p in FALLBACK_ORDER if p != first]
    out = [c for c in (settings(p) for p in order) if c["provider"] != KEYLESS and usable(c)]
    chosen = config.load().get("online_provider") == KEYLESS  # choisi exprès : essayé en premier
    if chosen or keyless_allowed():
        keyless = settings(KEYLESS)
        out.insert(0, keyless) if chosen else out.append(keyless)
    return out


def describe() -> str:
    """État de l'IA en ligne, en quelques mots, pour l'interface."""
    names = [PROVIDERS[c["provider"]][0] for c in chain() if c["provider"] != KEYLESS]
    if names:
        return "prête : " + ", ".join(names) + (" + sans clé" if keyless_allowed() else "")
    return "sans clé : marche, mais lent" if keyless_allowed() else "pas encore configurée"


class _ServiceFailed(ReviseError):
    """Ce service ne répond pas (quota, clé, modèle…) : on peut essayer le suivant."""


class OnlineEngine:
    name = "en-ligne"

    def __init__(self, post: Post = http_post, sleep: Callable[[float], None] = time.sleep, conf: dict | None = None,
                 get: Get = http_get, confs: list[dict] | None = None):
        self.post = post
        self.get = get
        self.sleep = sleep
        self.confs = [conf] if conf else confs if confs is not None else chain()
        self.index = 0
        self.replaced_model = False
        self.progress: Progress = lambda m: None

    @property
    def trap_batch(self) -> int:
        """Questions par demande de réponses pièges : le service sans clé n'écrit que des réponses courtes."""
        return KEYLESS_BATCH if self.conf["provider"] == KEYLESS else distractors.BATCH

    @property
    def conf(self) -> dict:
        return self.confs[self.index] if self.confs else settings()

    def _label(self, conf: dict | None = None) -> str:
        return PROVIDERS.get((conf or self.conf)["provider"], ("IA en ligne",))[0]

    def chat(self, system: str, user: str, schema: dict | None = None) -> str:
        """`schema` est ignoré : ces services garantissent du JSON, pas un schéma précis.
        Si un service ne répond pas (quota épuisé, clé refusée…), on essaie le suivant et on y reste."""
        errors: list[str] = []
        while True:
            try:
                return self._chat_one(system, user, last=self.index >= len(self.confs) - 1)
            except _ServiceFailed as e:
                errors.append(f"{self._label()} : {e}")
                if self.index >= len(self.confs) - 1:
                    raise ReviseError(errors[0] if len(errors) == 1 else
                                      "Aucun service d'IA en ligne n'a répondu.\n" + "\n".join(errors)) from e
                self.index += 1
                self.replaced_model = False
                self.progress(f"{errors[-1][:160]} — on passe à {self._label()}")

    def _chat_one(self, system: str, user: str, last: bool) -> str:
        c = self.conf
        payload = {
            "model": c["model"],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Content-Type": "application/json", "User-Agent": "revise"}
        if c["key"]:
            headers["Authorization"] = f"Bearer {c['key']}"
        keyless = c["provider"] == KEYLESS
        if keyless:  # modèle qui réfléchit avant de répondre, avec peu de place : sinon il n'a pas fini d'écrire
            payload["reasoning_effort"] = "low"
        tries = MAX_RETRIES if last or keyless else RETRIES_BEFORE_SWITCH
        for attempt in range(tries):
            payload["model"] = c["model"]
            try:
                data = self.post(c["url"] + "/chat/completions", headers, payload, TIMEOUT)
                return data["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                detail = _error_detail(e)
                busy = e.code in (429, 503) or (keyless and e.code == 402)
                if busy and re.search(r"limit:\s*0\b", detail):  # aucun quota : attendre ne sert à rien
                    raise _ServiceFailed(
                        f"ce service n'accorde aucune utilisation gratuite à ta clé pour le modèle « {c['model']} » "
                        f"(fréquent avec Gemini en Europe). Détail : {detail}") from e
                if busy and not keyless and not last and re.search(r"per day|daily|\bTPD\b|\bRPD\b|quota",
                                                                   detail, re.I):
                    raise _ServiceFailed(f"quota gratuit du jour épuisé. {detail[:200]}") from e
                if busy and attempt < tries - 1:
                    wait = _retry_after(e, detail, 15.0 * (attempt + 1))
                    self.progress(("service sans clé : une réponse toutes les 45 s environ, " if keyless else
                                   "limite du service atteinte, ") + f"nouvelle tentative dans {round(wait)} s…")
                    self.sleep(wait)
                    continue
                if busy:
                    raise _ServiceFailed(f"refuse toujours après plusieurs essais ({e.code}) : quota gratuit "
                                         f"épuisé ou service saturé. Réessaie plus tard, ajoute une autre clé dans "
                                         f"« Configurer… », ou utilise l'IA de cet ordinateur. Détail : {detail}") from e
                if e.code in (401, 402, 403):
                    raise _ServiceFailed(f"clé API refusée ({e.code}). Vérifie la clé. {detail}") from e
                if e.code == 400 and payload.get("reasoning_effort") != "low" and re.search(
                        r"token limit|max_tokens|reasoning effort", detail, re.I):
                    payload["reasoning_effort"] = "low"  # le modèle a trop réfléchi pour finir sa réponse
                    continue
                if e.code == 400 and "response_format" in payload and re.search(r"response_format|json", detail, re.I):
                    del payload["response_format"]  # modèle qui ne connaît pas le mode JSON : la consigne suffit
                    continue
                unknown = e.code == 404 or (e.code == 400 and re.search(
                    r"decommission|not found|does not exist|no longer|not supported|unknown model", detail, re.I))
                if unknown and not self.replaced_model and self._replace_model():
                    continue
                if unknown:
                    raise _ServiceFailed(f"modèle « {c['model']} » ou adresse inconnus du service : change le modèle "
                                         f"dans « Configurer… ». {detail}") from e
                raise _ServiceFailed(f"le service a répondu une erreur ({e.code}). {detail}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                raise _ServiceFailed(f"impossible de joindre le service ({c['url']}) : vérifie ta connexion. "
                                     f"Détail : {net.reason(e)}") from e
            except (KeyError, IndexError, TypeError, ValueError) as e:
                raise _ServiceFailed("réponse inattendue du service.") from e
        raise _ServiceFailed("le service est saturé : réessaie dans quelques minutes.")

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
        if c["provider"] == preferred():
            config.save({"online_model": model})
        else:
            models = config.load().get("online_models")
            config.save({"online_models": {**(models if isinstance(models, dict) else {}), c["provider"]: model}})
        return True

    def check(self) -> None:
        if not self.confs:
            raise ReviseError("Aucune clé API enregistrée et le service sans clé est désactivé : ajoute une clé "
                              "avec le bouton « Configurer… » de l'onglet « Ajouter un cours » (ou la commande "
                              "« revise cle »).")
        c = self.conf
        if not c["url"] or not c["model"]:
            raise ReviseError("Adresse ou modèle du service d'IA manquant dans les réglages de la clé API.")
        if not c["key"] and c["provider"] != KEYLESS:
            raise ReviseError("Aucune clé API enregistrée : ajoute-la avec le bouton « Configurer… » de l'onglet "
                              "« Ajouter un cours » (ou la commande « revise cle »).")

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        self.check()
        self.progress = progress
        label = "IA en ligne"
        title, cards = generate_cards(pdf, subject, progress, self.chat, label)
        distractors.add_to_drafts(cards, subject, self.chat, progress, label, self.trap_batch)
        return title, cards


def _retry_after(e: urllib.error.HTTPError, detail: str, default: float) -> float:
    """Attente demandée par le service (en-tête Retry-After, ou « retry after 32s » dans le message)."""
    m = re.search(r"retry after (\d+(?:\.\d+)?)\s*s", detail, re.I)
    try:
        wait = float(e.headers.get("Retry-After", "") if e.headers else "")
    except (TypeError, ValueError):
        wait = float(m.group(1)) + 1 if m else default
    return min(max(wait, 1.0), 120.0)


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
