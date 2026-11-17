"""Fenêtre « Mettre à jour les cours » : refait les cartes et les QCM de cours déjà importés (fabriqués par une
ancienne version, ou dont le fichier a changé) sans perdre la progression."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout)

from revise import config
from revise.db import Database, deck_label
from revise.engines.claude_code import claude_binary
from revise.gui.common import Eta, muted, row
from revise.gui.import_page import ENGINES, ImportWorker
from revise.importer import is_outdated, source_file

DECK_ROLE = Qt.ItemDataRole.UserRole
ENGINE_LABELS = {"ia": "L'IA de cet ordinateur", "en-ligne": "L'IA en ligne", "simple": "Sans IA (immédiat)",
                 "abonnement": "Mon abonnement Claude"}


class UpdateCoursesDialog(QDialog):
    def __init__(self, db: Database, deck_ids: list[int], parent=None):
        super().__init__(parent)
        self.db = db
        self.paths: dict[int, Path | None] = {}
        self._thread: QThread | None = None
        self.worker: ImportWorker | None = None
        self.updated = 0
        self.eta = Eta()
        self.setWindowTitle("Mettre à jour les cours")
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(muted(
            "Les cartes et les QCM de ces cours sont refaits avec la version actuelle de l'application, à partir "
            "du fichier du cours (s'il a changé, c'est la nouvelle version qui est lue). Une nouvelle carte qui dit "
            "la même chose qu'une ancienne garde ta progression ; les anciennes cartes sans équivalent sont "
            "retirées. Pas besoin de supprimer ni de réimporter quoi que ce soit."))
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.locate_btn = QPushButton("Choisir le fichier du cours sélectionné…")
        self.locate_btn.clicked.connect(self.locate)
        lay.addLayout(row(self.locate_btn, None))
        self.engine = QComboBox()
        has_claude = claude_binary() is not None
        for name in ENGINES:
            if name != "abonnement" or has_claude:
                self.engine.addItem(ENGINE_LABELS[name], name)
        saved = config.load().get("engine", "ia")
        self.engine.setCurrentIndex(max(0, self.engine.findData(saved)))
        lay.addLayout(row(muted("Qui refait les cartes :"), self.engine, None))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("%p %")
        self.progress.setVisible(False)
        self.status = muted("")
        self.eta_label = muted("")
        self.eta_label.setWordWrap(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setVisible(False)
        lay.addWidget(self.progress)
        lay.addLayout(row(self.status, None, self.eta_label))
        lay.addWidget(self.log)
        self.close_btn = QPushButton("Fermer")
        self.close_btn.clicked.connect(self.reject)
        self.stop_btn = QPushButton("Arrêter après ce cours")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self.stop)
        self.start_btn = QPushButton("Refaire les cartes")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        lay.addLayout(row(None, self.close_btn, self.stop_btn, self.start_btn))
        for d in deck_ids:
            self.paths[d] = None
        self.fill()

    def fill(self) -> None:
        self.list.clear()
        for deck_id in self.paths:
            deck = self.db.deck(deck_id)
            if deck is None:
                continue
            path = self.paths[deck_id] or source_file(deck)
            state = ("fichier introuvable : choisis-le" if path is None else
                     "fabriqué par une ancienne version" if is_outdated(deck) else "à jour (refait quand même)")
            item = QListWidgetItem(f"{deck_label(deck)}   —   {state}")
            item.setToolTip(str(path) if path else (deck.source or ""))
            item.setData(DECK_ROLE, deck_id)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        ready = sum(1 for d in self.paths if self.paths[d] or (self.db.deck(d) and source_file(self.db.deck(d))))
        self.start_btn.setEnabled(ready > 0 and self._thread is None)
        self.start_btn.setText(f"Refaire les cartes de {ready} cours" if ready > 1 else "Refaire les cartes")

    def locate(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        deck = self.db.deck(item.data(DECK_ROLE))
        start = str(Path(deck.source).parent) if deck and deck.source and Path(deck.source).parent.is_dir() \
            else str(Path.home())
        chosen, _ = QFileDialog.getOpenFileName(self, "Fichier du cours", start, "Cours (*.pdf *.pptx *.docx *.txt *.md)")
        if chosen:
            self.set_path(item.data(DECK_ROLE), Path(chosen))

    def set_path(self, deck_id: int, path: Path) -> None:
        self.paths[deck_id] = path
        self.fill()

    def jobs(self) -> dict[int, Path | None]:
        """Cours qu'on peut refaire : fichier choisi, sinon celui enregistré s'il existe."""
        out = {}
        for deck_id, path in self.paths.items():
            deck = self.db.deck(deck_id)
            if deck is not None and (path or source_file(deck)):
                out[deck_id] = path
        return out

    def start(self) -> None:
        jobs = self.jobs()
        if not jobs or self._thread is not None:
            return
        engine = self.engine.currentData()
        if engine == "en-ligne":
            from revise.engines import online
            if not online.chain():
                self.status.setText("Configure d'abord l'IA en ligne dans « Ajouter un cours ».")
                return
        for w in (self.progress, self.log, self.stop_btn):
            w.setVisible(True)
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.eta.restart()
        self._total, self._done = len(jobs), 0
        self._thread = QThread(self)
        self.worker = ImportWorker(Path(self.db.path), [], None, engine, updates=jobs)
        self.worker.moveToThread(self._thread)
        self._thread.started.connect(self.worker.run)
        self.worker.status.connect(self._on_status)
        self.worker.file_done.connect(self._file_done)
        self.worker.all_done.connect(self._all_done)
        self._thread.start()

    def stop(self) -> None:
        if self.worker:
            self.worker.cancelled = True
            self.stop_btn.setEnabled(False)

    def _on_status(self, text: str, fraction: float, phase: str) -> None:
        self.status.setText(text)
        if phase == "download":
            self.progress.setFormat("Téléchargement : %p %")
            if fraction >= 0:
                self.progress.setValue(int(fraction * 1000))
            self.eta.restart()
            return
        self.progress.setFormat("%p %")
        if fraction >= 0:
            self.progress.setValue(max(self.progress.value(), int(fraction * 1000)))
            self.eta_label.setText(self.eta.text(fraction))

    def _file_done(self, name: str, msg: str, ok: bool) -> None:
        self._done += 1
        self.progress.setValue(max(self.progress.value(), int(1000 * self._done / max(1, self._total))))
        self.log.appendPlainText(f"{'✓' if ok else '✗'} {name} — {msg}")

    def _all_done(self, updated: int) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.worker = None
        self.updated += updated
        self.stop_btn.setVisible(False)
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Terminé")
        self.close_btn.setObjectName("primary")
        self.eta_label.setText("")
        self.status.setText(f"Terminé : {updated} cours mis à jour." if updated else "Terminé.")
        self.fill()

    def reject(self) -> None:
        if self._thread is None:  # pas de fermeture pendant que l'IA écrit dans la base
            super().reject()
