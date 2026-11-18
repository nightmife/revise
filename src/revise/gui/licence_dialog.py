"""Fenêtre « Activer revise » (clé de licence Gumroad), et revérification de la licence en arrière-plan."""

from __future__ import annotations

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout

from revise import licence
from revise.gui.common import Background, muted, row
from revise.models import ReviseError


class LicenceDialog(QDialog):
    def __init__(self, parent=None, activator=licence.activate):
        super().__init__(parent)
        self.activator = activator
        self._running = False
        self.setWindowTitle("Activer revise")
        self.resize(560, 280)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        t = QLabel("Activer revise")
        t.setObjectName("section")
        lay.addWidget(t)
        lay.addWidget(muted("Colle la clé de licence reçue par mail après l'achat sur Gumroad. Il faut Internet "
                            "pour l'activation, ensuite l'application marche aussi hors ligne."))
        self.key = QLineEdit()
        self.key.setPlaceholderText("XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX")
        self.key.returnPressed.connect(self.start)
        lay.addWidget(self.key)
        self.status = muted("")
        self.status.setVisible(False)
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.buy_btn = QPushButton("Acheter revise")
        self.buy_btn.setToolTip("Ouvre la page de vente dans le navigateur.")
        self.buy_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(licence.BUY_URL)))
        self.buy_btn.setVisible(bool(licence.BUY_URL))
        self.quit_btn = QPushButton("Quitter")
        self.quit_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton("Activer")
        self.ok_btn.setObjectName("primary")
        self.ok_btn.clicked.connect(self.start)
        lay.addLayout(row(self.buy_btn, None, self.quit_btn, self.ok_btn))
        self.job = Background(self, self._on_message)

    def show_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def start(self) -> None:
        if self._running:
            return
        key = self.key.text()
        self._running = True
        self.ok_btn.setEnabled(False)
        self.key.setEnabled(False)
        self.show_status("Vérification de la clé…")

        def work(post) -> None:
            try:
                self.activator(key)
                post(None)
            except ReviseError as e:
                post(str(e))
            except Exception as e:  # ne jamais laisser la fenêtre bloquée sur « Vérification… »
                post(f"Erreur inattendue : {e}")
        self.job.start(work)

    def _on_message(self, error: str | None) -> None:
        self._running = False
        if error is None:
            self.accept()
            return
        self.ok_btn.setEnabled(True)
        self.key.setEnabled(True)
        self.key.setFocus()
        self.show_status(error)

    def reject(self) -> None:
        if not self._running:  # la vérification en cours enregistrerait la clé après la fermeture
            super().reject()


def ensure_licence(parent=None) -> bool:
    """True si l'application peut s'ouvrir (pas de licence demandée, déjà activée, ou activée à l'instant)."""
    if not licence.required() or licence.is_active():
        return True
    return LicenceDialog(parent).exec() == QDialog.DialogCode.Accepted


def recheck_in_background(parent: QObject, opener=None) -> None:
    """Revérifie la licence auprès de Gumroad si c'est le moment ; le résultat compte au prochain lancement."""
    if not licence.required():
        return
    key = licence.due_key()
    if key is None:
        return

    def work(post) -> None:
        post(licence.remote_status(key, opener) if opener else licence.remote_status(key))
    job = Background(parent, lambda status: licence.record(key, status))
    job.start(work)
