"""Fenêtre « Sauvegarde » : copier toutes ses données dans un fichier, ou les reprendre d'un fichier."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout

from revise.db import Database
from revise.gui.common import confirm, muted, row
from revise.models import ReviseError

FILTER = "Sauvegarde revise (*.db)"


class BackupDialog(QDialog):
    def __init__(self, db: Database, busy: bool = False, parent=None):
        super().__init__(parent)
        self.db = db
        self.restored = False
        self.setWindowTitle("Sauvegarde")
        self.resize(620, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        t = QLabel("Mettre mes données à l'abri")
        t.setObjectName("section")
        lay.addWidget(t)
        lay.addWidget(muted("Enregistre tous tes cours, tes cartes et ta progression dans un seul fichier. "
                            "Garde-le sur une clé USB ou dans un dossier synchronisé : il sert aussi à passer "
                            "sur un autre ordinateur."))
        self.save_btn = QPushButton("Enregistrer une sauvegarde…")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save)
        lay.addLayout(row(self.save_btn, None))
        lay.addSpacing(10)

        t = QLabel("Reprendre une sauvegarde")
        t.setObjectName("section")
        lay.addWidget(t)
        lay.addWidget(muted("Remplace tout ce qu'il y a dans l'application par le contenu d'une sauvegarde."))
        self.restore_btn = QPushButton("Restaurer une sauvegarde…")
        self.restore_btn.clicked.connect(self.restore)
        lay.addLayout(row(self.restore_btn, None))
        self.state = muted("")
        lay.addWidget(self.state)
        lay.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        lay.addLayout(row(None, close))
        if busy:
            self.restore_btn.setEnabled(False)
            self.state.setText("Restauration impossible pendant que l'IA travaille : attends qu'elle ait fini.")

    def save(self) -> None:
        start = Path.home() / f"revise-sauvegarde-{date.today().isoformat()}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer une sauvegarde", str(start), FILTER)
        if path:
            self.save_to(Path(path))

    def save_to(self, dest: Path) -> bool:
        if not dest.suffix:
            dest = dest.with_suffix(".db")
        try:
            self.db.backup_to(dest)
        except ReviseError as e:
            QMessageBox.warning(self, "Sauvegarde", str(e))
            return False
        self.state.setText(f"Sauvegarde enregistrée : {dest}")
        return True

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choisir une sauvegarde", str(Path.home()), FILTER)
        if not path:
            return
        if confirm(self, "Restaurer", "Remplacer tous tes cours et ta progression actuels par cette sauvegarde ?\n\n"
                   "Ce que tu as maintenant est gardé dans un fichier de secours, au cas où.", "Restaurer"):
            self.restore_from(Path(path))

    def restore_from(self, src: Path) -> bool:
        try:
            previous = self.db.restore_from(src)
        except ReviseError as e:
            QMessageBox.warning(self, "Restauration", str(e))
            return False
        self.restored = True
        self.state.setText("Sauvegarde restaurée." + (f" Tes anciennes données : {previous}" if previous else ""))
        return True
