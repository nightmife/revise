"""Clé de licence Payhip, sans réseau (faux `opener`)."""

import io
import json
import os
import time
import urllib.error
import urllib.parse

import pytest

from revise import config, licence
from revise.models import ReviseError

KEY = "WTKP4-66NL5-HMKQW-GFSCZ"


@pytest.fixture(autouse=True)
def product(monkeypatch):
    monkeypatch.setattr(licence, "SECRET", "secret123")
    monkeypatch.delenv("REVISE_LICENCE", raising=False)


class Payhip:
    """Faux Payhip : une clé connue, un compteur d'activations, un état (activée / désactivée)."""

    def __init__(self, uses=0, enabled=True, down=False, race=0):
        self.uses, self.enabled, self.down, self.race = uses, enabled, down, race
        self.calls = []

    def __call__(self, req, timeout):
        if self.down:
            raise urllib.error.URLError("pas de réseau")
        assert req.get_header("Product-secret-key") == "secret123"
        action = req.full_url.split("?")[0].rsplit("/", 1)[1]
        if action == "verify":
            assert req.get_method() == "GET" and req.data is None
            key = dict(urllib.parse.parse_qsl(req.full_url.split("?", 1)[1]))["license_key"]
        else:
            assert req.get_method() == "PUT"
            key = dict(urllib.parse.parse_qsl(req.data.decode()))["license_key"]
        self.calls.append(action)
        if key != KEY:
            return io.BytesIO(b"")                       # « réponse vide » si la vérification échoue
        if action == "usage":
            self.uses += 1 + self.race
        elif action == "decrease":
            self.uses -= 1
        return io.BytesIO(json.dumps({"data": {"enabled": self.enabled, "product_link": "AbCd",
                                               "license_key": KEY, "buyer_email": "x@example.org",
                                               "uses": self.uses, "date": "2026-11-18T10:00:00+00:00"}}).encode())


def test_required_only_for_packaged_app(monkeypatch):
    assert not licence.required()                 # lancée depuis le code source
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert licence.required()
    monkeypatch.setattr(licence, "SECRET", "")
    assert not licence.required()                 # pas encore reliée à Gumroad
    monkeypatch.setenv("REVISE_LICENCE", "1")
    assert licence.required()


def test_machine_id_is_stable_and_hashed():
    assert licence.machine_id() == licence.machine_id()
    assert len(licence.machine_id()) == 32


def test_activate_counts_one_machine_and_saves():
    g = Payhip()
    licence.activate(f"  {KEY}\n", opener=g)
    assert licence.is_active()
    assert g.uses == 1
    assert g.calls == ["verify", "usage"]
    licence.activate(KEY, opener=g)               # même ordinateur : pas compté deux fois
    assert g.uses == 1


def test_unknown_key_is_refused_without_saving():
    with pytest.raises(ReviseError, match="n'existe pas"):
        licence.activate("FAUSSE", opener=Payhip())
    assert not licence.is_active()


def test_empty_key():
    with pytest.raises(ReviseError, match="Colle"):
        licence.activate("   ", opener=Payhip())


def test_disabled_key_is_refused():
    with pytest.raises(ReviseError, match="désactivée"):
        licence.activate(KEY, opener=Payhip(enabled=False))
    assert not licence.is_active()


def test_too_many_machines_does_not_use_the_key():
    g = Payhip(uses=licence.MAX_MACHINES)
    with pytest.raises(ReviseError, match="déjà activée"):
        licence.activate(KEY, opener=g)
    assert g.uses == licence.MAX_MACHINES and len(g.calls) == 1
    assert not licence.is_active()


def test_offline_activation_explains():
    with pytest.raises(licence.Unreachable, match="connexion"):
        licence.activate(KEY, opener=Payhip(down=True))
    assert not licence.is_active()


def test_server_error_is_not_taken_for_a_bad_key():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "Erreur", {}, io.BytesIO(b"oups"))
    assert licence.remote_status(KEY, opener) == "unknown"


def test_licence_copied_to_another_computer_is_not_active(monkeypatch):
    licence.activate(KEY, opener=Payhip())
    monkeypatch.setattr(licence, "machine_id", lambda: "autre-ordinateur")
    assert not licence.is_active()


def test_licence_of_another_product_is_not_active(monkeypatch):
    licence.activate(KEY, opener=Payhip())
    monkeypatch.setattr(licence, "SECRET", "autre")
    assert not licence.is_active()


def test_recheck_schedule_and_results():
    now = time.time()
    licence.activate(KEY, opener=Payhip(), now=lambda: now)
    assert licence.due_key(now=lambda: now + 86400) is None
    later = now + (licence.RECHECK_DAYS + 1) * 86400
    assert licence.due_key(now=lambda: later) == KEY

    assert licence.remote_status(KEY, Payhip(down=True)) == "unknown"
    licence.record(KEY, "unknown", now=lambda: later)
    assert licence.is_active() and licence.due_key(now=lambda: later) == KEY   # hors ligne : rien ne change

    assert licence.remote_status(KEY, Payhip()) == "ok"
    licence.record(KEY, "ok", now=lambda: later)
    assert licence.due_key(now=lambda: later) is None

    assert licence.remote_status(KEY, Payhip(enabled=False)) == "revoked"
    licence.record(KEY, "revoked")
    assert not licence.is_active()


def test_activation_race_gives_the_use_back():
    g = Payhip(race=1)                                # activée ailleurs entre la vérification et le comptage
    with pytest.raises(ReviseError, match="déjà activée"):
        licence.activate(KEY, opener=g)
    assert g.calls == ["verify", "usage", "decrease"] and g.uses == 1
    assert not licence.is_active()


def test_wrong_product_secret_is_not_a_bad_key():
    def opener(req, timeout):
        body = b'{"code":"authentication_fail","message":"failed to authenticate","success":false}'
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(body))
    with pytest.raises(licence.Unreachable, match="erreur 401"):
        licence.activate(KEY, opener=opener)
    assert licence.remote_status(KEY, opener) == "unknown"


def test_empty_answer_never_revokes():
    licence.activate(KEY, opener=Payhip())
    assert licence.remote_status(KEY, lambda req, timeout: io.BytesIO(b"")) == "unknown"


def test_record_ignores_a_key_replaced_meanwhile():
    licence.activate(KEY, opener=Payhip())
    licence.record("ANCIENNE", "revoked")
    assert licence.is_active()


def test_garbage_settings_are_ignored():
    config.save({licence.SETTING: "n'importe quoi"})
    assert licence.stored() is None and not licence.is_active() and licence.due_key() is None


def test_dialog_activates(qapp):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from revise.gui.licence_dialog import LicenceDialog

    seen = []
    dlg = LicenceDialog(activator=seen.append)
    dlg.key.setText(KEY)
    dlg.start()
    for _ in range(200):
        qapp.processEvents()
        if dlg.result() == dlg.DialogCode.Accepted:
            break
        time.sleep(0.01)
    assert seen == [KEY] and dlg.result() == dlg.DialogCode.Accepted


def test_dialog_shows_error_and_allows_retry(qapp):
    from revise.gui.licence_dialog import LicenceDialog

    def refuse(key):
        raise ReviseError("Cette clé n'existe pas.")
    dlg = LicenceDialog(activator=refuse)
    dlg.key.setText("x")
    dlg.start()
    for _ in range(200):
        qapp.processEvents()
        if dlg.ok_btn.isEnabled():
            break
        time.sleep(0.01)
    assert dlg.ok_btn.isEnabled() and "n'existe pas" in dlg.status.text()
    assert dlg.result() != dlg.DialogCode.Accepted


def test_ensure_licence_skips_dialog_when_not_required():
    from revise.gui.licence_dialog import ensure_licence
    assert ensure_licence()
