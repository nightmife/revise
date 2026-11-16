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
    assert win.current_page() is win.home          # l'application s'ouvre sur le programme du jour
    win.show_page(win.COURSES)
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
    assert win.current_page() is rv and rv.exam and rv.total == 2
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
    assert win.current_page() is win.courses
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
    assert win.current_page() is learn and learn.list.count() == 2
    assert "Question 0" in learn.view.toPlainText() and not learn.prev_btn.isEnabled()
    learn.next_btn.click()
    assert "Une pile est une structure LIFO." in learn.view.toPlainText() and not learn.next_btn.isEnabled()
    win.grab().save(str(tmp_path / "learn.png"))

    win.show_page(win.QUIZ)
    quiz = win.quiz
    assert quiz.start_btn.isEnabled() and quiz.prepare_btn.isVisible()     # aucune réponse piège préparée
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


def test_activities_open_on_checked_courses(qapp, db):
    ids = [db.add_deck("Algo", f"CM{i}", None, None, "simple",
                       [CardDraft("qa", f"Question {i}.{j} ?", f"Réponse {i}.{j}", j + 1) for j in range(3)])
           for i in range(3)]
    win = MainWindow(db)
    win.show()
    qapp.processEvents()
    page = win.courses
    assert not page.quiz_btn.isEnabled() and not page.empty.isVisible()
    root = page.tree.topLevelItem(0)
    for row in (0, 2):                                   # un clic sur la ligne suffit à cocher
        page._on_pressed(root.child(row), 0)
        page._on_clicked(root.child(row), 0)
    assert page.selected_decks() == [ids[0], ids[2]] and page.quiz_btn.isEnabled()

    page.quiz_btn.click()
    assert win.current_page() is win.quiz and win.nav.checkedId() == win.QUIZ
    assert win.quiz.scope.currentText() == "Ma sélection (2 cours)" and win.quiz.scope.currentData() == [ids[0], ids[2]]
    win.quiz.count.setValue(50)
    win.quiz.start_btn.click()
    assert {q.card.deck_id for q in win.quiz.questions} == {ids[0], ids[2]} and len(win.quiz.questions) == 6

    win.show_page(win.COURSES)
    page.learn_btn.click()
    assert win.current_page() is win.learn and win.learn.scope.currentData() == [ids[0], ids[2]]
    assert "Question 0.0" in win.learn.view.toPlainText()
    win.close()


def test_empty_app_shows_the_welcome(qapp, db):
    win = MainWindow(db)
    win.show()
    win.show_page(win.COURSES)
    qapp.processEvents()
    assert win.courses.empty.isVisible() and not win.courses.tree.isVisible() and not win.courses.review_btn.isVisible()
    win.close()


def test_prepare_traps_from_quiz_page(qapp, db, monkeypatch):
    import json

    from PySide6.QtCore import QEventLoop, QTimer

    from revise.engines import distractors

    deck = db.add_deck("Algo", "CM1", None, None, "simple",
                       [CardDraft("qa", f"Question {i} ?", f"Réponse {i}", i + 1) for i in range(12)])

    class FakeEngine:
        closed = False

        def chat(self, system, user, schema):
            count = user.count("### Question")
            return json.dumps({"items": [{"n": n, "wrong": [f"Faux {n}a", f"Faux {n}b", f"Faux {n}c"]}
                                         for n in range(1, count + 1)]})

        def close(self):
            FakeEngine.closed = True

    monkeypatch.setattr(distractors, "default_engine", lambda: FakeEngine())
    win = MainWindow(db)
    win.show()
    win.show_page(win.QUIZ)
    quiz = win.quiz
    assert "trop facile" in quiz.traps_title.text()
    loop = QEventLoop()
    quiz.start_prepare([deck])
    assert quiz.worker is not None and not quiz.prepare_btn.isEnabled()
    quiz.worker.done.connect(loop.quit)
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    qapp.processEvents()
    assert quiz.worker is None and FakeEngine.closed and "12 questions" in quiz.traps_status.text()
    assert all(len(c.distractors) == 3 for c in db.cards(deck_id=deck))
    assert "prêtes" in quiz.traps_title.text() and not quiz.prepare_btn.isVisible()
    quiz.start_btn.click()
    q = quiz.questions[0]
    assert sorted(c for i, c in enumerate(q.choices) if i != q.correct) == sorted(q.card.distractors)
    win.close()


def test_update_notice(qapp, db):
    import io
    import time
    win = MainWindow(db)
    win.show()
    assert not win.update_btn.isVisible()
    win.check_updates(opener=lambda req, timeout: io.BytesIO(b'{"tag_name": "v99.1.0"}'))
    for _ in range(200):                              # la réponse arrive d'un autre fil
        qapp.processEvents()
        if win.update_btn.isVisible():
            break
        time.sleep(0.01)
    assert win.update_btn.isVisible() and "99.1.0" in win.update_btn.text()
    assert "télécharger" in win.update_btn.text()     # pas d'exécutable à remplacer ici : renvoi vers la page
    win.close()


def test_update_dialog(qapp, db):
    import time
    from pathlib import Path

    from revise import updates
    from revise.gui.update_dialog import UpdateDialog
    from revise.models import ReviseError

    def wait(cond):
        for _ in range(300):
            qapp.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    release = updates.Release("99.0.0")

    def broken(rel, progress, cancelled):
        progress(5 << 20, 50 << 20)
        raise ReviseError("pas d'Internet")
    dialog = UpdateDialog(release, installer=broken)
    dialog.show()
    dialog.start()
    assert wait(lambda: dialog.install_btn.text() == "Réessayer")
    assert "pas d'Internet" in dialog.text.text() and dialog.installed is None and dialog.install_btn.isEnabled()

    def works(rel, progress, cancelled):
        progress(50 << 20, 50 << 20)
        return "windows", Path("C:/revise.exe")
    dialog.installer = works
    dialog.start()
    assert wait(lambda: dialog.installed is not None)
    assert dialog.installed == ("windows", str(Path("C:/revise.exe"))) and not dialog.isVisible()


def test_share_from_courses_and_receive_in_import_page(qapp, db, tmp_path):
    from revise.db import Database
    from revise.gui.import_page import ImportWorker
    deck = db.add_deck("LIFAPSD", "Les piles", "/dl/[LIFAPSD] CM8 - Pile et file.pdf", None, "abonnement",
                       [CardDraft("qa", "Qu'est-ce qu'une pile ?", "Structure LIFO.", 3, "", ["a", "b", "c"])])
    win = MainWindow(db)
    win.show()
    qapp.processEvents()
    page = win.courses
    assert page.selected_decks() == [deck] and page.share_btn.isEnabled()   # un seul cours : coché d'office
    assert page.share_to(tmp_path / "piles")                               # l'extension est ajoutée
    shared = tmp_path / "piles.revise"
    assert shared.is_file()
    assert page.share_to(tmp_path / "piles.txt", anki=True) and (tmp_path / "piles.txt").is_file()

    other = Database(tmp_path / "autre.db")
    win2 = MainWindow(other)
    imp = win2.import_page
    imp.add_file(shared, checked=True)
    assert imp.selected_paths() == [shared.resolve()]
    done = []
    worker = ImportWorker(other.path, imp.selected_paths(), None, "en-ligne")   # aucun moteur n'est lancé
    worker.file_done.connect(lambda name, msg, ok: done.append((msg, ok)))
    worker.run()
    assert done == [("1 cours, 1 cartes", True)] and worker.engine is None
    assert [c.distractors for c in other.cards()] == [["a", "b", "c"]]
    win.close()
    win2.close()
    other.close()


def test_backup_dialog(qapp, db, tmp_path):
    from revise.gui.backup_dialog import BackupDialog
    deck = db.add_deck("Algo", "Piles", None, None, "simple", [CardDraft("qa", "Q", "R")])
    win = MainWindow(db)
    dialog = BackupDialog(db, parent=win)
    assert dialog.save_to(tmp_path / "ma-sauvegarde") and (tmp_path / "ma-sauvegarde.db").is_file()
    db.delete_deck(deck)
    assert dialog.restore_from(tmp_path / "ma-sauvegarde.db") and dialog.restored
    assert [d.title for d in db.decks()] == ["Piles"]
    assert not BackupDialog(db, busy=True, parent=win).restore_btn.isEnabled()
    win.close()


def test_formulas_and_code_colors(qapp):
    from PySide6.QtGui import QTextCursor
    from revise.gui.render import show_markdown
    from revise.gui.review import markdown_view
    view = markdown_view(14)
    show_markdown(view, "Coût : $O(n^2)$\n\n```python\ndef f(x):\n    return 'a'  # fin\n```\n\n```\nsans langage\n```\n"
                        "\n```langageinconnu\nx\n```")
    text = view.toPlainText()
    assert "O(n²)" in text and "$" not in text

    def color_at(word: str) -> str:
        cursor = QTextCursor(view.document())
        cursor.setPosition(text.index(word) + 1)
        return cursor.charFormat().foreground().color().name()
    assert color_at("def") != color_at("x):")            # mot-clé coloré
    assert color_at("'a'") not in (color_at("def"), color_at("x):"))
    assert color_at("sans langage") == color_at("x):")    # pas de langage : pas de couleur, pas d'erreur


def test_explain_button(qapp, db):
    import time

    from revise.models import ReviseError

    def wait(cond):
        for _ in range(300):
            qapp.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    class FakeAI:
        closed = False

        def __init__(self):
            self.asked = []

        def chat(self, system, user, schema):
            self.asked.append(user)
            if "arbre" in user:
                raise ReviseError("quota épuisé")
            return '{"explanation": "Pense à une pile d\'assiettes : coût $O(1)$."}'

        def close(self):
            self.closed = True

    deck = db.add_deck("Algo", "Piles", None, None, "simple",
                       [CardDraft("qa", "Qu'est-ce qu'une pile ?", "Structure LIFO.", 1),
                        CardDraft("qa", "Hauteur d'un arbre ?", "Plus long chemin.", 2)])
    win = MainWindow(db)
    win.show()
    ai = FakeAI()
    rv = win.review
    rv.engine_factory = lambda: ai
    win.start_review([deck], False, False, 20)
    qapp.processEvents()
    assert not rv.explain_btn.isVisible()                 # pas avant d'avoir vu la réponse
    rv.explain()
    assert ai.asked == [] and not rv.explanation.isVisible()
    for _ in range(2):                                    # les deux cartes, dans l'ordre tiré au hasard
        about_stack = "pile" in rv.card.question
        rv.reveal_btn.click()
        assert rv.explain_btn.isVisible()
        rv.explain_btn.click()
        assert wait(lambda: not rv.ai_busy)
        text = rv.explanation.toPlainText()
        if about_stack:
            assert "pile d'assiettes" in text and "O(1)" in text and "$" not in text
            assert "Qu'est-ce qu'une pile ?" in ai.asked[-1] and "Structure LIFO." in ai.asked[-1] and "Algo" in ai.asked[-1]
            rv.rate_btns[1].click()                       # « À revoir » : la carte reviendra, on passe à la suivante
            assert not rv.explanation.isVisible() and not rv.explain_btn.isVisible()
        else:
            assert "quota épuisé" in text and rv.explain_btn.isEnabled()   # erreur dite, pas de plantage
            rv.rate_btns[1].click()
    rv.reveal_btn.click()

    rv.explain_btn.click()                                # réponse qui arrive après qu'on a changé de carte
    rv.rate_btns[3].click()
    assert wait(lambda: not rv.ai_busy)
    assert not rv.explanation.isVisible()
    win.end_review()
    assert ai.closed and rv.engine is None
    win.close()


def test_explain_parses_model_output():
    from revise.engines.explain import SCHEMA, explain
    from revise.models import ReviseError
    seen = []

    def chat(system, user, schema):
        seen.append(schema)
        return '```json\n{"explanation": "  Parce que.  "}\n```'
    assert explain("Q", "R", "Algo", "CM1", chat) == "Parce que." and seen == [SCHEMA]
    for bad in ("pas du json", "{}", '{"explanation": ""}', '{"explanation": 3}', "[]"):
        with pytest.raises(ReviseError):
            explain("Q", "R", "", "", lambda s, u, sc: bad)


def test_online_key_dialog_and_claude_model(qapp, db, monkeypatch):
    from revise import config
    from revise.engines import claude_code, online
    from revise.gui import import_page

    monkeypatch.setattr(import_page, "claude_binary", lambda: "/usr/bin/claude")
    page = import_page.ImportPage(db)
    assert page.key_state.text() == "sans clé : marche, mais lent"
    page.claude_model.setCurrentIndex(page.claude_model.findData("sonnet"))
    assert config.load()["claude_model"] == "sonnet" and claude_code.ClaudeCodeEngine().model == "sonnet"

    dialog = import_page.KeyDialog(page)
    assert [dialog.first.itemData(i) for i in range(dialog.first.count())] == [online.KEYLESS]
    dialog.keys["groq"].setText(" gsk_1 ")
    dialog.keys["mistral"].setText("m")
    assert [dialog.first.itemData(i) for i in range(dialog.first.count())] == ["groq", "mistral", online.KEYLESS]
    dialog.first.setCurrentIndex(dialog.first.findData("mistral"))
    dialog._save()
    assert [c["provider"] for c in online.chain()] == ["mistral", "groq", online.KEYLESS]
    assert online.settings("groq")["key"] == "gsk_1"
    page._update_key_state()
    assert page.key_state.text() == "prête : Mistral AI, Groq + sans clé"
    again = import_page.KeyDialog(page)                     # rouverte : les réglages sont repris
    assert again.keys["groq"].text() == "gsk_1" and again.first.currentData() == "mistral"
