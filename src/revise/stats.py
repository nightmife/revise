"""Statistiques : avancement par matière, régularité (heatmap), prévisions, rétention."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from fsrs import State
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from revise.db import Database, parse_iso, utcnow
from revise.scheduler import load_state

# Rampe séquentielle bleue (une seule teinte, du faible au fort) pour un terminal sombre.
HEAT = ["#3a3936", "#184f95", "#256abf", "#3987e5", "#86b6ef"]
BAR = "#3987e5"
MUTED = "grey62"
WEEKDAYS = ["lun", "", "mer", "", "ven", "", "dim"]
MONTHS = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]


def local_day(ts: str) -> date:
    return parse_iso(ts).astimezone().date()


def heat_level(n: int, peak: int) -> int:
    if n <= 0:
        return 0
    if peak <= 4:
        return min(4, n)
    return min(4, 1 + int(3 * n / peak))


def streak(days: set[date], today: date) -> int:
    d = today if today in days else today - timedelta(days=1)
    s = 0
    while d in days:
        s += 1
        d -= timedelta(days=1)
    return s


def subject_table(db: Database, now: datetime) -> Table:
    t = Table(title="Matières", title_justify="left", header_style="bold", expand=False)
    t.add_column("Matière")
    t.add_column("Cours", justify="right")
    t.add_column("Cartes", justify="right")
    t.add_column("Nouvelles", justify="right")
    t.add_column("À réviser", justify="right")
    t.add_column("Apprises", justify="right")
    t.add_column("Solides (≥ 21 j)", justify="right")
    for subj in db.subjects():
        cards = db.cards(subject=subj, include_suspended=False)
        new = sum(1 for c in cards if c.fsrs is None)
        due = sum(1 for c in cards if c.fsrs is not None and parse_iso(c.due) <= now)
        learned = solid = 0
        for c in cards:
            if c.fsrs is None:
                continue
            st = load_state(c)
            if st.state == State.Review:
                learned += 1
                if (st.stability or 0) >= 21:
                    solid += 1
        t.add_row(subj, str(len(db.decks(subj))), str(len(cards)), str(new),
                  f"[bold]{due}[/]" if due else "0", str(learned), str(solid))
    return t


def heatmap(db: Database, today: date, weeks: int = 26) -> Group:
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    since = datetime.combine(start, datetime.min.time()).astimezone()
    counts = Counter(local_day(r["ts"]) for r in db.reviews_since(since))
    peak = max(counts.values(), default=0)
    lines = []
    cols = [" "] * (weeks * 2 + 4)
    last_month = None
    for w in range(weeks):
        d = start + timedelta(days=7 * w)
        if d.month != last_month:
            label = MONTHS[d.month - 1]
            pos = w * 2
            if all(c == " " for c in cols[pos:pos + len(label) + 1]):
                cols[pos:pos + len(label)] = label
            last_month = d.month
    header = Text("     " + "".join(cols).rstrip(), style=MUTED)
    lines.append(header)
    for wd in range(7):
        row = Text(f"{WEEKDAYS[wd]:>4} ", style=MUTED)
        for w in range(weeks):
            d = start + timedelta(days=7 * w + wd)
            if d > today:
                row.append("  ")
                continue
            row.append("■ ", style=HEAT[heat_level(counts.get(d, 0), peak)])
        lines.append(row)
    legend = Text("     moins ", style=MUTED)
    for c in HEAT:
        legend.append("■ ", style=c)
    legend.append("plus", style=MUTED)
    total = sum(counts.values())
    active = len(counts)
    legend.append(f"    {total} révisions sur {active} jour(s)", style=MUTED)
    lines.append(Text(""))
    lines.append(legend)
    return Group(*lines)


def forecast(db: Database, today: date, days: int = 14) -> Table:
    counts: Counter[date] = Counter()
    for c in db.cards(include_suspended=False):
        if c.fsrs is None:
            continue
        d = max(local_day(c.due), today)  # les cartes en retard comptent pour aujourd'hui
        if d < today + timedelta(days=days):
            counts[d] += 1
    peak = max(counts.values(), default=0)
    t = Table(title="Cartes à réviser les 14 prochains jours", title_justify="left", show_header=False,
              box=None, padding=(0, 1))
    t.add_column(style=MUTED)
    t.add_column()
    t.add_column(justify="right")
    width = 30
    for i in range(days):
        d = today + timedelta(days=i)
        n = counts.get(d, 0)
        label = "aujourd'hui" if i == 0 else ("demain" if i == 1 else d.strftime("%d/%m"))
        bar = "█" * (round(width * n / peak) if peak else 0)
        t.add_row(label, Text(bar or "·", style=BAR if n else MUTED), str(n))
    return t


def summary(db: Database, now: datetime) -> Text:
    today = now.astimezone().date()
    reviews = db.reviews_since(now - timedelta(days=400))
    days = {local_day(r["ts"]) for r in reviews}
    today_reviews = [r for r in reviews if local_day(r["ts"]) == today]
    minutes = sum((r["duration_ms"] or 0) for r in today_reviews) / 60000
    month = [r for r in reviews if parse_iso(r["ts"]) >= now - timedelta(days=30) and r["state_before"] == int(State.Review)]
    t = Text()
    t.append("Série : ", style=MUTED)
    t.append(f"{streak(days, today)} jour(s)", style="bold")
    t.append("   Aujourd'hui : ", style=MUTED)
    t.append(f"{len(today_reviews)} cartes en {minutes:.0f} min", style="bold")
    t.append("   Rétention (30 j) : ", style=MUTED)
    if month:
        ok = sum(1 for r in month if r["rating"] > 1)
        t.append(f"{100 * ok / len(month):.0f} %", style="bold")
        t.append(f" sur {len(month)} rappels", style=MUTED)
    else:
        t.append("pas encore de données", style=MUTED)
    return t


def show(db: Database, console: Console | None = None) -> None:
    console = console or Console()
    now = utcnow()
    if not db.subjects():
        console.print("Aucun cours importé. Commence par : [bold]revise importer cours.pdf -m Matière[/]")
        return
    today = now.astimezone().date()
    console.print(summary(db, now))
    console.print()
    console.print(subject_table(db, now))
    console.print()
    console.print(Panel(heatmap(db, today), title="Régularité (26 semaines)", title_align="left",
                        border_style=MUTED, expand=False))
    console.print()
    console.print(forecast(db, today))
