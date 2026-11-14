"""Fenêtre principale."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from revise import __version__
from revise.db import Database
from revise.gui import theme
from revise.gui.cards_dialog import CardsDialog
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
        tag = QLabel("Tes CM en cartes\nde révision")
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
        for i, (label, page) in enumerate((("Mes cours", self.courses), ("Apprendre", self.learn),
                                           ("QCM", self.quiz), ("Importer", self.import_page),
                                           ("Statistiques", self.stats))):
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            self.nav.addButton(b, i)
            sl.addWidget(b)
            self.stack.addWidget(page)
        self.stack.addWidget(self.review)
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
        if self.import_page.worker is not None:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, "Import en cours",
                                    "Un import est en cours. Quitter quand même ?\n"
                                    "(les cours déjà terminés sont enregistrés)") != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            import os
            self.import_page.worker.stop_engine()
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
    app.setWindowIcon(QIcon.fromTheme("accessories-dictionary"))
    win = MainWindow(db or Database())
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
