"""Vérification des mises à jour, sans réseau (faux `opener`)."""

import io
import json
import urllib.error

import pytest

from revise import __version__, config, updates


def fake(payload, seen=None):
    def opener(req, timeout):
        if seen is not None:
            seen.append(req)
        if isinstance(payload, Exception):
            raise payload
        return io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    return opener


@pytest.mark.parametrize("text,expected", [("v0.4.3", (0, 4, 3)), ("0.5", (0, 5)), ("0.5.0", (0, 5)), (" v1.0.0 ", (1,)),
                                           ("v1.2-beta", None), ("", None), ("latest", None)])
def test_parse_version(text, expected):
    assert updates.parse_version(text) == expected


def test_is_newer():
    assert updates.is_newer("0.10.0", "0.9.9")       # comparaison de nombres, pas de textes
    assert updates.is_newer("v1.0", "0.9")
    assert not updates.is_newer("0.5.0", "0.5")
    assert not updates.is_newer("0.4.9", "0.5.0")
    assert not updates.is_newer("n'importe quoi", "0.5.0")
    assert not updates.is_newer(__version__)


def test_update_found_and_request_is_anonymous():
    seen = []
    release = updates.available_update(fake({"tag_name": "v99.0.1", "assets": [
        {"name": "revise.exe", "size": 10, "digest": "sha256:" + "a" * 64,
         "browser_download_url": updates.ASSET_PREFIX + "v99.0.1/revise.exe"},
        {"name": "sans-empreinte.dmg", "size": 5, "browser_download_url": updates.ASSET_PREFIX + "v99.0.1/x.dmg"},
        {"name": "ailleurs.exe", "size": 10, "browser_download_url": "https://exemple.org/revise.exe"},
        {"name": "vide.exe", "size": 0, "browser_download_url": updates.ASSET_PREFIX + "v99.0.1/vide.exe"},
        "n'importe quoi"]}, seen))
    assert release.version == "99.0.1"
    assert sorted(release.assets) == ["revise.exe", "sans-empreinte.dmg"]     # jamais un fichier venu d'ailleurs
    assert release.assets["revise.exe"] == updates.Asset(updates.ASSET_PREFIX + "v99.0.1/revise.exe", 10, "a" * 64)
    assert release.assets["sans-empreinte.dmg"].sha256 is None
    [req] = seen
    assert req.full_url == updates.LATEST_API and req.get_header("User-agent") == "revise"
    assert req.data is None


@pytest.mark.parametrize("payload", [
    {"tag_name": f"v{__version__}"}, {"tag_name": "v0.0.1"}, {"tag_name": "nightly"}, {"tag_name": 5}, {}, [], b"<html>",
    urllib.error.URLError("pas d'Internet"), TimeoutError(), OSError("coupé")])
def test_no_update_and_errors_are_silent(payload):
    assert updates.available_update(fake(payload)) is None


def test_check_can_be_disabled():
    config.save({"check_updates": False})
    seen = []
    assert updates.available_update(fake({"tag_name": "v99.0"}, seen)) is None
    assert seen == []                                # aucune connexion
