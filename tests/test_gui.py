"""Interface graphique testée hors écran (QT_QPA_PLATFORM=offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from revise.gui import theme
from revise.gui.app import MainWindow
from revise.models import CardDraft


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.QSS)
    return app


def test_select_courses_and_exam_flow(qapp, db, tmp_path):
    d1 = db.add_deck("LIFAPSD", "Les piles", "/dl/[LIFAPSD] CM8 - Pile et file.pdf", None, "abonnement",
                     [CardDraft("qa", "Qu'est-ce qu'une **pile** ?", "Structure LIFO.", 3),
                      CardDraft("cloze", "Une file est de type [...]", "FIFO", 33)])
    db.add_deck("LIFAPSD", "Arbres", "/dl/[LIFAPSD] CM9 - Arbre.pdf", None, "abonnement",
                [CardDraft("qa", "Hauteur d'un arbre ?", "Plus long chemin racine-feuille.", 5)])
    win = MainWindow(db)
    win.resize(1180, 780)
    win.show()
    qapp.processEvents()
    page = win.courses
    root = page.tree.topLevelItem(0)
    assert root.text(0) == "LIFAPSD" and root.childCount() == 2
    assert root.child(0).text(0) == "CM8 - Pile et file"      # nom du fichier, pas le titre généré
    assert not page.exam_btn.isEnabled()
    root.child(0).setCheckState(0, Qt.CheckState.Checked)
    assert page.selected_decks() == [d1] and page.exam_btn.isEnabled()
    win.grab().save(str(tmp_path / "cours.png"))

    page.exam_btn.click()
    qapp.processEvents()
    rv = win.review
    assert win.stack.currentWidget() is rv and rv.exam and rv.total == 2
    assert rv.reveal_btn.isVisible() and not rv.rate_btns[3].isVisible()
    rv.reveal_btn.click()
    assert rv.rate_btns[3].isVisible() and "Bien" in rv.rate_btns[3].text()
    win.grab().save(str(tmp_path / "revision.png"))
    rv.rate_btns[1].click()            # À revoir → repasse en fin de file
    assert rv.session.remaining == 2
    for _ in range(3):
        if rv.card is None:
            break
        rv.reveal_btn.click()
        rv.rate_btns[3].click()
    assert rv.card is None and rv.back_btn.isVisible()
    rv.back_btn.click()
    assert win.stack.currentWidget() is win.courses
    assert win.courses.tree.topLevelItem(0).child(0).text(4) == "2"   # 2 cartes sues

    win.show_page(win.STATS)
    win.grab().save(str(tmp_path / "stats.png"))
    win.show_page(win.IMPORT)
    assert (tmp_path / "revision.png").stat().st_size > 1000
    win.close()


def test_quiz_and_learn_pages(qapp, db, tmp_path):
    drafts = [CardDraft("qa", f"Question {i} ?", f"Réponse {i}", i + 1, "Partie A" if i < 3 else "Partie B")
              for i in range(5)]
    drafts.append(CardDraft("cloze", "Une pile est une structure [...].", "LIFO", 6, "Partie B"))
    db.add_deck("Algo", "CM1", None, None, "simple", drafts)
    win = MainWindow(db)
    win.show()
    qapp.processEvents()

    win.show_page(win.LEARN)
    learn = win.learn
    assert win.stack.currentWidget() is learn and learn.list.count() == 2
    assert "Question 0" in learn.view.toPlainText() and not learn.prev_btn.isEnabled()
    learn.next_btn.click()
    assert "Une pile est une structure LIFO." in learn.view.toPlainText() and not learn.next_btn.isEnabled()
    win.grab().save(str(tmp_path / "learn.png"))

    win.show_page(win.QUIZ)
    quiz = win.quiz
    assert quiz.start_btn.isEnabled()
    quiz.count.setValue(3)
    quiz.start_btn.click()
    assert quiz.pages.currentIndex() == 1 and len(quiz.questions) == 3
    q = quiz.questions[0]
    quiz.choices[q.correct].click()
    quiz.choices[(q.correct + 1) % 4].click()            # déjà répondu : ignoré
    assert quiz.score == 1 and quiz.next_btn.isVisible()
    qapp.processEvents()
    win.grab().save(str(tmp_path / "quiz.png"))
    quiz.next_btn.click()
    q = quiz.questions[1]
    quiz.choices[(q.correct + 1) % 4].click()
    assert quiz.score == 1 and len(quiz.mistakes) == 1
    quiz.next_btn.click()
    quiz.choices[quiz.questions[2].correct].click()
    quiz.next_btn.click()
    assert quiz.pages.currentIndex() == 2 and quiz.result.text() == "2 / 3" and quiz.retry_btn.isVisible()
    quiz.retry_btn.click()
    assert quiz.pages.currentIndex() == 1 and len(quiz.questions) == 1
    assert db.cards()[0].fsrs is None                     # le QCM ne touche pas au planning
    win.close()
