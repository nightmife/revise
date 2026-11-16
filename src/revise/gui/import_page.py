"""Page « Importer » : choix des PDF, de la matière et du moteur, import en arrière-plan."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
                               QScrollArea, QVBoxLayout, QWidget)

from revise import config, documents, share
from revise.db import Database, file_sha256
from revise.engines import online
from revise.engines.claude_code import MODELS as CLAUDE_MODELS, claude_binary
from revise.gui.common import muted, page_header, row, save_cancel_buttons, step_header
from revise.importer import guess_subject, import_pdf
from revise.models import ReviseError

PATH_ROLE = Qt.ItemDataRole.UserRole
AUTO_SUBJECT = "Automatique (d'après le nom du fichier)"
SEARCH_DIRS = ["Downloads", "Téléchargements", "Documents"]
SCAN_SUFFIXES = (".pdf", ".pptx", ".docx")  # la recherche automatique laisse de côté les fichiers texte


ENGINES = ("ia", "en-ligne", "simple", "abonnement")  # dans l'ordre des boutons radio


def make_engine(name: str):
    from revise.engines.claude_code import ClaudeCodeEngine
    from revise.engines.embedded import EmbeddedEngine
    from revise.engines.simple import SimpleEngine
    return {"ia": EmbeddedEngine, "en-ligne": online.OnlineEngine, "simple": SimpleEngine,
            "abonnement": ClaudeCodeEngine}[name]()


class KeyDialog(QDialog):
    """Réglages de l'IA en ligne : une clé gratuite par service (facultatives), le service essayé en premier,
    le service sans clé ; adresse et modèle d'un autre service pour ceux qui savent."""

    KEYED = [p for p in online.PROVIDERS if p not in (online.KEYLESS, "autre")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurer l'IA en ligne")
        self.resize(760, 560)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("scrollBody")
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        lay = QVBoxLayout(body)
        lay.addWidget(muted(
            "L'IA en ligne marche tout de suite, sans rien faire : un service gratuit sans clé écrit les cartes, "
            "mais lentement (une réponse toutes les 45 secondes, compte un quart d'heure par cours).\n"
            "Pour aller beaucoup plus vite, crée une « clé » gratuite (un mot de passe que le service te donne) : "
            "deux minutes, une seule fois. Tu peux en mettre plusieurs : quand le quota gratuit de l'une est "
            "épuisé, l'application passe toute seule à la suivante."))
        cfg = config.load()
        keys = online._keys(cfg)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.keys: dict[str, QLineEdit] = {}
        for i, provider in enumerate(self.KEYED):
            label, _, _, page = online.PROVIDERS[provider]
            name = QLabel(f"<b>{label}</b>")
            link = QLabel(f"<a href='{page}' style='color:#8aa3ff'>créer une clé</a>")
            link.setOpenExternalLinks(True)
            link.setToolTip(page)
            edit = QLineEdit(keys.get(provider, ""))
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText("colle ta clé ici (facultatif)")
            edit.textChanged.connect(self._fill_first)
            self.keys[provider] = edit
            grid.addWidget(name, i, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(edit, i, 1)
            grid.addWidget(link, i, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addWidget(muted("Groq et Cerebras sont les plus rapides. Sur la page du service : crée un compte "
                            "gratuit, clique sur le bouton qui crée une clé (« API key »), copie-la et colle-la ici."))

        self.first = QComboBox()
        self.first.setToolTip("Les autres services qui ont une clé servent de secours, dans l'ordre de la liste.")
        lay.addLayout(row(muted("Essayer d'abord :"), self.first, None))
        self.keyless = QCheckBox("Utiliser le service sans clé (Pollinations) quand aucune clé ne marche")
        self.keyless.setChecked(online.keyless_allowed())
        lay.addWidget(self.keyless)

        self.advanced = QCheckBox("Autre service compatible OpenAI (adresse, modèle, clé)")
        self.url, self.model, self.other_key = QLineEdit(), QLineEdit(), QLineEdit()
        self.url.setPlaceholderText("https://…/v1")
        self.model.setPlaceholderText("nom du modèle")
        self.other_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.other_key.setPlaceholderText("clé")
        other = online.settings("autre")
        self.url.setText(other["url"])
        self.model.setText(other["model"])
        self.other_key.setText(keys.get("autre", ""))
        self.other_box = QWidget()
        form = QFormLayout(self.other_box)
        form.setContentsMargins(24, 0, 0, 0)
        form.addRow("Adresse :", self.url)
        form.addRow("Modèle :", self.model)
        form.addRow("Clé :", self.other_key)
        for w in (self.url, self.model, self.other_key):
            w.textChanged.connect(self._fill_first)
        self.advanced.setChecked(bool(other["url"] or keys.get("autre")))
        self.other_box.setVisible(self.advanced.isChecked())
        self.advanced.toggled.connect(self.other_box.setVisible)
        lay.addWidget(self.advanced)
        lay.addWidget(self.other_box)
        lay.addWidget(muted("Les clés restent sur cet ordinateur. Le texte de tes cours est envoyé au service "
                            "qui écrit les cartes."))
        lay.addStretch(1)
        buttons = save_cancel_buttons()
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._wanted_first = online.preferred()
        self._fill_first()

    def _entered(self) -> dict[str, str]:
        out = {p: e.text().strip() for p, e in self.keys.items() if e.text().strip()}
        if self.other_key.text().strip() and self.url.text().strip() and self.model.text().strip():
            out["autre"] = self.other_key.text().strip()
        return out

    def _fill_first(self, *_) -> None:
        current = self.first.currentData() or self._wanted_first
        self.first.blockSignals(True)
        self.first.clear()
        for provider in [p for p in online.FALLBACK_ORDER if p in self._entered()] + [online.KEYLESS]:
            self.first.addItem(online.PROVIDERS[provider][0], provider)
        self.first.setCurrentIndex(max(0, self.first.findData(current)))
        self.first.blockSignals(False)

    def _save(self) -> None:
        keys = self._entered()
        first = self.first.currentData() or online.KEYLESS
        if not keys and not self.keyless.isChecked():
            QMessageBox.warning(self, "Aucune clé", "Colle au moins une clé, ou garde le service sans clé.")
            return
        if first == online.KEYLESS and keys and not self.keyless.isChecked():
            first = next(p for p in online.FALLBACK_ORDER if p in keys)
        cfg = config.load()
        models = cfg.get("online_models") if isinstance(cfg.get("online_models"), dict) else {}
        values = {"online_keys": keys, "online_key": "", "online_keyless": self.keyless.isChecked(),
                  "online_provider": first, "online_url": self.url.text().strip(),
                  "online_models": {**models, "autre": self.model.text().strip()}}
        if first != cfg.get("online_provider"):
            values["online_model"] = ""  # modèle propre à l'ancien service choisi
        config.save(values)
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
                                  "Donne un cours (PDF, PowerPoint, Word ou texte) : l'application en tire des "
                                  "cartes de révision, une fiche et des QCM. Un cours partagé (fichier .revise) "
                                  "s'ajoute aussi ici."))

        lay.setSpacing(8)
        lay.addLayout(step_header(1, "Choisis tes cours"))
        self.drop = QFrame()
        self.drop.setObjectName("drop")
        dl = QHBoxLayout(self.drop)
        dl.setContentsMargins(20, 16, 20, 16)
        drop_text = QLabel("Glisse tes cours ici")
        drop_text.setObjectName("section")
        add_btn = QPushButton("Choisir des fichiers…")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self.browse)
        self.scan_btn = QPushButton("Chercher sur cet ordinateur")
        self.scan_btn.setToolTip("Liste les PDF, PowerPoint et Word des dossiers Téléchargements et Documents.")
        self.scan_btn.clicked.connect(lambda: self.scan())
        dl.addWidget(drop_text)
        dl.addWidget(muted("ou"))
        dl.addWidget(add_btn)
        dl.addWidget(self.scan_btn)
        dl.addStretch(1)
        lay.addWidget(self.drop)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un fichier dans la liste…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.count_label = muted("")
        self.count_label.setWordWrap(False)
        lay.addLayout(row(self.search, self.count_label))
        self.files = QListWidget()
        self.files.setMinimumHeight(190)  # au moins 5 fichiers visibles
        lay.addWidget(self.files, 1)

        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.setMinimumWidth(320)
        self.subject.setToolTip("Sert à regrouper les cours. Tu peux taper un nouveau nom (ex. Histoire).")
        lay.addLayout(row(muted("Matière :"), self.subject, None))

        lay.addSpacing(6)
        lay.addLayout(step_header(2, "Qui écrit les cartes ?"))
        self.engine_group = QButtonGroup(self)
        self.r_ia = QRadioButton("L'IA de cet ordinateur (conseillé)")
        self.r_online = QRadioButton("L'IA en ligne")
        self.r_simple = QRadioButton("Sans IA")
        self.r_claude = QRadioButton("Mon abonnement Claude")
        key_btn = QPushButton("Configurer…")
        key_btn.clicked.connect(self.edit_key)
        self.key_state = muted("")
        self.key_state.setWordWrap(False)
        details = {
            self.r_ia: "Gratuit, privé, sans compte. Lent : plusieurs minutes par cours, et un gros téléchargement "
                       "la première fois (2,5 à 7 Go).",
            self.r_online: "Gratuit, et marche sans rien régler (environ un quart d'heure par cours). Avec une "
                           "clé gratuite (2 minutes à créer) : quelques secondes. Le texte du cours est envoyé "
                           "sur Internet.",
            self.r_simple: "Immédiat, mais cartes approximatives à corriger et QCM facile.",
            self.r_claude: "Rapide et de très bonne qualité, sans clé : passe par Claude Code, installé et connecté "
                           "sur cet ordinateur. Lit aussi les pages scannées et les schémas des PDF. "
                           "Compte dans les limites de ton abonnement.",
        }
        has_claude = claude_binary() is not None  # proposé seulement à ceux qui ont Claude Code
        self.claude_model = QComboBox()
        for key, label in CLAUDE_MODELS.items():
            self.claude_model.addItem(label, key)
        saved_model = config.load().get("claude_model", "")
        self.claude_model.setCurrentIndex(max(0, self.claude_model.findData(saved_model)))
        self.claude_model.setToolTip("Le modèle de Claude qui écrit les cartes, les réponses pièges et les "
                                     "explications. Opus consomme plus vite les limites de l'abonnement.")
        self.claude_model.currentIndexChanged.connect(
            lambda: config.save({"claude_model": self.claude_model.currentData()}))
        claude_model_label = muted("Modèle :")
        claude_model_label.setWordWrap(False)
        for i, r in enumerate((self.r_ia, self.r_online, self.r_simple, self.r_claude)):
            self.engine_group.addButton(r, i)
            font = r.font()
            font.setBold(True)
            r.setFont(font)
            if r is self.r_online:
                lay.addLayout(row(r, key_btn, self.key_state, None))
            elif r is self.r_claude:
                lay.addLayout(row(r, claude_model_label, self.claude_model, None))
            else:
                lay.addWidget(r)
            detail = muted(details[r])
            detail.setContentsMargins(30, 0, 0, 4)
            lay.addWidget(detail)
            if r is self.r_claude:
                for w in (r, detail, claude_model_label, self.claude_model):
                    w.setVisible(has_claude)
        saved = config.load().get("engine")
        if saved not in ENGINES or (saved == "abonnement" and not has_claude):
            saved = "ia"
        self.engine_group.button(ENGINES.index(saved)).setChecked(True)
        self._update_key_state()

        lay.addSpacing(6)
        lay.addLayout(step_header(3, "C'est parti"))
        self.import_btn = QPushButton("Créer les cartes")
        self.import_btn.setObjectName("primary")
        self.import_btn.setMinimumHeight(46)
        self.import_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Arrêter après ce cours")
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
        if str(path) in self._known_paths() or not (shared or documents.is_supported(path)) or not path.is_file():
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
                found += [p for p in base.rglob("*") if p.suffix.lower() in SCAN_SUFFIXES
                          and len(p.relative_to(base).parts) <= 3 and not p.name.startswith(("~$", "."))]
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
                                                "Cours (*.pdf *.pptx *.docx *.txt *.md *.revise);;PDF (*.pdf);;"
                                                "PowerPoint (*.pptx);;Word (*.docx);;Texte (*.txt *.md);;"
                                                "Cours partagés (*.revise)")
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
                for f in sorted(f for f in p.rglob("*") if f.suffix.lower() in SCAN_SUFFIXES):
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
            self.count_label.setText(f"{n} fichier{'s' if n > 1 else ''} coché{'s' if n > 1 else ''}")
        else:
            self.count_label.setText("Coche les cours à transformer" if self.files.count() else "Aucun fichier choisi")
        self.import_btn.setEnabled(n > 0 and self._thread is None)
        self.import_btn.setText(f"Créer les cartes de {n} cours" if n > 1 else "Créer les cartes")

    # --------------------------------------------------------------- import
    def engine_name(self) -> str:
        return ENGINES[self.engine_group.checkedId()]

    def _update_key_state(self) -> None:
        self.key_state.setText(online.describe())

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
        if needs_ai and engine == "en-ligne" and not online.chain() and not self.edit_key():
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
            self.status.setText("Arrêt après le cours en train d'être lu…")

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
