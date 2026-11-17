"""Page d'accueil : le programme du jour, avec un seul gros bouton pour s'y mettre."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QConicalGradient, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from revise import config, exam
from revise.db import Database
from revise.gui import theme
from revise.gui.common import ActionCard, row
from revise.today import DEFAULT_NEW_PER_DAY, Today, today

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]


def greeting(now: datetime) -> str:
    if now.hour < 5 or now.hour >= 18:
        return "Bonsoir !"
    return "Bonjour !" if now.hour < 12 else "Bon après-midi !"


def french_date(now: datetime) -> str:
    return f"{WEEKDAYS[now.weekday()]} {now.day}{'er' if now.day == 1 else ''} {MONTHS[now.month - 1]}"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n < 2 else (many or one + 's')}"


class Ring(QWidget):
    """Anneau d'avancement de la journée : ce qui est fait sur ce qui était prévu."""

    def __init__(self, size: int = 132):
        super().__init__()
        self.setFixedSize(size, size)
        self.done, self.goal = 0, 0

    def set_progress(self, done: int, goal: int) -> None:
        self.done, self.goal = max(0, done), max(0, goal)
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = 11
        rect = QRectF(width / 2 + 1, width / 2 + 1, self.width() - width - 2, self.height() - width - 2)
        track = QPen(QColor(255, 255, 255, 46), width)
        p.setPen(track)
        p.drawEllipse(rect)
        fraction = min(1.0, self.done / self.goal) if self.goal else 0.0
        if fraction > 0:
            gradient = QConicalGradient(rect.center(), 90)
            gradient.setColorAt(0.0, QColor("#ffffff"))
            gradient.setColorAt(1.0, QColor("#b9c3ff"))
            pen = QPen(gradient, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -int(fraction * 360 * 16))
        p.setPen(QColor("white"))
        big = QFont(self.font())
        big.setPointSizeF(21)
        big.setBold(True)
        p.setFont(big)
        top = QRectF(0, self.height() / 2 - 30, self.width(), 34)
        p.drawText(top, Qt.AlignmentFlag.AlignCenter, str(self.done))
        small = QFont(self.font())
        small.setPointSizeF(9)
        p.setFont(small)
        p.setPen(QColor("#c9cffa"))
        label = "faites aujourd'hui" if self.done != 1 else "faite aujourd'hui"
        p.drawText(QRectF(0, self.height() / 2 + 4, self.width(), 18), Qt.AlignmentFlag.AlignCenter, label)


class Tile(QFrame):
    """Petit bloc : un chiffre, ce qu'il mesure, une ligne de détail."""

    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        self.label = QLabel(label)
        self.label.setObjectName("tileLabel")
        self.value = QLabel("—")
        self.value.setObjectName("tileValue")
        self.detail = QLabel("")
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setVisible(False)
        for w in (self.label, self.value, self.detail, self.bar):
            lay.addWidget(w)
        lay.addStretch(1)

    def set(self, value: str, detail: str, color: str | None = None, percent: int | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {color or theme.TEXT};")
        self.detail.setText(detail)
        self.bar.setVisible(percent is not None)
        if percent is not None:
            self.bar.setRange(0, 100)
            self.bar.setValue(percent)


def step_card(number: int, title: str, text: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("tile")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(6)
    badge = QLabel(str(number))
    badge.setObjectName("stepNumber")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    head = QLabel(title)
    head.setObjectName("actionTitle")
    body = QLabel(text)
    body.setObjectName("muted")
    body.setWordWrap(True)
    lay.addLayout(row(badge, head, None, spacing=10))
    lay.addWidget(body)
    lay.addStretch(1)
    return frame


class HomePage(QWidget):
    start_review = Signal(list, bool, bool, int)  # cours, examen, inclure les connues, nouvelles par jour
    quick_quiz = Signal(list)
    go_import = Signal()
    go_courses = Signal()
    go_learn = Signal()
    go_exam = Signal()
    start_weak = Signal(list)  # identifiants des cartes à retravailler

    def __init__(self, db: Database):
        super().__init__()
        self.setObjectName("page")
        self.db = db
        self.plan: Today | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("scrollBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(32, 26, 32, 26)
        lay.setSpacing(16)

        self.hello = QLabel()
        self.hello.setObjectName("hello")
        self.date = QLabel()
        self.date.setObjectName("subtitle")
        head = QVBoxLayout()
        head.setSpacing(0)
        head.addWidget(self.hello)
        head.addWidget(self.date)
        lay.addLayout(head)

        # ------------------------------------------------------------ le programme du jour
        self.hero = QFrame()
        self.hero.setObjectName("hero")
        hl = QHBoxLayout(self.hero)
        hl.setContentsMargins(30, 26, 30, 26)
        hl.setSpacing(28)
        self.ring = Ring()
        hl.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(6)
        self.hero_title = QLabel()
        self.hero_title.setObjectName("heroTitle")
        self.hero_title.setWordWrap(True)
        self.hero_text = QLabel()
        self.hero_text.setObjectName("heroText")
        self.hero_text.setWordWrap(True)
        self.main_btn = QPushButton()
        self.main_btn.setObjectName("hero")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setDefault(True)
        self.main_btn.clicked.connect(self._main_action)
        self.second_btn = QPushButton()
        self.second_btn.setObjectName("link")
        self.second_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.second_btn.setStyleSheet("color: #dfe3ff; font-size: 11pt;")
        self.second_btn.clicked.connect(self._second_action)
        text.addStretch(1)
        text.addWidget(self.hero_title)
        text.addWidget(self.hero_text)
        text.addSpacing(10)
        text.addLayout(row(self.main_btn, self.second_btn, None, spacing=18))
        text.addStretch(1)
        hl.addLayout(text, 1)
        lay.addWidget(self.hero)

        # ------------------------------------------------------------------ où j'en suis
        self.streak = Tile("Série")
        self.mastery = Tile("Ce que tu sais déjà")
        self.exam = Tile("Prochain examen")
        self.tiles = QWidget()
        tl = QHBoxLayout(self.tiles)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(14)
        for t in (self.streak, self.mastery, self.exam):
            tl.addWidget(t, 1)
        lay.addWidget(self.tiles)

        # -------------------------------------------------------------- autres activités
        self.more_title = QLabel("Envie d'autre chose ?")
        self.more_title.setObjectName("section")
        lay.addWidget(self.more_title)
        self.quiz_card = ActionCard("QCM rapide", "10 questions tirées au hasard dans tous tes cours.")
        self.quiz_card.clicked.connect(lambda: self.quick_quiz.emit([d.id for d in self.db.decks()]))
        self.learn_card = ActionCard("Lire une fiche", "Le cours résumé, réponses visibles, pour apprendre d'abord.")
        self.learn_card.clicked.connect(self.go_learn.emit)
        self.courses_card = ActionCard("Choisir mes cours", "Réviser un cours précis, ou tout revoir avant un contrôle.")
        self.courses_card.clicked.connect(self.go_courses.emit)
        self.import_card = ActionCard("Ajouter un cours", "PDF, PowerPoint, Word : l'application écrit les cartes.")
        self.import_card.clicked.connect(self.go_import.emit)
        self.weak_card = ActionCard("Mes points faibles", "Les questions que tu rates souvent, à retravailler.")
        self.weak_card.clicked.connect(self._weak)
        self.exam_card = ActionCard("Examen blanc", "QCM et réponses à écrire, chronométré, noté sur 20.")
        self.exam_card.clicked.connect(self.go_exam.emit)
        self.more = QWidget()
        grid = QGridLayout(self.more)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        for i, card in enumerate((self.quiz_card, self.exam_card, self.weak_card, self.learn_card, self.courses_card,
                                  self.import_card)):
            card.setMinimumHeight(84)
            grid.addWidget(card, i // 3, i % 3)
            grid.setColumnStretch(i % 3, 1)
        lay.addWidget(self.more)

        # ----------------------------------------------------- première visite : le mode d'emploi
        self.steps_title = QLabel("Comment ça marche")
        self.steps_title.setObjectName("section")
        lay.addWidget(self.steps_title)
        self.steps = QWidget()
        sl = QHBoxLayout(self.steps)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(14)
        for number, title, body_text in (
                (1, "Ajoute un cours", "Glisse le PDF, le PowerPoint ou le Word de ton cours : l'application le "
                                       "transforme en questions-réponses."),
                (2, "Apprends et teste-toi", "Lis la fiche du cours, puis réponds aux cartes ou fais un QCM."),
                (3, "Reviens chaque jour", "Quelques minutes suffisent : chaque question revient juste avant que "
                                           "tu l'oublies.")):
            sl.addWidget(step_card(number, title, body_text), 1)
        lay.addWidget(self.steps)
        lay.addStretch(1)
        self.refresh()

    # ------------------------------------------------------------------ données
    def refresh(self) -> None:
        now = datetime.now()
        self.hello.setText(greeting(now))
        base = config.load().get("new_per_day", DEFAULT_NEW_PER_DAY)
        base = base if isinstance(base, int) and not isinstance(base, bool) and 0 <= base <= 999 else DEFAULT_NEW_PER_DAY
        plan = self.plan = today(self.db, base)
        has = plan.decks > 0
        self.date.setText(f"Nous sommes {french_date(now)}." + (" Voici ton programme." if has else ""))
        for w in (self.tiles, self.more_title, self.more):
            w.setVisible(has)
        for w in (self.steps_title, self.steps, ):
            w.setVisible(not has)
        self.ring.setVisible(has)
        self.ring.set_progress(plan.done, plan.done + plan.remaining)
        if not has:
            self.hero_title.setText("Transforme ton premier cours en cartes de révision")
            self.hero_text.setText("Donne un cours à l'application : elle écrit les questions, te les pose au bon "
                                   "moment et te dit où tu en es.")
            self.main_btn.setText("Ajouter mon premier cours")
            self.second_btn.setVisible(False)
        elif plan.remaining:
            parts = []
            if plan.due:
                parts.append(f"{plan.due} à revoir")
            if plan.new:
                parts.append(plural(plan.new, "nouvelle"))
            self.hero_title.setText(f"{plural(plan.remaining, 'carte')} t'attend{'ent' if plan.remaining > 1 else ''} "
                                    "aujourd'hui")
            self.hero_text.setText(" · ".join(parts) + f" · environ {plan.minutes} min")
            self.main_btn.setText("Continuer ma révision" if plan.done else "Commencer ma révision")
            self.second_btn.setText("Choisir mes cours")
            self.second_btn.setVisible(True)
        else:
            if plan.done:
                self.hero_title.setText("Bravo, c'est fait pour aujourd'hui !")
                self.hero_text.setText(f"{plural(plan.done, 'réponse')} aujourd'hui. Reviens demain — ou continue "
                                       "avec un QCM pour le plaisir.")
            else:
                self.hero_title.setText("Tout est à jour")
                self.hero_text.setText("Aucune carte à revoir pour l'instant. Un QCM pour rester en forme ?")
            self.main_btn.setText("Faire un QCM")
            self.second_btn.setText("Tout revoir avant un contrôle")
            self.second_btn.setVisible(True)

        self.streak.set(plural(plan.streak, "jour"),
                        "d'affilée. Continue !" if plan.streak > 1 else
                        "Première journée : reviens demain." if plan.streak == 1 else
                        "Révise aujourd'hui pour démarrer une série.",
                        theme.WARN if plan.streak else theme.TEXT)
        self.mastery.set(f"{plan.mastery_percent} %", f"{plan.known} cartes sues sur {plan.total}",
                         theme.GOOD if plan.known else theme.TEXT, plan.mastery_percent)
        if plan.next_exam:
            name, days, ready = plan.next_exam
            self.exam.set(exam.countdown(days).capitalize(), f"{name} · prêt à {ready} %",
                          theme.BAD if days <= 2 else theme.ACCENT_HOVER)
        else:
            self.exam.set("—", "Donne la date d'un examen dans « Mes cours » : l'application règle le rythme.")
        from revise.weak import weak_cards
        weak = len(weak_cards(self.db)) if has else 0
        self.weak_card.setEnabled(weak > 0)
        self.weak_card.text.setText(f"{plural(weak, 'question')} que tu rates souvent : retravaille-les." if weak
                                    else "Rien pour l'instant : les questions que tu rates souvent viendront ici.")

    # ------------------------------------------------------------------ actions
    def _main_action(self) -> None:
        plan = self.plan
        ids = [d.id for d in self.db.decks()]
        if plan is None or not ids:
            self.go_import.emit()
        elif plan.remaining:
            self.start_review.emit(ids, False, False, plan.new_per_day)
        else:
            self.quick_quiz.emit(ids)

    def _second_action(self) -> None:
        self.go_courses.emit()

    def _weak(self) -> None:
        from revise.weak import weak_cards
        cards = [w.card.id for w in weak_cards(self.db)]
        if cards:
            self.start_weak.emit(cards)
