"""Moteur « ia » : une IA qui tourne sur la machine, sans rien installer à la main.

Au premier import, l'application télécharge elle-même le moteur d'inférence
(llama.cpp, quelques dizaines de Mo) et le modèle de langage (Gemma 3, plusieurs Go)
dans son dossier de données. Ensuite tout fonctionne hors ligne : le moteur est lancé
en arrière-plan le temps de l'import, et la carte graphique est utilisée s'il y en a une.
"""

from __future__ import annotations

import atexit
import json
import os
import platform as platform_info
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from revise import config
from revise.engines import Progress, distractors
from revise.engines.prompt import CARD_SCHEMA, generate_cards
from revise.models import CardDraft, ReviseError

LLAMA_TAG = "b12374"  # version de llama.cpp, figée pour que les noms de fichiers restent valides
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{asset}"
HF = "https://huggingface.co/ggml-org/{repo}/resolve/main/{file}"
# identifiant -> (nom affiché, adresse, taille exacte en octets)
MODELS = {
    "12b": ("Gemma 3 12B", HF.format(repo="gemma-3-12b-it-GGUF", file="gemma-3-12b-it-Q4_K_M.gguf"), 7_300_574_976),
    "4b": ("Gemma 3 4B", HF.format(repo="gemma-3-4b-it-GGUF", file="gemma-3-4b-it-Q4_K_M.gguf"), 2_489_757_856),
}
BIG_MODEL_RAM = 14e9   # en dessous (machines de 8 ou 12 Go), le gros modèle ne tient pas en mémoire
CONTEXT = 8192
MAX_TOKENS = 4096
LOAD_TIMEOUT = 900     # chargement du modèle
CHAT_TIMEOUT = 3 * 3600  # un morceau de cours, même sur un vieux processeur


def ia_dir() -> Path:
    return config.data_dir() / "ia"


def total_ram() -> float:
    """Mémoire vive de la machine en octets (0 si inconnue)."""
    try:
        if os.name == "nt":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong) for n in ("total", "avail", "tpage", "apage", "tvirt", "avirt", "aext")]

            st = Status()
            st.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return float(st.total)
        return float(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, AttributeError):
        return 0.0


def pick_model(ram: float | None = None) -> str:
    """« 12b » (le meilleur) si la machine a assez de mémoire, sinon « 4b »."""
    wanted = os.environ.get("REVISE_IA_MODELE", "")
    if wanted in MODELS:
        return wanted
    ram = total_ram() if ram is None else ram
    return "12b" if ram >= BIG_MODEL_RAM else "4b"


def server_kinds(platform: str | None = None) -> list[tuple[str, list[str]]]:
    """Moteurs à essayer dans l'ordre, avec leurs options : carte graphique d'abord, puis processeur seul."""
    if (platform or sys.platform) == "darwin":  # un seul moteur sur Mac, la carte graphique (Metal) est incluse
        return [("mac", []), ("mac", ["-ngl", "0"])]
    return [("vulkan", []), ("vulkan", ["-ngl", "0"]), ("cpu", [])]


def server_asset(kind: str, platform: str | None = None, machine: str | None = None) -> str:
    """Nom de l'archive llama.cpp pour ce système. `kind` : « vulkan » (carte graphique), « cpu » ou « mac »."""
    platform = platform or sys.platform
    if platform == "darwin":
        arch = "arm64" if (machine or platform_info.machine()).lower() in ("arm64", "aarch64") else "x64"
        return f"llama-{LLAMA_TAG}-bin-macos-{arch}.tar.gz"
    if platform.startswith("win"):
        return f"llama-{LLAMA_TAG}-bin-win-{kind}-x64.zip"
    if platform.startswith("linux"):
        return f"llama-{LLAMA_TAG}-bin-ubuntu-{'vulkan-' if kind == 'vulkan' else ''}x64.tar.gz"
    raise ReviseError("L'IA intégrée n'existe que pour Windows, Mac et Linux (64 bits) : utilise l'IA en ligne.")


def download(url: str, dest: Path, progress: Progress, label: str, expected: int | None = None,
             opener=urllib.request.urlopen) -> Path:
    """Télécharge `url` dans `dest`, en reprenant un téléchargement interrompu."""
    if dest.exists() and (expected is None or dest.stat().st_size == expected):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if expected is not None and have > expected:
        part.unlink()
        have = 0
    if expected is None or have < expected:
        free = shutil.disk_usage(dest.parent).free
        if expected is not None and free < expected - have + 500_000_000:
            raise ReviseError(f"Pas assez de place sur le disque pour {label} : il faut "
                              f"{(expected - have) / 1e9:.1f} Go libres dans {dest.parent}.")
        headers = {"User-Agent": "revise"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with opener(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                if have and getattr(resp, "status", 200) != 206:  # le serveur renvoie tout : on repart de zéro
                    have = 0
                total = expected or have + int(resp.headers.get("Content-Length") or 0)
                last = -1
                with open(part, "ab" if have else "wb") as f:
                    while block := resp.read(1 << 20):
                        f.write(block)
                        have += len(block)
                        pct = int(have * 100 / total) if total else 0
                        if pct != last:
                            last = pct
                            progress(f"Téléchargement de {label} : {pct} % de {total / 1e9:.2f} Go (une seule fois)")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise ReviseError(f"Téléchargement de {label} interrompu ({e}). Vérifie ta connexion et relance "
                              "l'import : il reprendra où il s'est arrêté.") from e
    if expected is not None and part.stat().st_size != expected:
        if part.stat().st_size > expected:
            part.unlink()
        raise ReviseError(f"Téléchargement de {label} incomplet : relance l'import, il reprendra où il s'est arrêté.")
    part.replace(dest)
    return dest


def model_path(progress: Progress) -> tuple[str, Path]:
    """Nom et fichier du modèle à utiliser, téléchargé au besoin."""
    custom = os.environ.get("REVISE_IA_MODELE", "")
    if custom.endswith(".gguf"):
        path = Path(custom).expanduser()
        if not path.exists():
            raise ReviseError(f"Modèle introuvable : {path}")
        return path.stem, path
    label, url, size = MODELS[pick_model()]
    return label, download(url, ia_dir() / url.rsplit("/", 1)[1], progress, f"l'IA {label}", size)


def server_binary(kind: str, progress: Progress) -> Path:
    """Exécutable llama-server, téléchargé et décompressé au besoin."""
    folder = ia_dir() / f"llama-{LLAMA_TAG}-{kind}"
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    found = next(folder.rglob(name), None) if folder.exists() else None
    if found:
        return found
    asset = server_asset(kind)
    archive = download(LLAMA_URL.format(tag=LLAMA_TAG, asset=asset), ia_dir() / asset, progress, "du moteur d'IA")
    tmp = folder.with_name(folder.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                t.extractall(tmp, filter="tar")
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
        archive.unlink(missing_ok=True)
        raise ReviseError(f"Archive du moteur d'IA illisible ({e}) : relance l'import.") from e
    shutil.rmtree(folder, ignore_errors=True)
    tmp.replace(folder)
    archive.unlink(missing_ok=True)
    found = next(folder.rglob(name), None)
    if not found:
        raise ReviseError("Le moteur d'IA téléchargé ne contient pas llama-server.")
    if os.name != "nt":
        found.chmod(0o755)
    return found


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EmbeddedEngine:
    name = "ia"

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.label = ""
        self.progress: Progress = lambda m: None
        atexit.register(self.close)

    # -- serveur llama.cpp ------------------------------------------------------

    def _spawn(self, exe: Path, model: Path, extra: list[str]) -> bool:
        """Lance le serveur et attend qu'il ait chargé le modèle. Faux s'il n'a pas démarré."""
        self.port = free_port()
        cmd = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(self.port),
               "-c", str(CONTEXT), "-np", "1", *extra]
        env = dict(os.environ)
        if os.name != "nt":
            for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
                env[var] = f"{exe.parent}:{env.get(var, '')}"
        log = open(ia_dir() / "serveur.log", "ab")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(cmd, cwd=exe.parent, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                         stderr=subprocess.STDOUT, creationflags=flags)
        except OSError:
            log.close()
            return False
        log.close()
        deadline = time.monotonic() + LOAD_TIMEOUT
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.proc = None
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=5) as r:
                    if r.status == 200:
                        return True
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                pass
            time.sleep(0.5)
        self.close()
        return False

    def start(self, progress: Progress) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        self.label, model = model_path(progress)
        # Carte graphique d'abord ; si elle pose problème, processeur seul, puis moteur sans Vulkan.
        for i, (kind, extra) in enumerate(server_kinds()):
            exe = server_binary(kind, progress)
            progress(f"Chargement de l'IA {self.label}…" + (" (sans carte graphique)" if i else ""))
            if self._spawn(exe, model, extra):
                return
        raise ReviseError("L'IA intégrée n'a pas pu démarrer sur cette machine (détails dans "
                          f"{ia_dir() / 'serveur.log'}). Essaie l'IA en ligne.")

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    # -- génération -------------------------------------------------------------

    def chat(self, system: str, user: str, schema: dict = CARD_SCHEMA) -> str:
        self.start(self.progress)
        payload = {
            "temperature": 0.2,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "reponse", "strict": True, "schema": schema}},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                     data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=CHAT_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as e:
            raise ReviseError(f"L'IA intégrée a renvoyé une erreur ({e.code}) : {e.read().decode()[:300]}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise ReviseError(f"L'IA intégrée s'est arrêtée pendant la génération ({e}).") from e
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ReviseError("Réponse inattendue de l'IA intégrée.") from e

    def generate(self, pdf: Path, subject: str, progress: Progress) -> tuple[str, list[CardDraft]]:
        self.progress = progress
        title, cards = generate_cards(pdf, subject, progress, self.chat, "IA intégrée")
        distractors.add_to_drafts(cards, subject, self.chat, progress, "IA intégrée")
        return title, cards
