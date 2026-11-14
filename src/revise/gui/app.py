"""Fenêtre principale."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from revise import __version__
from revise.db import Database
from revise.gui import theme
from revise.gui.cards_dialog import CardsDialog
from revise.gui.common import confirm
from revise.gui.courses import CoursesPage
from revise.gui.import_page import ImportPage
from revise.gui.learn_page import LearnPage
from revise.gui.quiz_page import QuizPage
from revise.gui.review import ReviewPage
from revise.gui.stats_page import StatsPage


class MainWindow(QMainWindow):
    COURSES, LEARN, QUIZ, IMPORT, STATS = range(5)  # index des pages = identifiants des boutons

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
        self.sidebar.setEnabled(True)
        self.show_page(self.COURSES)

    def edit_cards(self, deck_id: int) -> None:
        CardsDialog(self.db, deck_id, self).exec()
        self.courses.refresh()

    def closeEvent(self, e) -> None:
        workers = [w for w in (self.import_page.worker, self.quiz.worker) if w is not None]
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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
