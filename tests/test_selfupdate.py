"""Installation automatique des mises à jour : téléchargement vérifié et échange des fichiers, sans réseau."""

import hashlib
import io
import subprocess
from pathlib import Path

import pytest

from revise import selfupdate, updates
from revise.models import ReviseError

DATA = b"nouvelle version" * 1000


def asset(data: bytes = DATA, **changes) -> updates.Asset:
    values = {"url": updates.ASSET_PREFIX + "v9.0.0/revise.exe", "size": len(data),
              "sha256": hashlib.sha256(data).hexdigest()}
    values.update(changes)
    return updates.Asset(**values)


def serve(data: bytes = DATA):
    return lambda req, timeout: io.BytesIO(data)


class Runner:
    """Faux `subprocess.run` : note les commandes, imite hdiutil et ditto, échoue sur demande."""

    def __init__(self, fail: str = "", volume: Path | None = None):
        self.fail, self.volume, self.calls = fail, volume, []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        assert "_MEIPASS2" not in kwargs.get("env", {})
        if cmd[0] == "ditto":
            import shutil
            shutil.copytree(cmd[1], cmd[2])
        if cmd[:2] == ["hdiutil", "attach"] and self.volume is not None:   # « monte » l'image : copie son contenu
            import shutil
            shutil.copytree(self.volume, cmd[cmd.index("-mountpoint") + 1], dirs_exist_ok=True)
        if cmd[:2] == ["hdiutil", "detach"]:
            import shutil
            shutil.rmtree(cmd[2])
            Path(cmd[2]).mkdir()
        failed = self.fail and any(self.fail in part for part in cmd)
        return subprocess.CompletedProcess(cmd, 1 if failed else 0)


def test_download_checks_size_and_hash(tmp_path):
    dest = tmp_path / "f.exe"
    seen = []
    selfupdate.download(asset(), dest, lambda done, total: seen.append((done, total)), serve())
    assert dest.read_bytes() == DATA and seen[-1] == (len(DATA), len(DATA))
    for bad, opener in ((asset(sha256="0" * 64), serve()),                  # contenu différent de celui publié
                        (asset(sha256=None), serve()),                      # rien pour vérifier
                        (asset(), serve(DATA[:-5])),                        # coupé
                        (asset(), serve(DATA + b"x")),                      # plus gros que prévu
                        (asset(url="https://exemple.org/revise.exe"), serve()),
                        (asset(size=0), serve()),
                        (asset(), lambda req, timeout: (_ for _ in ()).throw(OSError("coupé")))):
        dest.unlink(missing_ok=True)
        with pytest.raises(ReviseError):
            selfupdate.download(bad, dest, opener=opener)
        assert not dest.exists()                                            # jamais de fichier douteux laissé
    with pytest.raises(ReviseError):
        selfupdate.download(asset(), dest, opener=serve(), cancelled=lambda: True)
    assert not dest.exists()


def test_child_env_forgets_the_running_executable(monkeypatch):
    monkeypatch.setenv("_MEIPASS2", "C:/tmp/_MEI123")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:/revise.exe")
    monkeypatch.setenv("REVISE_AUTRE", "gardé")
    env = selfupdate.child_env()
    assert "_MEIPASS2" not in env and "_PYI_ARCHIVE_FILE" not in env
    assert env["REVISE_AUTRE"] == "gardé" and env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_not_available_from_source():
    assert selfupdate.app_target() is None and not selfupdate.can_install()
    with pytest.raises(ReviseError):
        selfupdate.install(updates.Release("9.0.0"))
    selfupdate.cleanup_leftovers()                                          # sans effet, sans erreur


def test_windows_install_swaps_and_keeps_the_old_one(tmp_path, monkeypatch):
    current = tmp_path / "revise.exe"
    current.write_bytes(b"ancienne")
    monkeypatch.setattr(selfupdate, "app_target", lambda: ("windows", current))
    run = Runner()
    release = updates.Release("9.0.0", {"revise.exe": asset()})
    assert selfupdate.install(release, opener=serve(), run=run) == ("windows", current)
    assert current.read_bytes() == DATA
    assert (tmp_path / "revise-ancien.exe").read_bytes() == b"ancienne"
    assert run.calls == [[str(tmp_path / "revise-nouveau.exe"), "--selftest"]]   # essayée avant l'échange
    selfupdate.cleanup_leftovers()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["revise.exe"]


def test_windows_install_aborts_when_new_version_does_not_start(tmp_path, monkeypatch):
    current = tmp_path / "revise.exe"
    current.write_bytes(b"ancienne")
    monkeypatch.setattr(selfupdate, "app_target", lambda: ("windows", current))
    release = updates.Release("9.0.0", {"revise.exe": asset()})
    with pytest.raises(ReviseError, match="ne démarre pas"):
        selfupdate.install(release, opener=serve(), run=Runner(fail="--selftest"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["revise.exe"] and current.read_bytes() == b"ancienne"
    with pytest.raises(ReviseError):                                        # pas de fichier pour cet ordinateur
        selfupdate.install(updates.Release("9.0.0"), opener=serve(), run=Runner())
    with pytest.raises(ReviseError):                                        # empreinte fausse : rien n'est lancé
        run = Runner()
        selfupdate.install(updates.Release("9.0.0", {"revise.exe": asset(sha256="1" * 64)}), opener=serve(), run=run)
    assert run.calls == [] and current.read_bytes() == b"ancienne"


def make_app(root: Path, content: bytes) -> Path:
    exe = root / "revise.app" / "Contents" / "MacOS" / "revise"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(content)
    return root / "revise.app"


def test_mac_install(tmp_path, monkeypatch):
    apps, volume = tmp_path / "Applications", tmp_path / "volume"
    apps.mkdir()
    volume.mkdir()
    bundle = make_app(apps, b"ancienne")
    make_app(volume, b"nouvelle")
    monkeypatch.setattr(selfupdate, "app_target", lambda: ("mac", bundle))
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "arm64")
    name = "revise-mac-arm64.dmg"
    assert selfupdate.asset_name("mac") == name
    release = updates.Release("9.0.0", {name: asset(url=updates.ASSET_PREFIX + "v9.0.0/" + name)})
    run = Runner(volume=volume)
    assert selfupdate.install(release, opener=serve(), run=run) == ("mac", bundle)
    assert (bundle / "Contents" / "MacOS" / "revise").read_bytes() == b"nouvelle"
    assert (apps / "revise.app.ancien" / "Contents" / "MacOS" / "revise").read_bytes() == b"ancienne"
    assert [c[0] for c in run.calls] == ["hdiutil", str(Path(run.calls[0][-2]) / "revise.app/Contents/MacOS/revise"),
                                         "ditto", "hdiutil"]
    selfupdate.cleanup_leftovers()
    assert sorted(p.name for p in apps.iterdir()) == ["revise.app"]

    for fail in ("attach", "--selftest", "ditto"):                          # un échec à n'importe quelle étape
        with pytest.raises(ReviseError):
            selfupdate.install(release, opener=serve(), run=Runner(fail=fail, volume=volume))
        assert sorted(p.name for p in apps.iterdir()) == ["revise.app"]
        assert (bundle / "Contents" / "MacOS" / "revise").read_bytes() == b"nouvelle"
    with pytest.raises(ReviseError, match="Applications"):
        selfupdate.install_mac(tmp_path / "x.dmg", Path("/private/var/folders/x/AppTranslocation/y/d/revise.app"))


def test_relaunch_commands(tmp_path):
    calls = []
    selfupdate.relaunch("mac", tmp_path / "revise.app", popen=lambda cmd, **kw: calls.append(cmd))
    selfupdate.relaunch("windows", tmp_path / "revise.exe", popen=lambda cmd, **kw: calls.append(cmd))
    assert calls == [["open", "-n", str(tmp_path / "revise.app")], [str(tmp_path / "revise.exe")]]
