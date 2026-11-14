"""Enregistre l'icône de l'application en PNG (PyInstaller la convertit en .ico ou .icns avec Pillow).

Usage : python packaging/make_icon.py build/icon.png
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from revise.gui.theme import app_icon  # noqa: E402

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    if not app_icon(1024).pixmap(1024, 1024).save(str(out), "PNG"):
        sys.exit(f"Impossible d'écrire {out}")
    print(out)
