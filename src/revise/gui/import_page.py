"""Page « Importer » : choix des PDF, de la matière et du moteur, import en arrière-plan."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QVBoxLayout,
                               QWidget)

from revise import config, share
from revise.db import Database, file_sha256
from revise.engines import online
from revise.engines.claude_code import claude_binary
from revise.gui.common import muted, page_header, row, save_cancel_buttons
from revise.importer import guess_subject, import_pdf
from revise.models import ReviseError

PATH_ROLE = Qt.ItemDataRole.UserRole
AUTO_SUBJECT = "Automatique (d'après le nom du fichier)"
SEARCH_DIRS = ["Downloads", "Téléchargements", "Documents"]


ENGINES = ("ia", "en-ligne", "simple", "abonnement")  # dans l'ordre des boutons radio


def make_engine(name: str):
    from revise.engines.claude_code import ClaudeCodeEngine
    from revise.engines.embedded import EmbeddedEngine
    from revise.engines.simple import SimpleEngine
    return {"ia": EmbeddedEngine, "en-ligne": online.OnlineEngine, "simple": SimpleEngine,
            "abonnement": ClaudeCodeEngine}[name]()


class KeyDialog(QDialog):
    """Réglages de l'IA en ligne : service et clé ; modèle et adresse pour ceux qui savent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurer l'IA en ligne")
        self.resize(640, 320)
        form = QFormLayout(self)
        form.addRow(muted("L'IA en ligne est gratuite, mais il faut une « clé » : un mot de passe que le service "
                          "te donne pour l'utiliser. Deux minutes, une seule fois."))
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
        self.advanced = QCheckBox("Réglages avancés (modèle, adresse)")
        self.model_label, self.url_label = QLabel("Modèle :"), QLabel("Adresse :")
        form.addRow("1. Service :", self.provider)
        form.addRow("2. Clé :", self.link)
        form.addRow("3. Colle-la :", self.key)
        form.addRow(self.advanced)
        form.addRow(self.model_label, self.model)
        form.addRow(self.url_label, self.url)
        form.addRow(muted("La clé reste sur cet ordinateur. Le texte de tes cours est envoyé au service choisi."))
        buttons = save_cancel_buttons()
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
        self.advanced.toggled.connect(self._show_advanced)
        self._show_advanced()

    def _show_advanced(self, *_) -> None:
        """Modèle et adresse : cachés, sauf pour un service « autre » qui n'a pas de valeurs par défaut."""
        show = self.advanced.isChecked() or self.provider.currentData() == "autre"
        for w in (self.model_label, self.model, self.url_label, self.url):
            w.setVisible(show)

    def _provider_changed(self) -> None:
        _, url, model, page = online.PROVIDERS[self.provider.currentData()]
        self.model.setText(model)
        self.url.setText(url)
        self.link.setText(f"Ouvre <a href='{page}' style='color:#8aa3ff'>{page}</a>, crée un compte gratuit, "
                          "puis clique sur le bouton qui crée une clé et copie-la." if page
                          else "Indique l'adresse de l'API (elle finit souvent par /v1) et le nom du modèle.")
        self._show_advanced()

    def _save(self) -> None:
        if not self.key.text().strip():
            QMessageBox.warning(self, "Clé manquante", "Colle ta clé avant d'enregistrer.")
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
        imported = 0
        try:
            for pdf in self.pdfs:
                if self.cancelled:
                    break
                try:
                    if share.is_share_file(pdf):  # cours partagé : les cartes sont déjà écrites, pas besoin d'IA
                        got = share.import_file(db, pdf, self.subject)
                        new = [r for r in got if not r.skipped]
                        imported += len(new)
                        self.file_done.emit(pdf.name, f"{len(new)} cours, {sum(r.cards for r in new)} cartes" if new
                                            else "déjà ajouté", True)
                        continue
                    if self.engine is None:
                        self.engine = make_engine(self.engine_name)
                    res = import_pdf(db, self.engine, pdf, self.subject,
                                     lambda m, n=pdf.name: self.status.emit(f"{n} : {m}"))
                    if res.skipped:
                        self.file_done.emit(pdf.name, "déjà ajouté", True)
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
        self._scanned = False
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(page_header("Ajouter un cours",
                                  "Donne le PDF d'un cours : l'application en tire des cartes de révision, "
                                  "une fiche et des QCM. Tu peux aussi donner un cours partagé (fichier .revise)."))

        self.drop = QFrame()
        self.drop.setObjectName("drop")
        dl = QHBoxLayout(self.drop)
        dl.setContentsMargins(20, 16, 20, 16)
        drop_text = QLabel("Glisse tes PDF ici")
        drop_text.setObjectName("section")
        add_btn = QPushButton("Choisir des PDF…")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self.browse)
        self.scan_btn = QPushButton("Chercher sur cet ordinateur")
        self.scan_btn.setToolTip("Liste les PDF des dossiers Téléchargements et Documents.")
        self.scan_btn.clicked.connect(lambda: self.scan())
        dl.addWidget(drop_text)
        dl.addWidget(muted("ou"))
        dl.addWidget(add_btn)
        dl.addWidget(self.scan_btn)
        dl.addStretch(1)
        lay.addWidget(self.drop)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un PDF dans la liste…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.count_label = muted("")
        self.count_label.setWordWrap(False)
        lay.addLayout(row(self.search, self.count_label))
        self.files = QListWidget()
        lay.addWidget(self.files, 1)

        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.setMinimumWidth(320)
        self.subject.setToolTip("Sert à regrouper les cours. Tu peux taper un nouveau nom (ex. Histoire).")
        lay.addLayout(row(muted("Matière :"), self.subject, None))

        how = QLabel("Qui écrit les cartes ?")
        how.setObjectName("section")
        lay.addWidget(how)
        self.engine_group = QButtonGroup(self)
        self.r_ia = QRadioButton("L'IA de cet ordinateur (conseillé)")
        self.r_online = QRadioButton("L'IA en ligne (le plus rapide)")
        self.r_simple = QRadioButton("Sans IA")
        self.r_claude = QRadioButton("Mon abonnement Claude")
        key_btn = QPushButton("Configurer…")
        key_btn.clicked.connect(self.edit_key)
        self.key_state = muted("")
        self.key_state.setWordWrap(False)
        details = {
            self.r_ia: "Gratuit, privé, sans compte. Lent : plusieurs minutes par cours, et un gros téléchargement "
                       "la première fois (2,5 à 7 Go).",
            self.r_online: "Quelques secondes par cours. Gratuit, mais il faut créer une clé (2 minutes) "
                           "et le texte du cours est envoyé sur Internet.",
            self.r_simple: "Immédiat, mais cartes approximatives à corriger et QCM facile.",
            self.r_claude: "Rapide et de très bonne qualité, sans clé : passe par Claude Code, installé et connecté "
                           "sur cet ordinateur. Compte dans les limites de ton abonnement.",
        }
        has_claude = claude_binary() is not None  # proposé seulement à ceux qui ont Claude Code
        for i, r in enumerate((self.r_ia, self.r_online, self.r_simple, self.r_claude)):
            self.engine_group.addButton(r, i)
            font = r.font()
            font.setBold(True)
            r.setFont(font)
            if r is self.r_online:
                lay.addLayout(row(r, key_btn, self.key_state, None))
            else:
                lay.addWidget(r)
            detail = muted(details[r])
            detail.setContentsMargins(30, 0, 0, 4)
            lay.addWidget(detail)
            if r is self.r_claude:
                r.setVisible(has_claude)
                detail.setVisible(has_claude)
        saved = config.load().get("engine")
        if saved not in ENGINES or (saved == "abonnement" and not has_claude):
            saved = "ia"
        self.engine_group.button(ENGINES.index(saved)).setChecked(True)
        self._update_key_state()

        self.import_btn = QPushButton("Créer les cartes")
        self.import_btn.setObjectName("primary")
        self.import_btn.setMinimumHeight(46)
        self.import_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Arrêter après ce PDF")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setVisible(False)
        self.status = muted("")
        lay.addLayout(row(self.import_btn, self.cancel_btn, None))

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setVisible(False)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(self.log)
        self.files.itemChanged.connect(self._update_count)
        self.refresh_subjects()
        # Sur Mac, lire Téléchargements/Documents déclenche une demande d'autorisation du système :
        # on ne le fait que si l'utilisateur clique sur « Chercher sur cet ordinateur ».
        if sys.platform != "darwin":
            self.scan()
        self._update_count()

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
        shared = share.is_share_file(path)
        if str(path) in self._known_paths() or not (shared or path.suffix.lower() == ".pdf") or not path.is_file():
            return
        done = not shared and self.db.find_deck_by_hash(file_sha256(path)) is not None
        label = path.name + ("   ✓ déjà ajouté" if done else
                             "   —   cours partagé" if shared else f"   —   {guess_subject(path)}")
        item = QListWidgetItem(label)
        item.setData(PATH_ROLE, str(path))
        item.setToolTip(str(path))
        if done:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable & ~Qt.ItemFlag.ItemIsEnabled)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        if checked:
            self.files.insertItem(0, item)  # ce que l'utilisateur vient de choisir reste sous ses yeux
        else:
            self.files.addItem(item)

    def _filter(self, *_) -> None:
        text = self.search.text().lower().strip()
        for i in range(self.files.count()):
            it = self.files.item(i)
            it.setHidden(bool(text) and text not in it.text().lower())

    def scan(self, search: bool = True) -> None:
        """Reconstruit la liste : les PDF déjà cochés, puis (si `search`) ceux des dossiers habituels
        (Téléchargements, Documents), ceux déjà ajoutés en dernier."""
        self._scanned = self._scanned or search
        self.files.blockSignals(True)
        checked = self.selected_paths()
        self.files.clear()
        home = Path.home()
        found: list[Path] = []
        for d in SEARCH_DIRS if search else []:
            base = home / d
            if base.is_dir():
                found += [p for p in base.rglob("*.pdf") if len(p.relative_to(base).parts) <= 3]
        found = sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)[:300]  # les plus récents
        for p in reversed(checked):  # les PDF choisis à la main restent, même hors des dossiers habituels
            self.add_file(p, checked=True)
        for p in sorted(found, key=lambda p: p.name.lower()):
            self.add_file(p)
        done = [i for i in range(self.files.count())
                if not self.files.item(i).flags() & Qt.ItemFlag.ItemIsEnabled]
        for it in [self.files.takeItem(i) for i in reversed(done)][::-1]:
            self.files.addItem(it)
        self.files.blockSignals(False)
        self.refresh_subjects()
        self._filter()
        self._update_count()

    def browse(self) -> None:
        start = str(Path.home() / "Downloads") if (Path.home() / "Downloads").is_dir() else str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(self, "Choisir des cours", start,
                                                "Cours (*.pdf *.revise);;PDF (*.pdf);;Cours partagés (*.revise)")
        for p in paths:
            self.add_file(Path(p), checked=True)
        self._update_count()

    def _highlight_drop(self, on: bool) -> None:
        self.drop.setProperty("active", "true" if on else "false")
        self.drop.style().unpolish(self.drop)
        self.drop.style().polish(self.drop)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            self._highlight_drop(True)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self._highlight_drop(False)

    def dropEvent(self, e) -> None:
        self._highlight_drop(False)
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
        if n:
            self.count_label.setText(f"{n} PDF coché{'s' if n > 1 else ''}")
        else:
            self.count_label.setText("Coche les PDF à transformer" if self.files.count() else "Aucun PDF choisi")
        self.import_btn.setEnabled(n > 0 and self._thread is None)
        self.import_btn.setText(f"Créer les cartes de {n} cours" if n > 1 else "Créer les cartes")

    # --------------------------------------------------------------- import
    def engine_name(self) -> str:
        return ENGINES[self.engine_group.checkedId()]

    def _update_key_state(self) -> None:
        conf = online.settings()
        self.key_state.setText(f"prête ({online.PROVIDERS[conf['provider']][0]})" if conf["key"]
                               else "pas encore configurée")

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
        needs_ai = any(not share.is_share_file(p) for p in pdfs)
        if needs_ai and engine == "en-ligne" and not online.settings()["key"] and not self.edit_key():
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
        self.status.setText(f"Terminé : {imported} cours ajouté{'s' if imported > 1 else ''}. "
                            "Retrouve-le dans « Mes cours »." if imported else "Terminé.")
        self.scan(search=self._scanned)
        self.imported.emit()
