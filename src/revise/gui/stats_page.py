"""Page « Statistiques » : chiffres clés, matières, régularité, prévisions."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QFrame, QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget, QHBoxLayout)

from revise import stats
from revise.db import Database, utcnow
from revise.gui import theme
from revise.gui.common import cloze_question, muted, page_header, row
from revise.weak import weak_cards

MONTHS = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]
DAYS = ["lun", "", "mer", "", "ven", "", "dim"]
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def kpi(title: str, value: str, detail: str = "") -> QFrame:
    f = QFrame()
    f.setObjectName("kpi")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.addWidget(muted(title))
    v = QLabel(value)
    v.setObjectName("kpiValue")
    lay.addWidget(v)
    if detail:
        lay.addWidget(muted(detail))
    return f


class Heatmap(QWidget):
    """Révisions par jour sur 26 semaines (rampe bleue séquentielle, une seule teinte)."""

    CELL, GAP, LEFT, TOP = 14, 3, 34, 20

    def __init__(self):
        super().__init__()
        self.weeks = 26
        self.start = date.today()
        self.counts: dict[date, int] = {}
        self.today = date.today()
        self.setMouseTracking(True)
        self.setMinimumHeight(self.TOP + 7 * (self.CELL + self.GAP) + 30)

    def set_data(self, start: date, counts: dict[date, int], today: date) -> None:
        self.start, self.counts, self.today = start, counts, today
        self.setMinimumWidth(self.LEFT + self.weeks * (self.CELL + self.GAP) + 10)
        self.update()

    def _cell(self, w: int, d: int) -> QRectF:
        step = self.CELL + self.GAP
        return QRectF(self.LEFT + w * step, self.TOP + d * step, self.CELL, self.CELL)

    def _level(self, n: int) -> int:
        return stats.heat_level(n, max(self.counts.values(), default=0))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        p.setPen(QColor(theme.MUTED))
        last_month = None
        for w in range(self.weeks):
            d0 = self.start + timedelta(days=7 * w)
            if d0.month != last_month:
                p.drawText(QRectF(self.LEFT + w * (self.CELL + self.GAP), 0, 60, self.TOP - 4),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, MONTHS[d0.month - 1])
                last_month = d0.month
        for i, lab in enumerate(DAYS):
            if lab:
                r = self._cell(0, i)
                p.drawText(QRectF(0, r.top(), self.LEFT - 6, self.CELL),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, lab)
        p.setPen(Qt.PenStyle.NoPen)
        for w in range(self.weeks):
            for d in range(7):
                day = self.start + timedelta(days=7 * w + d)
                if day > self.today:
                    continue
                p.setBrush(QColor(theme.HEAT[self._level(self.counts.get(day, 0))]))
                p.drawRoundedRect(self._cell(w, d), 3, 3)
        # légende
        y = self.TOP + 7 * (self.CELL + self.GAP) + 8
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(self.LEFT, y, 50, self.CELL), Qt.AlignmentFlag.AlignVCenter, "moins")
        x = self.LEFT + 44
        p.setPen(Qt.PenStyle.NoPen)
        for c in theme.HEAT:
            p.setBrush(QColor(c))
            p.drawRoundedRect(QRectF(x, y, self.CELL, self.CELL), 3, 3)
            x += self.CELL + self.GAP
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(x + 4, y, 50, self.CELL), Qt.AlignmentFlag.AlignVCenter, "plus")

    def mouseMoveEvent(self, e):
        for w in range(self.weeks):
            for d in range(7):
                if self._cell(w, d).contains(e.position()):
                    day = self.start + timedelta(days=7 * w + d)
                    if day <= self.today:
                        n = self.counts.get(day, 0)
                        QToolTip.showText(e.globalPosition().toPoint(),
                                          f"{day.strftime('%d/%m/%Y')} : {n} révision{'s' if n > 1 else ''}", self)
                    return
        QToolTip.hideText()


class ForecastChart(QWidget):
    """Cartes à réviser chaque jour (barres, un seul axe, valeurs au survol et au-dessus des barres)."""

    def __init__(self):
        super().__init__()
        self.data: list[tuple[date, int]] = []
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self._bars: list[tuple[QRectF, str]] = []

    def set_data(self, data: list[tuple[date, int]]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        self._bars = []
        if not self.data:
            return
        w, h = self.width(), self.height()
        top, bottom = 18, 22
        n = len(self.data)
        slot = w / n
        bw = max(6.0, slot - 6)
        peak = max((v for _, v in self.data), default=0) or 1
        p.setPen(QColor(theme.BORDER))
        p.drawLine(0, h - bottom, w, h - bottom)
        for i, (d, v) in enumerate(self.data):
            x = i * slot + (slot - bw) / 2
            bh = (h - top - bottom) * v / peak
            rect = QRectF(x, h - bottom - bh, bw, bh)
            label = "auj." if i == 0 else d.strftime("%d/%m")
            if v:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.ACCENT))
                # extrémité arrondie côté donnée, ancrée sur la ligne de base
                p.drawRoundedRect(rect, 4, 4)
                p.fillRect(QRectF(x, h - bottom - min(bh, 4), bw, min(bh, 4)), QColor(theme.ACCENT))
                p.setPen(QColor(theme.TEXT))
                p.drawText(QRectF(x - 10, rect.top() - 16, bw + 20, 14), Qt.AlignmentFlag.AlignCenter, str(v))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(i * slot, h - bottom + 4, slot, 16), Qt.AlignmentFlag.AlignCenter, label)
            self._bars.append((QRectF(i * slot, 0, slot, h), f"{WEEKDAYS[d.weekday()]} {d.strftime('%d/%m')} : {v} carte(s)"))

    def mouseMoveEvent(self, e):
        for rect, text in self._bars:
            if rect.contains(e.position()):
                QToolTip.showText(e.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()


class StatsPage(QWidget):
    start_weak = Signal(list)  # identifiants des cartes à retravailler

    def __init__(self, db: Database):
        super().__init__()
        self.setObjectName("page")
        self.db = db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("page")
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(28, 24, 28, 24)
        self.lay.addWidget(page_header("Mes progrès", "Ta régularité et ce qui t'attend les prochains jours."))
        self.kpis = QHBoxLayout()
        self.lay.addLayout(self.kpis)
        self.lay.addSpacing(10)
        t = QLabel("Matières")
        t.setObjectName("section")
        self.lay.addWidget(t)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Matière", "Cours", "Cartes", "Jamais vues", "À réviser", "Apprises",
                                              "Solides (≥ 21 j)"])
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 7):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(170)
        self.lay.addWidget(self.table)
        self.lay.addSpacing(10)
        t = QLabel("Mes points faibles")
        t.setObjectName("section")
        self.lay.addWidget(t)
        self.weak_info = muted("")
        self.lay.addWidget(self.weak_info)
        self.weak_list = QListWidget()
        self.weak_list.setMaximumHeight(230)
        self.weak_list.setWordWrap(True)
        self.lay.addWidget(self.weak_list)
        self.weak_btn = QPushButton("Retravailler mes points faibles")
        self.weak_btn.setObjectName("primary")
        self.weak_btn.clicked.connect(lambda: self.start_weak.emit(self.weak_ids))
        self.lay.addLayout(row(self.weak_btn, None))
        self.weak_ids: list[int] = []
        self.lay.addSpacing(10)
        t = QLabel("Régularité (révisions par jour, 26 semaines)")
        t.setObjectName("section")
        self.lay.addWidget(t)
        self.heatmap = Heatmap()
        self.lay.addWidget(self.heatmap)
        t = QLabel("Cartes à réviser les 14 prochains jours")
        t.setObjectName("section")
        self.lay.addWidget(t)
        self.forecast = ForecastChart()
        self.lay.addWidget(self.forecast)
        self.lay.addStretch(1)

    def refresh(self) -> None:
        now = utcnow()
        today = now.astimezone().date()
        while self.kpis.count():
            item = self.kpis.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        d = stats.summary_data(self.db, now)
        ret = f"{100 * d['retention']:.0f} %" if d["retention"] is not None else "—"
        self.kpis.addWidget(kpi("Série", f"{d['streak']} j", "jours de suite avec au moins une révision"))
        self.kpis.addWidget(kpi("Aujourd'hui", f"{d['today']}", f"cartes en {d['minutes']:.0f} min"))
        self.kpis.addWidget(kpi("Réponses justes (30 j)", ret,
                                f"sur {d['retention_n']} cartes revues" if d["retention_n"] else "pas encore de données"))
        rows = stats.subject_rows(self.db, now)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["subject"], r["decks"], r["cards"], r["new"], r["due"], r["learned"], r["solid"]]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, j, it)
        weak = weak_cards(self.db)
        self.weak_ids = [w.card.id for w in weak]
        self.weak_list.clear()
        for w in weak:
            it = QListWidgetItem(f"{cloze_question(w.card.question).replace('**', '')}\n    {w.describe()}")
            it.setToolTip(w.card.answer)
            self.weak_list.addItem(it)
        self.weak_list.setVisible(bool(weak))
        self.weak_btn.setVisible(bool(weak))
        self.weak_btn.setText(f"Retravailler ces {len(weak)} questions" if len(weak) > 1 else "Retravailler cette question")
        self.weak_info.setText(
            "Les questions que tu rates souvent (révisions, QCM et examens blancs). Une question sue deux fois de "
            "suite sort de la liste." if weak else
            "Aucun point faible pour l'instant : les questions que tu rates souvent viendront ici.")
        start, counts = stats.daily_counts(self.db, today)
        self.heatmap.set_data(start, dict(counts), today)
        self.forecast.set_data(stats.forecast_counts(self.db, today))
