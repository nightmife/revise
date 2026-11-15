"""Vérifie s'il existe une version plus récente de l'application (dernière Release du dépôt GitHub).

Une seule requête, anonyme, sans rien envoyer sur l'utilisateur. Toute erreur (pas d'Internet, service
indisponible, réponse inattendue) est ignorée : on répond simplement « rien de nouveau »."""

from __future__ import annotations

import json
import re
import urllib.request

from revise import __version__, config, net

LATEST_API = "https://api.github.com/repos/nightmife/revise/releases/latest"
DOWNLOAD_PAGE = "https://github.com/nightmife/revise/releases/latest"


def parse_version(text: str) -> tuple[int, ...] | None:
    """« v0.4.3 » → (0, 4, 3) ; None si ce n'est pas un numéro de version."""
    m = re.fullmatch(r"\s*v?(\d+(?:\.\d+)*)\s*", text or "")
    if not m:
        return None
    parts = [int(x) for x in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:  # 0.5 et 0.5.0 sont la même version
        parts.pop()
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def enabled() -> bool:
    return config.load().get("check_updates", True) is not False


def latest_version(opener=net.urlopen) -> str | None:
    """Numéro de la dernière version publiée (« 0.5.0 »), None si on ne peut pas le savoir."""
    req = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "revise"})
    try:
        with opener(req, timeout=8) as resp:
            data = json.loads(resp.read(1 << 20).decode("utf-8"))
    except Exception:  # réseau, HTTP, JSON : jamais bloquant
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    if not isinstance(tag, str) or parse_version(tag) is None:
        return None
    return tag.strip().lstrip("v")


def available_update(opener=net.urlopen) -> str | None:
    """La version à proposer, None s'il n'y a rien de plus récent (ou si la vérification est coupée)."""
    if not enabled():
        return None
    latest = latest_version(opener)
    return latest if latest and is_newer(latest) else None
