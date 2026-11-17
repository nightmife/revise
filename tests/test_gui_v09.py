"""Interface 0.9 : réponse tapée, carte réécrite, page du cours, examen blanc, points faibles, thème clair,
mise à jour des cours, recherche dans un dossier choisi, progression de l'import."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from revise import config
from revise.gui import theme
from revise.gui.app import MainWindow
from revise.models import CardDraft


def wait(qapp, cond, tries=400):
    for _ in range(tries):
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_typed_answer_is_checked_and_letters_are_not_shortcuts(qapp, db):
    deck = db.add_deck("Algo", "Piles", None, None, "simple",
                       [CardDraft("cloze", "Une pile est de type [...]", "LIFO", 1)])
    win = MainWindow(db)
    win.show()
    rv = win.review
    rv.type_toggle.setChecked(True)
    assert config.load()["type_answers"] is True
    win.start_review([deck], False, False, 20)
    qapp.processEvents()
    assert rv.typed.isVisible()
    rv.typed.setFocus()
    QTest.keyClicks(rv.typed, "lifo es")              # « e » et « s » sont aussi des raccourcis de la page
    assert rv.typed.text() == "lifo es" and rv.card is not None and not rv.card.suspended
    QTest.keyClick(rv.typed, Qt.Key.Key_Backspace)
    QTest.keyClick(rv.typed, Qt.Key.Key_Backspace)
    QTest.keyClick(rv.typed, Qt.Key.Key_Backspace)
    QTest.keyClick(rv.typed, Qt.Key.Key_Return)
    assert rv.revealed and rv.verdict == "juste" and "Juste" in rv.check_label.text()
    assert "conseillé" in rv.rate_btns[3].text()
    rv.rate(4)                                         # Facile : la carte ne revient pas aujourd'hui
    assert rv.card is None
    win.close()


def test_bad_card_is_rewritten_by_ai_and_page_shown(qapp, db, tmp_path, monkeypatch):
    src = tmp_path / "cours.txt"
    src.write_text("Une pile est une structure LIFO : dernier entré, premier sorti.", encoding="utf-8")
    deck = db.add_deck("Algo", "Piles", str(src), None, "simple",
                       [CardDraft("qa", "Pile ?", "coupée…", 1)])

    class FakeAI:
        def __init__(self):
            self.asked = []

        def chat(self, system, user, schema):
            self.asked.append(user)
            return '{"question": "Qu\'est-ce qu\'une pile ?", "answer": "Une structure LIFO.", "change": "précisée"}'

    win = MainWindow(db)
    win.show()
    rv = win.review
    ai = FakeAI()
    rv.engine_factory = lambda: ai
    from revise.gui import review
    monkeypatch.setattr(review.RewriteDialog, "exec", lambda self: True)
    win.start_review([deck], False, False, 20)
    qapp.processEvents()
    assert rv.page_btn.isVisible() and rv.fix_btn.isVisible()
    rv.fix_btn.click()
    assert wait(qapp, lambda: not rv.ai_busy)
    assert "dernier entré" in ai.asked[0]                # le texte de la page est donné à l'IA
    card = db.cards(deck_id=deck)[0]
    assert card.question == "Qu'est-ce qu'une pile ?" and card.answer == "Une structure LIFO."
    assert "Qu'est-ce qu'une pile" in rv.question.toPlainText()

    from revise.gui.page_dialog import PageDialog
    dlg = PageDialog(db, db.deck(deck), 1, win)
    assert "LIFO" in dlg.text.toPlainText() and dlg.open_btn.isVisibleTo(dlg)
    src.unlink()
    lost = PageDialog(db, db.deck(deck), 1, win)
    assert lost.locate_btn.isVisibleTo(lost) and "n'est plus à sa place" in lost.info.text()
    moved = tmp_path / "rangé.txt"
    moved.write_text("Une pile est une structure LIFO : dernier entré, premier sorti.", encoding="utf-8")
    monkeypatch.setattr("revise.gui.page_dialog.confirm", lambda *a, **k: True)
    assert lost.relocate(moved) and db.deck(deck).source == str(moved.resolve())
    win.close()


def test_mock_exam_flow_and_weak_points(qapp, db, tmp_path):
    drafts = [CardDraft("qa", f"Capitale numéro {i} ?", f"Ville{i}", i + 1) for i in range(6)]
    deck = db.add_deck("Géo", "Capitales", None, None, "simple", drafts)
    win = MainWindow(db)
    win.resize(1280, 690)
    win.show()
    win.show_page(win.EXAM)
    ex = win.exam
    assert win.current_page() is ex and ex.start_btn.isEnabled()
    ex.count.setValue(4)
    ex.duration.setValue(0)
    ex.mix.setCurrentIndex(0)
    ex.start()
    assert ex.pages.currentIndex() == 1 and len(ex.questions) == 4
    win.grab().save(str(tmp_path / "examen.png"))
    wrong = None
    for n in range(4):
        q = ex.current()
        if q.mode == "qcm":
            ex.choose(q.correct if n else (q.correct + 1) % len(q.choices))
            if not n:
                wrong = q.card.id
        else:
            ex.written.setPlainText(q.card.answer if n else "je ne sais pas")
            if not n:
                wrong = q.card.id
        ex.next_btn.click()
    assert ex.pages.currentIndex() == 2 and ex.note.text() == "15 / 20"
    win.grab().save(str(tmp_path / "resultat.png"))
    weak = [w.card.id for w in __import__("revise.weak", fromlist=["x"]).weak_cards(db)]
    assert weak == [wrong]
    first = ex.correction.item(0)
    if first.flags() & Qt.ItemFlag.ItemIsUserCheckable:   # réponse écrite : l'étudiant peut la compter juste
        first.setCheckState(Qt.CheckState.Checked)
        assert ex.note.text() == "20 / 20"

    win.show_page(win.STATS)
    st = win.stats
    if ex.note.text() == "15 / 20":
        assert st.weak_list.count() == 1 and st.weak_btn.isVisible()
        st.weak_btn.click()
        qapp.processEvents()
        assert win.current_page() is win.review and [c.id for c in win.review.session.queue] == [wrong]
        win.review.finished.emit()
        assert win.current_page() is win.stats
    win.close()


def test_light_theme_switch(qapp, db):
    win = MainWindow(db)
    win.show()
    assert win.theme_btn.text() == "Apparence : sombre"
    win.theme_btn.click()
    assert config.load()["theme"] == "clair" and not theme.is_dark()
    assert theme.LIGHT["SURFACE"] in qapp.styleSheet() and win.theme_btn.text() == "Apparence : clair"
    win.theme_btn.click()
    assert config.load()["theme"] == "automatique"
    win.theme_btn.click()
    assert config.load()["theme"] == "sombre" and theme.is_dark() and theme.DARK["SURFACE"] in qapp.styleSheet()
    win.close()


def test_update_courses_dialog_with_simple_engine(qapp, db, tmp_path):
    src = tmp_path / "cours.txt"
    src.write_text("Piles\n• Une pile est une structure de donnée où seul le sommet est accessible\n", encoding="utf-8")
    deck = db.add_deck("Algo", "Piles", str(src), None, "ia",
                       [CardDraft("qa", "Qu'est-ce qu'une pile ?", "Une structure", 1),
                        CardDraft("qa", "Carte ratée de l'ancienne version", "???", 1)])
    win = MainWindow(db)
    win.show()
    win.show_page(win.COURSES)
    assert win.courses.outdated_note.isVisible()
    from revise.gui.update_courses import UpdateCoursesDialog
    dlg = UpdateCoursesDialog(db, [deck], win)
    dlg.engine.setCurrentIndex(dlg.engine.findData("simple"))
    assert dlg.start_btn.isEnabled()
    dlg.start()
    assert wait(qapp, lambda: dlg.worker is None)
    assert dlg.updated == 1 and dlg.progress.value() == 1000
    questions = [c.question for c in db.cards(deck_id=deck)]
    assert "Qu'est-ce qu'une pile ?" in questions and "Carte ratée de l'ancienne version" not in questions
    assert db.deck(deck).gen_version is not None and db.deck(deck).engine == "simple"
    win.courses.refresh()
    assert not win.courses.outdated_note.isVisible()
    win.close()


def test_import_page_scans_chosen_folder_and_shows_progress(qapp, db, tmp_path):
    folder = tmp_path / "bazar" / "fac" / "L2"
    folder.mkdir(parents=True)
    (folder / "algo.txt").write_text("x")             # fichiers texte : pas proposés par la recherche
    (folder / "CM1.docx").write_bytes(b"pas un vrai docx")
    (tmp_path / "bazar" / "cours.pdf").write_bytes(b"%PDF")
    win = MainWindow(db)
    win.show()
    page = win.import_page
    page.set_dirs([str(tmp_path / "bazar")])
    assert wait(qapp, lambda: not page.scanning)
    labels = [page.files.item(i).text() for i in range(page.files.count())]
    assert any(l.startswith("CM1.docx") and "bazar/fac/L2" in l for l in labels)
    assert any(l.startswith("cours.pdf") for l in labels) and len(labels) == 2
    assert "bazar" in page.dirs_label.text() and page.reset_dirs_btn.isVisibleTo(page)
    page.search.setText("fac/l2")
    assert sum(not page.files.item(i).isHidden() for i in range(page.files.count())) == 1
    page.reset_dirs()
    assert wait(qapp, lambda: not page.scanning) and config.load()["scan_dirs"] == []

    page.eta.restart()
    page._files_total, page._files_done = 2, 0
    page._on_status("cours.pdf : morceau 1/4", 0.25, "work")
    assert page.progress.value() == 250
    page._on_status("Téléchargement de l'IA : 40 %", 0.4, "download")
    assert page.progress.value() == 400 and page.progress.format().startswith("Téléchargement")
    win.close()


def test_eta_text():
    from revise.gui.common import Eta
    now = [0.0]
    eta = Eta(lambda: now[0])
    assert eta.text(0.5) == "calcul du temps restant…"
    now[0] = 120
    assert eta.text(0.5) == "environ 2 min restantes"
    assert eta.text(0.95) == "moins d'une minute restante"
    assert eta.text(1.0) == ""
