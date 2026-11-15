"""Fenêtre de mise à jour : télécharge et installe la nouvelle version, puis relance l'application."""

from __future__ import annotations

import threading

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from revise import selfupdate, updates
from revise.gui.common import muted, row
from revise.models import ReviseError


class UpdateDialog(QDialog):
    progressed = Signal(int, int)
    finished_ok = Signal(str, str)  # type d'application, chemin à relancer
    failed = Signal(str)

    def __init__(self, release: updates.Release, parent=None, installer=selfupdate.install):
        super().__init__(parent)
        self.release = release
        self.installer = installer
        self.installed: tuple[str, str] | None = None
        self._cancel = False
        self._running = False
        self.setWindowTitle("Mise à jour")
        self.resize(560, 260)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        t = QLabel(f"Installer la version {release.version} ?")
        t.setObjectName("section")
        lay.addWidget(t)
        self.text = muted("L'application télécharge la nouvelle version, vérifie qu'elle fonctionne, la met à la "
                          "place de l'actuelle puis se relance. Tes cours et ta progression ne sont pas touchés.")
        lay.addWidget(self.text)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        lay.addStretch(1)
        self.page_btn = QPushButton("Télécharger moi-même")
        self.page_btn.setToolTip("Ouvre la page de téléchargement dans le navigateur.")
        self.page_btn.clicked.connect(self.open_page)
        self.cancel_btn = QPushButton("Plus tard")
        self.cancel_btn.clicked.connect(self.reject)
        self.install_btn = QPushButton("Installer")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self.start)
        lay.addLayout(row(self.page_btn, None, self.cancel_btn, self.install_btn))
        self.progressed.connect(self._on_progress)
        self.finished_ok.connect(self._on_done)
        self.failed.connect(self._on_failed)

    def open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(updates.DOWNLOAD_PAGE))

    def start(self) -> None:
        if self._running:
            return
        self._running, self._cancel = True, False
        self.install_btn.setEnabled(False)
        self.page_btn.setEnabled(False)
        self.cancel_btn.setText("Annuler")
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)
        self.text.setText("Téléchargement…")

        def work() -> None:
            try:
                kind, target = self.installer(self.release, self.progressed.emit, cancelled=lambda: self._cancel)
                self.finished_ok.emit(kind, str(target))
            except ReviseError as e:
                self.failed.emit(str(e))
            except Exception as e:  # ne jamais laisser la fenêtre bloquée sur « Téléchargement… »
                self.failed.emit(f"erreur inattendue : {e}")
        threading.Thread(target=work, name="revise-installation", daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        if done >= total:
            self.bar.setRange(0, 0)
            self.text.setText("Vérification et installation… (une minute au plus)")
            self.cancel_btn.setEnabled(False)  # l'échange des fichiers ne s'interrompt pas
        else:
            self.text.setText(f"Téléchargement… {done // (1 << 20)} Mo sur {total // (1 << 20)} Mo")

    def _on_done(self, kind: str, target: str) -> None:
        self._running = False
        self.installed = (kind, target)
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._running = False
        self.bar.setVisible(False)
        self.text.setText(f"La mise à jour automatique n'a pas marché : {message}\n\n"
                          "Rien n'a été modifié. Tu peux réessayer, ou télécharger la nouvelle version toi-même.")
        self.install_btn.setText("Réessayer")
        for b in (self.install_btn, self.page_btn, self.cancel_btn):
            b.setEnabled(True)
        self.cancel_btn.setText("Fermer")

    def reject(self) -> None:
        if self._running:
            self._cancel = True  # le fil s'arrête au prochain morceau reçu, puis `failed` rend la main
            self.text.setText("Annulation…")
            return
        super().reject()
