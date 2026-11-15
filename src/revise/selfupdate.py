"""Installation automatique d'une mise à jour, pour les applications empaquetées (revise.exe, revise.app).

Déroulement : télécharger le fichier de la Release, vérifier son empreinte, vérifier que la nouvelle
application démarre (`--selftest`), puis seulement échanger l'ancienne et la nouvelle. L'ancienne est gardée
à côté jusqu'au lancement suivant ; au moindre échec avant l'échange, rien n'a changé."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from revise import net
from revise.models import ReviseError
from revise.updates import ASSET_PREFIX, Asset, Release

MAX_BYTES = 600 * 1024 * 1024
SELFTEST_TIMEOUT = 240
OLD, NEW = "ancien", "nouveau"

DownloadProgress = Callable[[int, int], None]  # octets reçus, octets attendus


def app_target() -> tuple[str, Path] | None:
    """Ce qu'il faut remplacer : ("windows", …/revise.exe) ou ("mac", …/revise.app).
    None si l'application n'est pas empaquetée (lancée depuis le code source, Linux)."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if os.name == "nt":
        return "windows", exe
    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return "mac", parent
    return None


def can_install() -> bool:
    return app_target() is not None


def asset_name(kind: str) -> str:
    if kind == "windows":
        return "revise.exe"
    return f"revise-mac-{'arm64' if platform.machine() == 'arm64' else 'intel'}.dmg"


def sibling(target: Path, tag: str) -> Path:
    """revise.exe → revise-ancien.exe ; revise.app → revise.app.ancien (même dossier, donc même disque)."""
    if target.suffix == ".exe":
        return target.with_name(f"{target.stem}-{tag}.exe")
    return target.with_name(f"{target.name}.{tag}")


def child_env() -> dict[str, str]:
    """Environnement d'une autre copie de l'application : sans les variables que l'exécutable en cours
    a posées pour lui-même (sinon la nouvelle copie se croit lancée par l'ancienne et en reprend les fichiers)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI_", "_MEIPASS"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def cleanup_leftovers(target: Path | None = None) -> None:
    """Supprime l'ancienne version laissée par la dernière mise à jour (et un téléchargement abandonné)."""
    if target is None:
        found = app_target()
        if found is None:
            return
        target = found[1]
    for tag in (OLD, NEW):
        try:
            _remove(sibling(target, tag))
        except OSError:  # encore en cours d'arrêt : ce sera pour le prochain lancement
            pass


# ------------------------------------------------------------ téléchargement ---

def download(asset: Asset, dest: Path, progress: DownloadProgress = lambda done, total: None,
             opener=net.urlopen, cancelled: Callable[[], bool] = lambda: False) -> None:
    """Télécharge `asset` dans `dest` et vérifie sa taille et son empreinte SHA-256."""
    if not asset.url.startswith(ASSET_PREFIX):
        raise ReviseError("Adresse de téléchargement inattendue.")
    if not asset.sha256:
        raise ReviseError("Cette version ne peut pas être vérifiée automatiquement (empreinte absente).")
    if not 0 < asset.size <= MAX_BYTES:
        raise ReviseError("Taille de la mise à jour inattendue.")
    digest = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(asset.url, headers={"User-Agent": "revise"})
        with opener(req, timeout=60) as resp, open(dest, "wb") as out:
            while chunk := resp.read(1 << 18):
                if cancelled():
                    raise ReviseError("Mise à jour annulée.")
                done += len(chunk)
                if done > asset.size:
                    raise ReviseError("Le fichier reçu est plus gros que prévu.")
                digest.update(chunk)
                out.write(chunk)
                progress(done, asset.size)
        if done != asset.size:
            raise ReviseError("Téléchargement incomplet : vérifie ta connexion et réessaie.")
        if digest.hexdigest() != asset.sha256:
            raise ReviseError("Le fichier téléchargé ne correspond pas à celui publié : mise à jour annulée.")
    except ReviseError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:  # réseau, disque plein, dossier protégé…
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise ReviseError(f"Téléchargement impossible ({net.reason(e)}).") from e


# ---------------------------------------------------------------- échange ---

def _run(run, cmd: list[str], what: str, timeout: float = 300) -> None:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = run(cmd, env=child_env(), capture_output=True, timeout=timeout, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as e:
        raise ReviseError(f"{what} : {e}") from e
    if proc.returncode != 0:
        raise ReviseError(f"{what} (code {proc.returncode}).")


def _swap(new: Path, target: Path) -> None:
    """Met `new` à la place de `target` ; l'ancien est gardé à côté. Tout ou rien."""
    old = sibling(target, OLD)
    try:
        _remove(old)
        os.rename(target, old)  # permis même pour l'exécutable en cours (Windows) ou l'appli ouverte (Mac)
    except OSError as e:
        raise ReviseError(f"Impossible de remplacer l'application ({e.strerror or e}).") from e
    try:
        os.rename(new, target)
    except OSError as e:
        os.rename(old, target)  # on remet l'ancienne en place
        raise ReviseError(f"Impossible d'installer la nouvelle version ({e.strerror or e}).") from e


def install_windows(new_exe: Path, current: Path, run=subprocess.run) -> None:
    try:
        _run(run, [str(new_exe), "--selftest"], "La nouvelle version ne démarre pas", SELFTEST_TIMEOUT)
        _swap(new_exe, current)
    except ReviseError:
        new_exe.unlink(missing_ok=True)
        raise


def install_mac(dmg: Path, bundle: Path, run=subprocess.run) -> None:
    if "AppTranslocation" in bundle.parts:
        raise ReviseError("Glisse d'abord revise dans le dossier Applications, puis relance-le depuis là.")
    new = sibling(bundle, NEW)
    mount = Path(tempfile.mkdtemp(prefix="revise-maj-"))
    try:
        _run(run, ["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mount), str(dmg)],
             "Impossible d'ouvrir la mise à jour")
        try:
            source = mount / "revise.app"
            if not (source / "Contents" / "MacOS" / "revise").is_file():
                raise ReviseError("La mise à jour ne contient pas l'application attendue.")
            _run(run, [str(source / "Contents" / "MacOS" / "revise"), "--selftest"],
                 "La nouvelle version ne démarre pas", SELFTEST_TIMEOUT)
            try:
                _remove(new)
            except OSError as e:
                raise ReviseError(f"Dossier de l'application protégé ({e.strerror or e}).") from e
            _run(run, ["ditto", str(source), str(new)], "Copie de la nouvelle version impossible")
        finally:
            try:
                run(["hdiutil", "detach", str(mount), "-force"], capture_output=True, timeout=120)
            except (OSError, subprocess.SubprocessError):
                pass
        _swap(new, bundle)
    except ReviseError:
        try:
            _remove(new)
        except OSError:
            pass
        raise
    finally:
        try:
            mount.rmdir()
        except OSError:
            pass


def install_local(file: Path, run=subprocess.run) -> tuple[str, Path]:
    """Installe une mise à jour déjà téléchargée (un revise.exe, ou un .dmg sur Mac)."""
    found = app_target()
    if found is None:
        raise ReviseError("L'installation automatique n'existe que pour les applications Windows et Mac.")
    kind, target = found
    if kind == "windows":
        new = sibling(target, NEW)
        if file.resolve() != new.resolve():
            try:
                shutil.copyfile(file, new)
            except OSError as e:
                raise ReviseError(f"Dossier de l'application protégé ({e.strerror or e}).") from e
        install_windows(new, target, run)
    else:
        install_mac(file, target, run)
    return kind, target


def install(release: Release, progress: DownloadProgress = lambda done, total: None, opener=net.urlopen,
            run=subprocess.run, cancelled: Callable[[], bool] = lambda: False) -> tuple[str, Path]:
    """Télécharge et installe `release`. Renvoie ce qu'il faut relancer (voir `relaunch`)."""
    found = app_target()
    if found is None:
        raise ReviseError("L'installation automatique n'existe que pour les applications Windows et Mac.")
    kind, target = found
    asset = release.assets.get(asset_name(kind))
    if asset is None:
        raise ReviseError("Cette version n'a pas (encore) de fichier pour cet ordinateur.")
    if kind == "windows":
        new = sibling(target, NEW)  # à côté de l'exécutable : l'échange se fait sur le même disque
        download(asset, new, progress, opener, cancelled)
        install_windows(new, target, run)
    else:
        with tempfile.TemporaryDirectory(prefix="revise-maj-") as tmp:
            dmg = Path(tmp) / asset_name(kind)
            download(asset, dmg, progress, opener, cancelled)
            install_mac(dmg, target, run)
    return kind, target


def relaunch(kind: str, target: Path, popen=subprocess.Popen) -> None:
    """Lance la version qui vient d'être installée (l'appelant quitte ensuite)."""
    if kind == "windows":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        popen([str(target)], env=child_env(), close_fds=True, creationflags=flags)
    else:
        popen(["open", "-n", str(target)], env=child_env())
