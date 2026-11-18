"""Clé de licence Gumroad des versions empaquetées (revise.exe, revise.app).

Chaque achat sur Gumroad donne une clé unique. L'application la vérifie une fois en ligne (API publique
`licenses/verify`, sans compte ni secret), puis la garde dans les réglages avec l'empreinte de l'ordinateur :
elle marche ensuite hors ligne. Une clé s'active sur `MAX_MACHINES` ordinateurs au plus (compteur `uses` de
Gumroad). Tous les `RECHECK_DAYS` jours, une vérification en arrière-plan retire la licence d'un achat
remboursé ou contesté ; sans Internet, rien ne change.

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

# À remplir une fois le produit créé sur Gumroad (voir README, « Vente sur Gumroad »).
PRODUCT_ID = "w66guSGB6bEETnGkV5J2fg=="   # produit → Content → License key → product_id
BUY_URL = "https://dylanbonn.gumroad.com/l/revise"      # page de vente, ex. « https://xxx.gumroad.com/l/revise »

VERIFY_URL = "https://api.gumroad.com/v2/licenses/verify"
MAX_MACHINES = 1
RECHECK_DAYS = 14
SETTING = "licence"


class Unreachable(ReviseError):
    """Gumroad injoignable (pas d'Internet, panne) : rien ne permet de dire si la clé est bonne ou non."""


def required() -> bool:
    if os.environ.get("REVISE_LICENCE") == "1":
        return True
    return bool(getattr(sys, "frozen", False)) and bool(PRODUCT_ID)


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
    return bool(lic and lic.get("product") == PRODUCT_ID and lic.get("machine") == machine_id())


def forget() -> None:
    config.save({SETTING: None})


def _call(key: str, increment: bool, opener) -> dict:
    body = urllib.parse.urlencode({"product_id": PRODUCT_ID, "license_key": key,
                                   "increment_uses_count": "true" if increment else "false"}).encode()
    req = urllib.request.Request(VERIFY_URL, data=body, method="POST",
                                 headers={"User-Agent": "revise",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=15) as resp:
            raw = resp.read(1 << 16)
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404):   # clé inconnue : 404 avec {"success": false, …}
            raise Unreachable(f"Gumroad ne répond pas correctement (erreur {e.code}). Réessaie dans un moment.")
        raw = e.read(1 << 16)
    except (OSError, ValueError) as e:  # URLError, délai dépassé, connexion coupée
        raise Unreachable(f"Impossible de joindre Gumroad ({net.reason(e)}). Vérifie ta connexion à Internet.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Unreachable("Réponse illisible de Gumroad. Réessaie dans un moment.")
    if not isinstance(data, dict):
        raise Unreachable("Réponse inattendue de Gumroad. Réessaie dans un moment.")
    return data


def _problem(data: dict) -> str | None:
    """Pourquoi la clé ne vaut rien, None si elle est bonne."""
    if data.get("success") is not True:
        return "Cette clé n'existe pas. Copie-la telle quelle depuis le mail de Gumroad."
    purchase = data.get("purchase")
    purchase = purchase if isinstance(purchase, dict) else {}
    if any(purchase.get(k) is True for k in ("refunded", "chargebacked", "disputed")):
        return "Cet achat a été remboursé ou contesté : la clé ne marche plus."
    return None


def _uses(data: dict) -> int:
    uses = data.get("uses")
    return uses if isinstance(uses, int) and not isinstance(uses, bool) else 0


def _too_many() -> str:
    where = "un autre ordinateur" if MAX_MACHINES == 1 else f"{MAX_MACHINES} ordinateurs"
    return (f"Cette clé est déjà activée sur {where}. Tu as changé d'ordinateur ou réinstallé ? "
            "Contacte le vendeur depuis ta page d'achat Gumroad pour la libérer.")


def activate(key: str, opener=net.urlopen, now=time.time) -> None:
    """Vérifie la clé et l'enregistre pour cet ordinateur ; `ReviseError` (message à montrer) sinon."""
    key = key.strip()
    if not key:
        raise ReviseError("Colle ta clé de licence.")
    if not PRODUCT_ID:
        raise ReviseError("Cette version n'est pas reliée à une page de vente (PRODUCT_ID vide).")
    lic = stored()
    if lic and lic.get("key") == key and lic.get("product") == PRODUCT_ID and lic.get("machine") == machine_id():
        return  # déjà activée ici : ne pas compter cet ordinateur deux fois
    data = _call(key, False, opener)  # d'abord sans compter, pour ne pas user la clé sur un refus
    if problem := _problem(data):
        raise ReviseError(problem)
    if _uses(data) >= MAX_MACHINES:
        raise ReviseError(_too_many())
    data = _call(key, True, opener)
    if problem := _problem(data):
        raise ReviseError(problem)
    if _uses(data) > MAX_MACHINES:  # activée ailleurs entre les deux appels
        raise ReviseError(_too_many())
    config.save({SETTING: {"key": key, "product": PRODUCT_ID, "machine": machine_id(), "checked": now()}})


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
    """« ok », « revoked » (remboursée, contestée, supprimée) ou « unknown » (Gumroad injoignable).
    Ne touche pas aux réglages : peut tourner dans un fil."""
    try:
        data = _call(key, False, opener)
    except Unreachable:
        return "unknown"
    return "revoked" if _problem(data) else "ok"


def record(key: str, status: str, now=time.time) -> None:
    """Applique le résultat de `remote_status` (dans le fil de l'interface : seul à écrire les réglages)."""
    lic = stored()
    if not lic or lic.get("key") != key:
        return
    if status == "ok":
        config.save({SETTING: {**lic, "checked": now()}})
    elif status == "revoked":
        forget()
