"""Fenêtre principale."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from revise import __version__, selfupdate, updates
from revise.db import Database
from revise.gui import theme
from revise.gui.backup_dialog import BackupDialog
from revise.gui.cards_dialog import CardsDialog
from revise.gui.common import confirm
from revise.gui.courses import CoursesPage
from revise.gui.import_page import ImportPage
from revise.gui.learn_page import LearnPage
from revise.gui.quiz_page import QuizPage
from revise.gui.review import ReviewPage
from revise.gui.stats_page import StatsPage
from revise.gui.update_dialog import UpdateDialog


class MainWindow(QMainWindow):
    COURSES, LEARN, QUIZ, IMPORT, STATS = range(5)  # index des pages = identifiants des boutons
    update_found = Signal(object)  # updates.Release, émis depuis le fil qui interroge Internet

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setWindowTitle("revise")
        self.resize(1180, 780)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(196)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(0, 0, 0, 12)
        name = QLabel("revise")
        name.setObjectName("appname")
        tag = QLabel("Tes cours en PDF,\nen cartes et en QCM")
        tag.setObjectName("tagline")
        sl.addWidget(name)
        sl.addWidget(tag)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)

        self.stack = QStackedWidget()
        self.courses = CoursesPage(db)
        self.learn = LearnPage(db)
        self.quiz = QuizPage(db)
        self.import_page = ImportPage(db)
        self.stats = StatsPage(db)
        self.review = ReviewPage(db)
        for page in (self.courses, self.learn, self.quiz, self.import_page, self.stats, self.review):
            self.stack.addWidget(page)
        # Ordre du menu = ordre dans lequel on s'en sert ; les identifiants restent les index des pages.
        for label, i in (("Mes cours", self.COURSES), ("Ajouter un cours", self.IMPORT), ("Lire la fiche", self.LEARN),
                         ("QCM", self.QUIZ), ("Mes progrès", self.STATS)):
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            self.nav.addButton(b, i)
            sl.addWidget(b)
        sl.addStretch(1)
        self.update_btn = QPushButton()
        self.update_btn.setObjectName("update")
        self.update_btn.setVisible(False)
        self.update_btn.clicked.connect(self.install_update)
        self.release: updates.Release | None = None
        self.update_found.connect(self.show_update)
        sl.addWidget(self.update_btn)
        self.backup_btn = QPushButton("Sauvegarde…")
        self.backup_btn.setObjectName("side")
        self.backup_btn.setToolTip("Mettre tes cours et ta progression à l'abri dans un fichier, ou les récupérer.")
        self.backup_btn.clicked.connect(self.open_backup)
        sl.addWidget(self.backup_btn)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("tagline")
        sl.addWidget(ver)
        self.nav.idClicked.connect(self.show_page)

        h.addWidget(self.sidebar)
        h.addWidget(self.stack, 1)

        self.courses.start_review.connect(self.start_review)
        self.courses.edit_cards.connect(self.edit_cards)
        self.courses.go_import.connect(lambda: self.show_page(self.IMPORT))
        self.courses.open_learn.connect(lambda ids: self.open_with(self.LEARN, ids))
        self.courses.open_quiz.connect(lambda ids: self.open_with(self.QUIZ, ids))
        self.review.finished.connect(self.end_review)
        self.import_page.imported.connect(self.courses.refresh)
        self.show_page(self.COURSES if db.subjects() else self.IMPORT)

    def show_page(self, i: int) -> None:
        self.nav.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        if i == self.COURSES:
            self.courses.refresh()
        elif i == self.LEARN:
            self.learn.refresh()
        elif i == self.QUIZ:
            self.quiz.refresh()
        elif i == self.IMPORT:
            self.import_page.refresh_subjects()
        elif i == self.STATS:
            self.stats.refresh()

    def open_with(self, i: int, deck_ids: list) -> None:
        """Ouvre « Lire la fiche » ou « QCM » sur les cours cochés dans « Mes cours »."""
        page = self.learn if i == self.LEARN else self.quiz
        page.set_scope([int(d) for d in deck_ids])
        self.nav.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)

    def start_review(self, deck_ids: list, exam: bool, include_known: bool, new_per_day: int) -> None:
        self.sidebar.setEnabled(False)
        self.stack.setCurrentWidget(self.review)
        self.review.start([int(d) for d in deck_ids], exam, include_known, new_per_day)

    def end_review(self) -> None:
        if not self.review.ai_busy:
            self.review.stop_engine()  # l'IA des explications ne reste pas en mémoire après la séance
        self.sidebar.setEnabled(True)
        self.show_page(self.COURSES)

    def edit_cards(self, deck_id: int) -> None:
        CardsDialog(self.db, deck_id, self).exec()
        self.courses.refresh()

    # ------------------------------------------------------------ mise à jour
    def check_updates(self, opener=None) -> None:
        """Demande en arrière-plan s'il existe une version plus récente ; sans réponse, il ne se passe rien."""
        def work() -> None:
            release = updates.available_update(opener) if opener else updates.available_update()
            if release:
                try:
                    self.update_found.emit(release)
                except RuntimeError:  # fenêtre déjà fermée
                    pass
            selfupdate.cleanup_leftovers()  # l'ancienne version, gardée le temps de la dernière mise à jour
        threading.Thread(target=work, name="revise-maj", daemon=True).start()

    def show_update(self, release: updates.Release) -> None:
        self.release = release
        auto = selfupdate.can_install()
        self.update_btn.setText(f"Nouvelle version {release.version}\n{'L’installer' if auto else 'La télécharger'}")
        self.update_btn.setToolTip("Télécharge et installe la nouvelle version, puis relance l'application." if auto
                                   else "Ouvre la page de téléchargement dans le navigateur.")
        self.update_btn.setVisible(True)

    def install_update(self) -> None:
        if self.release is None:
            return
        if not selfupdate.can_install():  # lancée depuis le code source (Linux) : pas d'exécutable à remplacer
            QDesktopServices.openUrl(QUrl(updates.DOWNLOAD_PAGE))
            return
        if self.busy():
            QMessageBox.information(self, "Mise à jour", "L'IA travaille encore : attends qu'elle ait fini, "
                                                         "puis relance la mise à jour.")
            return
        dialog = UpdateDialog(self.release, self)
        dialog.exec()
        if dialog.installed:
            kind, target = dialog.installed
            try:
                selfupdate.relaunch(kind, Path(target))
            except OSError:
                QMessageBox.information(self, "Mise à jour", "La nouvelle version est installée : rouvre revise.")
            self.db.close()
            QApplication.quit()

    # ------------------------------------------------------------- sauvegarde
    def busy(self) -> bool:
        """L'IA écrit dans la base (import ou réponses pièges en cours)."""
        return self.import_page.worker is not None or self.quiz.worker is not None

    def open_backup(self) -> None:
        dialog = BackupDialog(self.db, self.busy(), self)
        dialog.exec()
        if dialog.restored:
            self.import_page.scan(search=self.import_page._scanned)
            self.show_page(self.COURSES)

    def closeEvent(self, e) -> None:
        workers = [w for w in (self.import_page.worker, self.quiz.worker) if w is not None]
        if self.review.ai_busy:
            workers.append(self.review)
        if workers:
            if not confirm(self, "L'IA travaille encore", "L'IA est en train de travailler. Quitter quand même ?\n"
                           "(ce qui est déjà terminé est enregistré)", "Quitter"):
                e.ignore()
                return
            import os
            for w in workers:
                w.stop_engine()
            self.db.close()
            os._exit(0)  # le PDF en cours est abandonné ; sa transaction n'est pas validée
        self.review.stop_engine()
        super().closeEvent(e)


def main(db: Database | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("revise")
    app.setDesktopFileName("revise")
    font = QFont(app.font())
    font.setPointSizeF(11)
    app.setFont(font)
    app.setStyleSheet(theme.QSS)
    app.setWindowIcon(theme.app_icon())
    translator = QTranslator(app)  # textes de Qt lui-même (clic droit, fenêtre de choix de fichiers) en français
    if translator.load("qtbase_fr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    win = MainWindow(db or Database())
    win.show()
    win.check_updates()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
