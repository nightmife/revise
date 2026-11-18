"""Clé de licence Gumroad, sans réseau (faux `opener`)."""

import io
import json
import os
import time
import urllib.error
import urllib.parse

import pytest

from revise import config, licence
from revise.models import ReviseError

KEY = "AAAA1111-BBBB2222-CCCC3333-DDDD4444"


@pytest.fixture(autouse=True)
def product(monkeypatch):
    monkeypatch.setattr(licence, "PRODUCT_ID", "prod123")
    monkeypatch.delenv("REVISE_LICENCE", raising=False)


class Gumroad:
    """Faux Gumroad : une clé connue, un compteur d'activations, un état d'achat."""

    def __init__(self, uses=0, refunded=False, down=False):
        self.uses, self.refunded, self.down = uses, refunded, down
        self.calls = []

    def __call__(self, req, timeout):
        if self.down:
            raise urllib.error.URLError("pas de réseau")
        form = dict(urllib.parse.parse_qsl(req.data.decode()))
        self.calls.append(form)
        assert req.full_url == licence.VERIFY_URL and form["product_id"] == "prod123"
        if form["license_key"] != KEY:
            body = json.dumps({"success": False, "message": "That license does not exist"}).encode()
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(body))
        if form["increment_uses_count"] == "true":
            self.uses += 1
        return io.BytesIO(json.dumps({"success": True, "uses": self.uses,
                                      "purchase": {"refunded": self.refunded, "chargebacked": False}}).encode())


def test_required_only_for_packaged_app(monkeypatch):
    assert not licence.required()                 # lancée depuis le code source
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert licence.required()
    monkeypatch.setattr(licence, "PRODUCT_ID", "")
    assert not licence.required()                 # pas encore reliée à Gumroad
    monkeypatch.setenv("REVISE_LICENCE", "1")
    assert licence.required()


def test_machine_id_is_stable_and_hashed():
    assert licence.machine_id() == licence.machine_id()
    assert len(licence.machine_id()) == 32


def test_activate_counts_one_machine_and_saves():
    g = Gumroad()
    licence.activate(f"  {KEY}\n", opener=g)
    assert licence.is_active()
    assert g.uses == 1
    assert [c["increment_uses_count"] for c in g.calls] == ["false", "true"]
    licence.activate(KEY, opener=g)               # même ordinateur : pas compté deux fois
    assert g.uses == 1


def test_unknown_key_is_refused_without_saving():
    with pytest.raises(ReviseError, match="n'existe pas"):
        licence.activate("FAUSSE", opener=Gumroad())
    assert not licence.is_active()


def test_empty_key():
    with pytest.raises(ReviseError, match="Colle"):
        licence.activate("   ", opener=Gumroad())


def test_refunded_purchase_is_refused():
    with pytest.raises(ReviseError, match="remboursé"):
        licence.activate(KEY, opener=Gumroad(refunded=True))
    assert not licence.is_active()


def test_too_many_machines_does_not_use_the_key():
    g = Gumroad(uses=licence.MAX_MACHINES)
    with pytest.raises(ReviseError, match="déjà activée"):
        licence.activate(KEY, opener=g)
    assert g.uses == licence.MAX_MACHINES and len(g.calls) == 1
    assert not licence.is_active()


def test_offline_activation_explains():
    with pytest.raises(licence.Unreachable, match="connexion"):
        licence.activate(KEY, opener=Gumroad(down=True))
    assert not licence.is_active()


def test_server_error_is_not_taken_for_a_bad_key():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "Erreur", {}, io.BytesIO(b"oups"))
    assert licence.remote_status(KEY, opener) == "unknown"


def test_licence_copied_to_another_computer_is_not_active(monkeypatch):
    licence.activate(KEY, opener=Gumroad())
    monkeypatch.setattr(licence, "machine_id", lambda: "autre-ordinateur")
    assert not licence.is_active()


def test_licence_of_another_product_is_not_active(monkeypatch):
    licence.activate(KEY, opener=Gumroad())
    monkeypatch.setattr(licence, "PRODUCT_ID", "autre")
    assert not licence.is_active()


def test_recheck_schedule_and_results():
    now = time.time()
    licence.activate(KEY, opener=Gumroad(), now=lambda: now)
    assert licence.due_key(now=lambda: now + 86400) is None
    later = now + (licence.RECHECK_DAYS + 1) * 86400
    assert licence.due_key(now=lambda: later) == KEY

    assert licence.remote_status(KEY, Gumroad(down=True)) == "unknown"
    licence.record(KEY, "unknown", now=lambda: later)
    assert licence.is_active() and licence.due_key(now=lambda: later) == KEY   # hors ligne : rien ne change

    assert licence.remote_status(KEY, Gumroad()) == "ok"
    licence.record(KEY, "ok", now=lambda: later)
    assert licence.due_key(now=lambda: later) is None

    assert licence.remote_status(KEY, Gumroad(refunded=True)) == "revoked"
    licence.record(KEY, "revoked")
    assert not licence.is_active()


def test_record_ignores_a_key_replaced_meanwhile():
    licence.activate(KEY, opener=Gumroad())
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
