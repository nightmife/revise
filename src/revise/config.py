"""Réglages de l'utilisateur (fichier JSON) et dossier de données de l'application."""

from __future__ import annotations

import json
import os
from pathlib import Path


def data_dir() -> Path:
    """Dossier des données lourdes (base, moteur d'IA, modèle)."""
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "revise"


def config_path() -> Path:
    if env := os.environ.get("REVISE_CONFIG"):
        return Path(env)
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "revise" / "config.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "revise" / "config.json"


def load() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(values: dict) -> None:
    """Fusionne `values` dans le fichier de réglages (lisible par l'utilisateur seulement)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load()
    data.update(values)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
