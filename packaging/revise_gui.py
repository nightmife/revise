"""Point d'entrée de l'exécutable (PyInstaller) : ouvre directement l'application."""

import os
import sys


def selftest() -> int:
    """Vérifie que l'exécutable démarre : construit la fenêtre sans l'afficher."""
    import tempfile
    from pathlib import Path

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    from revise.db import Database
    from revise.gui import theme
    from revise.gui.app import MainWindow

    app = QApplication([])
    app.setStyleSheet(theme.QSS)
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        win = MainWindow(db)
        win.show()
        app.processEvents()
        for page in range(5):
            win.show_page(page)
            app.processEvents()
        win.close()
        db.close()
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from revise.gui.app import main

    sys.exit(main())
