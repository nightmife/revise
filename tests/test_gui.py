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

    win.show_page(2)
    win.grab().save(str(tmp_path / "stats.png"))
    win.show_page(1)
    assert (tmp_path / "revision.png").stat().st_size > 1000
    win.close()
