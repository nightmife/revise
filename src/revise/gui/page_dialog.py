"""Fenêtre « Page du cours » : la page du PDF d'où vient une carte (ou son texte)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QPushButton, QScrollArea, QTextBrowser, QVBoxLayout

from revise import pageview
from revise.db import Database, Deck, deck_label, file_sha256
from revise.gui.common import confirm, muted, row
from revise.importer import source_file


class PageDialog(QDialog):
    def __init__(self, db: Database, deck: Deck, page: int, parent=None):
        super().__init__(parent)
        self.db, self.deck, self.page = db, deck, page
        self.zoom = 1.0
        self.image: pageview.PageImage | None = None
        self.setWindowTitle(f"{deck_label(deck)} — page {page}")
        self.resize(900, 760)
        lay = QVBoxLayout(self)
        self.info = muted("")
        lay.addWidget(self.info)
        self.area = QScrollArea()
        self.area.setWidgetResizable(False)
        self.area.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.picture = QLabel()
        self.area.setWidget(self.picture)
        self.text = QTextBrowser()
        lay.addWidget(self.area, 1)
        lay.addWidget(self.text, 1)
        self.minus = QPushButton("−")
        self.plus = QPushButton("+")
        self.minus.setToolTip("Réduire")
        self.plus.setToolTip("Agrandir")
        self.minus.clicked.connect(lambda: self.set_zoom(self.zoom / 1.25))
        self.plus.clicked.connect(lambda: self.set_zoom(self.zoom * 1.25))
        self.locate_btn = QPushButton("Retrouver le fichier…")
        self.locate_btn.clicked.connect(self.locate)
        self.open_btn = QPushButton("Ouvrir le fichier")
        self.open_btn.setToolTip("Ouvre le cours complet dans l'application habituelle de l'ordinateur.")
        self.open_btn.clicked.connect(self.open_file)
        close = QPushButton("Fermer")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        lay.addLayout(row(self.minus, self.plus, None, self.locate_btn, self.open_btn, close))
        self.load()

    def load(self) -> None:
        path = source_file(self.deck)
        self.locate_btn.setVisible(path is None)
        self.open_btn.setVisible(path is not None)
        self.image = pageview.render_page(path, self.page) if path else None
        has_image = self.image is not None
        for w in (self.area, self.minus, self.plus):
            w.setVisible(has_image)
        self.text.setVisible(not has_image)
        if path is None:
            self.info.setText("Le fichier de ce cours n'est plus à sa place"
                              + (f" ({self.deck.source})" if self.deck.source else "")
                              + ". Clique sur « Retrouver le fichier… » pour le montrer à l'application.")
            self.text.setPlainText("")
            return
        if has_image:
            self.info.setText(f"Page {self.page} de {path.name}")
            fit = max(0.3, min(1.0, (self.width() - 60) / max(1, self.image.width)))
            self.set_zoom(fit)
            return
        text = pageview.page_text(path, self.page)
        self.info.setText(f"Texte de la page {self.page} de {path.name}"
                          + ("" if path.suffix.lower() != ".pdf" or pageview.can_render()
                             else " (l'image de la page demande le module pypdfium2)"))
        self.text.setPlainText(text or "(aucun texte lisible sur cette page)")

    def set_zoom(self, value: float) -> None:
        if self.image is None:
            return
        self.zoom = max(0.2, min(3.0, value))
        fmt = QImage.Format.Format_RGBA8888 if self.image.channels == 4 else QImage.Format.Format_RGB888
        img = QImage(self.image.data, self.image.width, self.image.height, self.image.stride, fmt)
        pix = QPixmap.fromImage(img)
        w = int(self.image.width * self.zoom)
        self.picture.setPixmap(pix.scaledToWidth(max(50, w), Qt.TransformationMode.SmoothTransformation))
        self.picture.adjustSize()

    def open_file(self) -> None:
        path = source_file(self.deck)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def locate(self) -> None:
        start = str(Path(self.deck.source).parent) if self.deck.source else str(Path.home())
        chosen, _ = QFileDialog.getOpenFileName(self, "Où est ce cours ?", start,
                                                "Cours (*.pdf *.pptx *.docx *.txt *.md)")
        if chosen:
            self.relocate(Path(chosen))

    def relocate(self, path: Path) -> bool:
        """Enregistre le nouvel emplacement du cours (après confirmation si le fichier a changé)."""
        row_ = self.db.conn.execute("SELECT sha256 FROM decks WHERE id = ?", (self.deck.id,)).fetchone()
        same = row_ is not None and row_[0] == file_sha256(path)
        if not same and not confirm(self, "Fichier différent",
                                    f"{path.name} n'est pas exactement le fichier importé (il a peut-être été modifié). "
                                    "L'utiliser quand même pour ce cours ?", "L'utiliser"):
            return False
        self.db.set_deck_source(self.deck.id, str(path.resolve()))
        self.deck = self.db.deck(self.deck.id) or self.deck
        self.load()
        return True
