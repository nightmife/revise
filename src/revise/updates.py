"""Vérifie s'il existe une version plus récente de l'application (dernière Release du dépôt GitHub).

Une seule requête, anonyme, sans rien envoyer sur l'utilisateur. Toute erreur (pas d'Internet, service
indisponible, réponse inattendue) est ignorée : on répond simplement « rien de nouveau »."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field

from revise import __version__, config, net

LATEST_API = "https://api.github.com/repos/nightmife/revise/releases/latest"
DOWNLOAD_PAGE = "https://github.com/nightmife/revise/releases/latest"
ASSET_PREFIX = "https://github.com/nightmife/revise/releases/download/"  # seul endroit d'où l'on télécharge


@dataclass
class Asset:
    url: str
    size: int
    sha256: str | None  # empreinte publiée par GitHub ; None si elle manque


@dataclass
class Release:
    version: str  # « 0.6.0 »
    assets: dict[str, Asset] = field(default_factory=dict)  # nom du fichier → où le prendre


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


def _assets(raw) -> dict[str, Asset]:
    out = {}
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict):
            continue
        name, url, size, digest = a.get("name"), a.get("browser_download_url"), a.get("size"), a.get("digest")
        if not (isinstance(name, str) and isinstance(url, str) and url.startswith(ASSET_PREFIX)):
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            continue
        m = re.fullmatch(r"sha256:([0-9a-f]{64})", digest) if isinstance(digest, str) else None
        out[name] = Asset(url, size, m.group(1) if m else None)
    return out


def latest_release(opener=net.urlopen) -> Release | None:
    """Dernière version publiée et ses fichiers, None si on ne peut pas le savoir."""
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
    return Release(tag.strip().lstrip("v"), _assets(data.get("assets")))


def latest_version(opener=net.urlopen) -> str | None:
    release = latest_release(opener)
    return release.version if release else None


def available_update(opener=net.urlopen) -> Release | None:
    """La version à proposer, None s'il n'y a rien de plus récent (ou si la vérification est coupée)."""
    if not enabled():
        return None
    latest = latest_release(opener)
    return latest if latest and is_newer(latest.version) else None
