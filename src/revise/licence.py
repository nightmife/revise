"""Clé de licence Payhip des versions empaquetées (revise.exe, revise.app).

Chaque achat sur Payhip donne une clé unique. L'application la vérifie une fois en ligne (API v2 « license »),
compte l'activation (`uses`), puis garde la clé dans les réglages avec l'empreinte de l'ordinateur : elle marche
ensuite hors ligne. Une clé s'active sur `MAX_MACHINES` ordinateur(s). Tous les `RECHECK_DAYS` jours, une
vérification en arrière-plan retire la licence d'un achat remboursé (Payhip désactive alors la clé) ; sans
Internet, rien ne change.

La clé secrète du produit Payhip n'est pas dans le dépôt : le build l'écrit dans `_licence_secret.py` (secret
GitHub `PAYHIP_SECRET`). Elle reste lisible dans l'exécutable par quelqu'un de motivé ; elle ne permet que de
manipuler une clé de licence qu'on connaît déjà (les clés des autres sont aléatoires).

Lancée depuis le code source, l'application ne demande rien (sauf `REVISE_LICENCE=1`, pour essayer)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from revise import config, net
from revise.models import ReviseError

try:
    from revise._licence_secret import SECRET   # écrit par le build, jamais commité
except ImportError:
    SECRET = ""

BUY_URL = "https://payhip.com/b/8XCQ2"   # page de vente Payhip, ex. « https://payhip.com/b/AbCd »
API = "https://payhip.com/api/v2/license/"
MAX_MACHINES = 1
RECHECK_DAYS = 14
SETTING = "licence"


class Unreachable(ReviseError):
    """Payhip injoignable (pas d'Internet, panne) : rien ne permet de dire si la clé est bonne ou non."""


def required() -> bool:
    if os.environ.get("REVISE_LICENCE") == "1":
        return True
    return bool(getattr(sys, "frozen", False)) and bool(SECRET)


def product_tag() -> str:
    """Repère du produit gardé avec la clé (changer de produit oblige à réactiver), sans le secret lui-même."""
    return hashlib.sha256(f"revise:{SECRET}".encode()).hexdigest()[:12]


def machine_id() -> str:
    """Empreinte stable de l'ordinateur (identifiant du système, haché : rien de lisible n'est gardé)."""
    raw = ""
    try:
        if os.name == "nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                raw = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        elif sys.platform == "darwin":
            out = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                 capture_output=True, text=True, timeout=10).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            raw = m.group(1) if m else ""
        else:
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                try:
                    with open(path, encoding="ascii") as f:
                        raw = f.read().strip()
                except OSError:
                    continue
                if raw:
                    break
    except Exception:
        raw = ""
    if not raw:
        raw = f"mac:{uuid.getnode():012x}"
    return hashlib.sha256(f"revise:{raw}".encode()).hexdigest()[:32]



def stored() -> dict | None:
    lic = config.load().get(SETTING)
    if not isinstance(lic, dict) or not isinstance(lic.get("key"), str) or not lic["key"]:
        return None
    return lic


def is_active() -> bool:
    lic = stored()
    return bool(lic and lic.get("product") == product_tag() and lic.get("machine") == machine_id())


def forget() -> None:
    config.save({SETTING: None})


def _call(action: str, key: str, opener) -> dict | None:
    """Appel à l'API ; le contenu de « data », None si Payhip ne connaît pas la clé (réponse vide)."""
    form = urllib.parse.urlencode({"license_key": key})
    headers = {"User-Agent": "revise", "product-secret-key": SECRET}
    if action == "verify":
        req = urllib.request.Request(f"{API}verify?{form}", headers=headers, method="GET")
    else:
        req = urllib.request.Request(API + action, data=form.encode(), method="PUT",
                                     headers={**headers, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=15) as resp:
            raw = resp.read(1 << 16)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        raise Unreachable(f"Payhip ne répond pas correctement (erreur {e.code}). Réessaie dans un moment.")
    except (OSError, ValueError) as e:  # URLError, délai dépassé, connexion coupée
        raise Unreachable(f"Impossible de joindre Payhip ({net.reason(e)}). Vérifie ta connexion à Internet.")
    if not raw.strip():
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Unreachable("Réponse illisible de Payhip. Réessaie dans un moment.")
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or data.get("license_key") != key:
        return None
    return data


def _uses(data: dict) -> int:
    uses = data.get("uses")
    return uses if isinstance(uses, int) and not isinstance(uses, bool) else 0


UNKNOWN = "Cette clé n'existe pas. Copie-la telle quelle depuis le mail de Payhip."
DISABLED = "Cette clé a été désactivée (achat remboursé ?) : elle ne marche plus."


def _too_many() -> str:
    where = "un autre ordinateur" if MAX_MACHINES == 1 else f"{MAX_MACHINES} ordinateurs"
    return (f"Cette clé est déjà activée sur {where}. Tu as changé d'ordinateur ou réinstallé ? "
            "Réponds au mail de ton achat pour la faire libérer.")


def activate(key: str, opener=net.urlopen, now=time.time) -> None:
    """Vérifie la clé, compte cet ordinateur et l'enregistre ; `ReviseError` (message à montrer) sinon."""
    key = key.strip()
    if not key:
        raise ReviseError("Colle ta clé de licence.")
    if not SECRET:
        raise ReviseError("Cette version n'est pas reliée à une page de vente (clé du produit absente).")
    lic = stored()
    if lic and lic.get("key") == key and is_active():
        return  # déjà activée ici : ne pas compter cet ordinateur deux fois
    data = _call("verify", key, opener)
    if data is None:
        raise ReviseError(UNKNOWN)
    if data.get("enabled") is not True:
        raise ReviseError(DISABLED)
    if _uses(data) >= MAX_MACHINES:
        raise ReviseError(_too_many())
    data = _call("usage", key, opener)
    if data is None:
        raise Unreachable("Payhip n'a pas pu enregistrer l'activation. Réessaie dans un moment.")
    if _uses(data) > MAX_MACHINES:  # activée ailleurs entre les deux appels : on rend l'activation
        try:
            _call("decrease", key, opener)
        except Unreachable:
            pass
        raise ReviseError(_too_many())
    config.save({SETTING: {"key": key, "product": product_tag(), "machine": machine_id(), "checked": now()}})


def due_key(now=time.time) -> str | None:
    """La clé à revérifier en ligne, None si ce n'est pas encore le moment."""
    lic = stored()
    if lic is None or not is_active():
        return None
    checked = lic.get("checked")
    if isinstance(checked, (int, float)) and 0 <= now() - checked < RECHECK_DAYS * 86400:
        return None
    return lic["key"]


def remote_status(key: str, opener=net.urlopen) -> str:
    """« ok », « revoked » (clé désactivée par Payhip, ex. remboursement) ou « unknown » (injoignable, réponse
    vide). Une réponse vide ne retire jamais la licence : seul « enabled: false » le fait. Peut tourner dans un fil."""
    try:
        data = _call("verify", key, opener)
    except Unreachable:
        return "unknown"
    if data is None:
        return "unknown"
    return "ok" if data.get("enabled") is True else "revoked"


def record(key: str, status: str, now=time.time) -> None:
    """Applique le résultat de `remote_status` (dans le fil de l'interface : seul à écrire les réglages)."""
    lic = stored()
    if not lic or lic.get("key") != key:
        return
    if status == "ok":
        config.save({SETTING: {**lic, "checked": now()}})
    elif status == "revoked":
        forget()
