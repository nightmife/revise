"""Page « Importer » : choix des PDF, de la matière et du moteur, import en arrière-plan."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QFileDialog, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QVBoxLayout, QWidget,
                               QApplication)

from revise import config
from revise.db import Database, file_sha256
from revise.engines import online
from revise.gui.common import muted, page_header, row
from revise.importer import guess_subject, import_pdf
from revise.models import ReviseError

PATH_ROLE = Qt.ItemDataRole.UserRole
AUTO_SUBJECT = "Automatique (d'après le nom du fichier)"
SEARCH_DIRS = ["Downloads", "Téléchargements", "Documents"]


ENGINES = ("ia", "en-ligne", "simple")  # dans l'ordre des boutons radio


def make_engine(name: str):
    from revise.engines.embedded import EmbeddedEngine
    from revise.engines.simple import SimpleEngine
    return {"ia": EmbeddedEngine, "en-ligne": online.OnlineEngine, "simple": SimpleEngine}[name]()


class KeyDialog(QDialog):
    """Réglages de l'IA en ligne : service, clé API, modèle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clé API de l'IA en ligne")
        self.resize(620, 300)
        form = QFormLayout(self)
        self.provider = QComboBox()
        for key, (label, *_rest) in online.PROVIDERS.items():
            self.provider.addItem(label, key)
        self.link = QLabel()
        self.link.setOpenExternalLinks(True)
        self.link.setWordWrap(True)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("colle ta clé ici")
        self.model = QLineEdit()
        self.url = QLineEdit()
        form.addRow("Service :", self.provider)
        form.addRow("", self.link)
        form.addRow("Clé API :", self.key)
        form.addRow("Modèle :", self.model)
        form.addRow("Adresse :", self.url)
        form.addRow(muted("La clé reste sur cet ordinateur. Le texte de tes cours est envoyé au service choisi."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        current = online.settings()
        self.provider.setCurrentIndex(max(0, self.provider.findData(current["provider"])))
        self.key.setText(config.load().get("online_key", ""))
        self._provider_changed()
        self.model.setText(current["model"])
        self.url.setText(current["url"])
        self.provider.currentIndexChanged.connect(self._provider_changed)

    def _provider_changed(self) -> None:
        _, url, model, page = online.PROVIDERS[self.provider.currentData()]
        self.model.setText(model)
        self.url.setText(url)
        self.link.setText(f"Crée une clé gratuite ici : <a href='{page}' style='color:#8aa3ff'>{page}</a>" if page
                          else "Indique l'adresse de l'API (elle finit souvent par /v1) et le nom du modèle.")

    def _save(self) -> None:
        if not self.key.text().strip():
            QMessageBox.warning(self, "Clé API", "Colle ta clé API avant d'enregistrer.")
            return
        config.save({"online_provider": self.provider.currentData(), "online_key": self.key.text().strip(),
                     "online_model": self.model.text().strip(), "online_url": self.url.text().strip()})
        self.accept()


class ImportWorker(QObject):
    """Importe les PDF un par un dans un thread (avec sa propre connexion SQLite)."""

    status = Signal(str)
    file_done = Signal(str, str, bool)  # nom, message, succès
    all_done = Signal(int)

    def __init__(self, db_path: Path, pdfs: list[Path], subject: str | None, engine_name: str):
        super().__init__()
        self.db_path, self.pdfs, self.subject, self.engine_name = db_path, pdfs, subject, engine_name
        self.cancelled = False
        self.engine = None

    def run(self) -> None:
        db = Database(self.db_path)
        engine = self.engine = make_engine(self.engine_name)
        imported = 0
        try:
            for pdf in self.pdfs:
                if self.cancelled:
                    break
                try:
                    res = import_pdf(db, engine, pdf, self.subject, lambda m, n=pdf.name: self.status.emit(f"{n} : {m}"))
                    if res.skipped:
                        self.file_done.emit(pdf.name, "déjà importé", True)
                    else:
                        imported += 1
                        self.file_done.emit(pdf.name, f"{len(res.cards)} cartes", True)
                except ReviseError as e:
                    self.file_done.emit(pdf.name, str(e), False)
                except Exception as e:  # on ne laisse pas un PDF bizarre tuer tout l'import
                    self.file_done.emit(pdf.name, f"erreur inattendue : {e}", False)
        finally:
            self.stop_engine()
            db.close()
            self.all_done.emit(imported)


    def stop_engine(self) -> None:
        """Arrête l'IA intégrée si elle tourne (sans effet pour les autres moteurs)."""
        getattr(self.engine, "close", lambda: None)()


class ImportPage(QWidget):
    imported = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.setObjectName("page")
        self.db = db
        self._thread: QThread | None = None
        self.worker: ImportWorker | None = None
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(page_header("Importer des cours",
                                  "Coche les PDF de CM à transformer en cartes. Tu peux aussi glisser-déposer des PDF ici."))

        self.files = QListWidget()
        lay.addWidget(self.files, 1)
        add_btn = QPushButton("Ajouter des PDF…")
        add_btn.clicked.connect(self.browse)
        scan_btn = QPushButton("Actualiser")
        scan_btn.clicked.connect(self.scan)
        self.count_label = muted("")
        lay.addLayout(row(add_btn, scan_btn, self.count_label, None))

        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.setMinimumWidth(320)
        lay.addLayout(row(muted("Matière :"), self.subject, None))

        self.engine_group = QButtonGroup(self)
        self.r_ia = QRadioButton("IA intégrée — gratuite, hors ligne, rien à installer")
        self.r_ia.setToolTip("Le modèle (2,5 à 7 Go selon la mémoire de l'ordinateur) est téléchargé une seule fois, "
                             "au premier import.")
        self.r_online = QRadioButton("IA en ligne — rapide, avec ta clé API gratuite (Internet nécessaire)")
        self.r_simple = QRadioButton("Sans IA — instantané, cartes à retoucher")
        key_btn = QPushButton("Clé API…")
        key_btn.clicked.connect(self.edit_key)
        self.key_state = muted("")
        for i, r in enumerate((self.r_ia, self.r_online, self.r_simple)):
            self.engine_group.addButton(r, i)
            if r is self.r_online:
                lay.addLayout(row(r, key_btn, self.key_state, None))
            elif r is self.r_ia:
                lay.addLayout(row(r, muted("modèle téléchargé au premier import (2,5 à 7 Go), "
                                           "plusieurs minutes par cours"), None))
            else:
                lay.addWidget(r)
        saved = config.load().get("engine")
        self.engine_group.button(ENGINES.index(saved) if saved in ENGINES else 0).setChecked(True)
        self._update_key_state()

        self.import_btn = QPushButton("Importer la sélection")
        self.import_btn.setObjectName("primary")
        self.import_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Arrêter après ce PDF")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setVisible(False)
        lay.addLayout(row(self.import_btn, self.cancel_btn, None))

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.status = muted("")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setVisible(False)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(self.log)
        self.files.itemChanged.connect(self._update_count)
        self.scan()

    # ------------------------------------------------------------- fichiers
    def refresh_subjects(self) -> None:
        current = self.subject.currentText()
        self.subject.clear()
        self.subject.addItem(AUTO_SUBJECT)
        for s in self.db.subjects():
            self.subject.addItem(s)
        if current and current != AUTO_SUBJECT:
            self.subject.setCurrentText(current)

    def _known_paths(self) -> set[str]:
        return {self.files.item(i).data(PATH_ROLE) for i in range(self.files.count())}

    def add_file(self, path: Path, checked: bool = False) -> None:
        path = path.resolve()
        if str(path) in self._known_paths() or path.suffix.lower() != ".pdf" or not path.is_file():
            return
        done = self.db.find_deck_by_hash(file_sha256(path)) is not None
        label = f"{path.name}   —   {guess_subject(path)}" + ("   ✓ déjà importé" if done else "")
        item = QListWidgetItem(label)
        item.setData(PATH_ROLE, str(path))
        item.setToolTip(str(path))
        if done:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable & ~Qt.ItemFlag.ItemIsEnabled)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.files.addItem(item)

    def scan(self) -> None:
        """Liste les PDF des dossiers habituels (Téléchargements, Documents)."""
        self.files.blockSignals(True)
        checked = {p for p in self.selected_paths()}
        self.files.clear()
        home = Path.home()
        found: list[Path] = []
        for d in SEARCH_DIRS:
            base = home / d
            if base.is_dir():
                found += [p for p in base.rglob("*.pdf") if len(p.relative_to(base).parts) <= 3]
        found = sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)[:300]  # les plus récents
        for p in sorted(found, key=lambda p: p.name.lower()):
            self.add_file(p, checked=str(p.resolve()) in {str(c) for c in checked})
        self.files.blockSignals(False)
        self.refresh_subjects()
        self._update_count()

    def browse(self) -> None:
        start = str(Path.home() / "Downloads") if (Path.home() / "Downloads").is_dir() else str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(self, "Choisir des PDF de cours", start, "PDF (*.pdf)")
        for p in paths:
            self.add_file(Path(p), checked=True)
        self._update_count()

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                for f in sorted(p.rglob("*.pdf")):
                    self.add_file(f, checked=True)
            else:
                self.add_file(p, checked=True)
        self._update_count()

    def selected_paths(self) -> list[Path]:
        out = []
        for i in range(self.files.count()):
            it = self.files.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable and it.checkState() == Qt.CheckState.Checked:
                out.append(Path(it.data(PATH_ROLE)))
        return out

    def _update_count(self, *_):
        n = len(self.selected_paths())
        self.count_label.setText(f"{n} PDF coché(s)" if n else "Coche les PDF à importer")
        self.import_btn.setEnabled(n > 0 and self._thread is None)

    # --------------------------------------------------------------- import
    def engine_name(self) -> str:
        return ENGINES[self.engine_group.checkedId()]

    def _update_key_state(self) -> None:
        conf = online.settings()
        self.key_state.setText(f"clé enregistrée ({online.PROVIDERS[conf['provider']][0]})" if conf["key"]
                               else "aucune clé enregistrée")

    def edit_key(self) -> bool:
        ok = KeyDialog(self).exec() == QDialog.DialogCode.Accepted
        self._update_key_state()
        if ok:
            self.r_online.setChecked(True)
        return ok

    def start(self) -> None:
        pdfs = self.selected_paths()
        if not pdfs or self._thread is not None:
            return
        subject = self.subject.currentText().strip()
        subject = None if (not subject or subject == AUTO_SUBJECT) else subject
        engine = self.engine_name()
        if engine == "en-ligne" and not online.settings()["key"] and not self.edit_key():
            return
        config.save({"engine": engine})
        self.progress.setRange(0, len(pdfs))
        self.progress.setValue(0)
        for w in (self.progress, self.log, self.cancel_btn):
            w.setVisible(True)
        self.log.clear()
        self.import_btn.setEnabled(False)
        self.status.setText("Démarrage…")

        self._thread = QThread(self)
        self.worker = ImportWorker(Path(self.db.path), pdfs, subject, engine)
        self.worker.moveToThread(self._thread)
        self._thread.started.connect(self.worker.run)
        self.worker.status.connect(self.status.setText)
        self.worker.file_done.connect(self._file_done)
        self.worker.all_done.connect(self._all_done)
        self._thread.start()

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancelled = True
            self.cancel_btn.setEnabled(False)
            self.status.setText("Arrêt après le PDF en cours…")

    def _file_done(self, name: str, msg: str, ok: bool) -> None:
        self.progress.setValue(self.progress.value() + 1)
        self.log.appendPlainText(f"{'✓' if ok else '✗'} {name} — {msg}")

    def _all_done(self, imported: int) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.worker = None
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.status.setText(f"Terminé : {imported} cours importé(s)." if imported else "Terminé.")
        self.scan()
        self.imported.emit()
