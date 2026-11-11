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


def subject_rows(db: Database, now: datetime) -> list[dict]:
    rows = []
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
        rows.append({"subject": subj, "decks": len(db.decks(subj)), "cards": len(cards), "new": new,
                     "due": due, "learned": learned, "solid": solid})
    return rows


def subject_table(db: Database, now: datetime) -> Table:
    t = Table(title="Matières", title_justify="left", header_style="bold", expand=False)
    for col in ("Matière", "Cours", "Cartes", "Nouvelles", "À réviser", "Apprises", "Solides (≥ 21 j)"):
        t.add_column(col, justify="left" if col == "Matière" else "right")
    for r in subject_rows(db, now):
        t.add_row(r["subject"], str(r["decks"]), str(r["cards"]), str(r["new"]),
                  f"[bold]{r['due']}[/]" if r["due"] else "0", str(r["learned"]), str(r["solid"]))
    return t


def daily_counts(db: Database, today: date, weeks: int = 26) -> tuple[date, Counter]:
    """Premier lundi affiché et nombre de révisions par jour local."""
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    since = datetime.combine(start, datetime.min.time()).astimezone()
    return start, Counter(local_day(r["ts"]) for r in db.reviews_since(since))


def forecast_counts(db: Database, today: date, days: int = 14) -> list[tuple[date, int]]:
    counts: Counter[date] = Counter()
    for c in db.cards(include_suspended=False):
        if c.fsrs is None:
            continue
        d = max(local_day(c.due), today)  # les cartes en retard comptent pour aujourd'hui
        if d < today + timedelta(days=days):
            counts[d] += 1
    return [(today + timedelta(days=i), counts.get(today + timedelta(days=i), 0)) for i in range(days)]


def summary_data(db: Database, now: datetime) -> dict:
    today = now.astimezone().date()
    reviews = db.reviews_since(now - timedelta(days=400))
    days = {local_day(r["ts"]) for r in reviews}
    today_reviews = [r for r in reviews if local_day(r["ts"]) == today]
    month = [r for r in reviews
             if parse_iso(r["ts"]) >= now - timedelta(days=30) and r["state_before"] == int(State.Review)]
    ok = sum(1 for r in month if r["rating"] > 1)
    return {"streak": streak(days, today), "today": len(today_reviews),
            "minutes": sum((r["duration_ms"] or 0) for r in today_reviews) / 60000,
            "retention": (ok / len(month)) if month else None, "retention_n": len(month)}


def heatmap(db: Database, today: date, weeks: int = 26) -> Group:
    start, counts = daily_counts(db, today, weeks)
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
    data = forecast_counts(db, today, days)
    counts = dict(data)
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
    d = summary_data(db, now)
    t = Text()
    t.append("Série : ", style=MUTED)
    t.append(f"{d['streak']} jour(s)", style="bold")
    t.append("   Aujourd'hui : ", style=MUTED)
    t.append(f"{d['today']} cartes en {d['minutes']:.0f} min", style="bold")
    t.append("   Rétention (30 j) : ", style=MUTED)
    if d["retention"] is not None:
        t.append(f"{100 * d['retention']:.0f} %", style="bold")
        t.append(f" sur {d['retention_n']} rappels", style=MUTED)
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
