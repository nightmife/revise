"""Interface en ligne de commande."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from revise import __version__, editfmt
from revise.db import Database, file_sha256
from revise.models import ReviseError

console = Console()
err_console = Console(stderr=True)


def pick_engine(name: str):
    from revise.engines.claude import ClaudeEngine
    from revise.engines.claude_code import ClaudeCodeEngine, claude_binary
    from revise.engines.simple import SimpleEngine

    if name == "auto":
        # On ne paie jamais sans l'avoir demandé : l'API facturée n'est utilisée qu'avec --moteur api.
        if claude_binary():
            return ClaudeCodeEngine()
        console.print("[yellow]Claude Code introuvable : moteur sans IA.[/]")
        return SimpleEngine()
    return {"api": ClaudeEngine, "abonnement": ClaudeCodeEngine, "simple": SimpleEngine}[name]()


# --------------------------------------------------------------- commandes ---

def cmd_import(db: Database, args) -> int:
    from revise.engines.claude import ClaudeEngine, format_estimate

    engine = pick_engine(args.moteur)
    total = 0
    for raw in args.pdf:
        pdf = Path(raw).expanduser()
        subject = args.matiere or pdf.resolve().parent.name
        sha = file_sha256(pdf) if pdf.is_file() else None
        if sha and (existing := db.find_deck_by_hash(sha)) and not args.forcer:
            console.print(f"[yellow]{pdf.name} déjà importé[/] (paquet {existing.id}, {existing.subject}). "
                          "--forcer pour réimporter.")
            continue
        if isinstance(engine, ClaudeEngine) and not args.oui:
            with console.status(f"Estimation du coût pour {pdf.name}…"):
                est = engine.estimate(pdf, subject)
            console.print(format_estimate(est))
            if not Confirm.ask("Générer les cartes ?", default=True):
                continue
        with console.status(f"{pdf.name}…") as status:
            title, cards = engine.generate(pdf, subject, lambda m: status.update(f"{pdf.name} : {m}"))
        if not cards:
            console.print(f"[red]Aucune carte trouvée dans {pdf.name}.[/]")
            continue
        if args.titre and len(args.pdf) == 1:
            title = args.titre
        if sha and (existing := db.find_deck_by_hash(sha)) and args.forcer:
            db.delete_deck(existing.id)
        deck_id = db.add_deck(subject, title, str(pdf.resolve()), sha, engine.name, cards)
        total += len(cards)
        console.print(f"[green]✓[/] {pdf.name} → paquet {deck_id} « {title} » ({subject}) : "
                      f"[bold]{len(cards)} cartes[/]")
        for c in cards[:3]:
            console.print(Panel(Markdown(f"{c.question}\n\n---\n\n{c.answer}"), title=f"exemple · p. {c.page or '?'}",
                                title_align="left", border_style="grey50", expand=False, width=90))
    if total:
        console.print(f"\nC'est parti : [bold]revise reviser[/]  (ou [bold]revise editer N[/] pour retoucher les cartes)")
    return 0


def cmd_estimate(db: Database, args) -> int:
    from revise.engines.claude import ClaudeEngine, format_estimate

    engine = ClaudeEngine()
    for raw in args.pdf:
        pdf = Path(raw).expanduser()
        with console.status(f"Estimation pour {pdf.name}…"):
            est = engine.estimate(pdf, args.matiere or pdf.resolve().parent.name)
        console.print(f"{pdf.name} : {format_estimate(est)}")
    return 0


def cmd_review(db: Database, args) -> int:
    from revise import tui

    if not db.subjects():
        console.print("Aucun cours importé. Commence par : [bold]revise importer cours.pdf -m Matière[/]")
        return 1
    if args.matiere and args.matiere.lower() not in {s.lower() for s in db.subjects()}:
        raise ReviseError(f"matière inconnue « {args.matiere} » (connues : {', '.join(db.subjects())})")
    done = tui.run(db, args.matiere, args.nouvelles)
    console.print(f"{done} carte(s) révisée(s).")
    return 0


def cmd_stats(db: Database, args) -> int:
    from revise import stats

    stats.show(db, console)
    return 0


def cmd_list(db: Database, args) -> int:
    decks = db.decks(args.matiere)
    if not decks:
        console.print("Aucun paquet.")
        return 0
    t = Table(header_style="bold")
    for col in ("N°", "Matière", "Cours", "Cartes", "Nouvelles", "Moteur", "Importé le"):
        t.add_column(col, justify="right" if col in ("N°", "Cartes", "Nouvelles") else "left")
    for d in decks:
        cards = db.cards(deck_id=d.id)
        new = sum(1 for c in cards if c.fsrs is None)
        t.add_row(str(d.id), d.subject, d.title, str(len(cards)), str(new), d.engine, d.created[:10])
    console.print(t)
    return 0


def require_deck(db: Database, deck_id: int):
    d = db.deck(deck_id)
    if not d:
        raise ReviseError(f"paquet {deck_id} introuvable (voir : revise liste)")
    return d


def cmd_cards(db: Database, args) -> int:
    d = require_deck(db, args.paquet)
    for c in db.cards(deck_id=d.id):
        flag = " · suspendue" if c.suspended else (" · nouvelle" if c.fsrs is None else "")
        console.print(Panel(Markdown(f"{c.question}\n\n---\n\n{c.answer}"),
                            title=f"carte {c.id} · {c.kind} · p. {c.page or '?'}{flag}",
                            title_align="left", border_style="grey50", width=100))
    return 0


def cmd_edit(db: Database, args) -> int:
    from revise.tui import open_in_editor

    d = require_deck(db, args.paquet)
    original = db.cards(deck_id=d.id)
    text = editfmt.render(f"{d.subject} — {d.title}", original)
    while True:
        text = open_in_editor(text)
        try:
            blocks = editfmt.parse(text)
            ch = editfmt.diff(db, d.id, original, blocks)
            break
        except ReviseError as e:
            console.print(f"[red]Erreur : {e}[/]")
            if not Confirm.ask("Rouvrir l'éditeur pour corriger ?", default=True):
                return 1
    if not (ch.updated or ch.created or ch.deleted):
        console.print("Aucun changement.")
        return 0
    console.print(f"{ch.updated} modifiée(s), {ch.created} ajoutée(s), {len(ch.deleted or [])} supprimée(s).")
    if ch.deleted and not Confirm.ask(f"Supprimer {len(ch.deleted)} carte(s) et leur historique ?", default=False):
        return 1
    editfmt.apply(db, d.id, original, blocks)
    console.print("[green]✓ Enregistré.[/]")
    return 0


def cmd_delete(db: Database, args) -> int:
    d = require_deck(db, args.paquet)
    n = len(db.cards(deck_id=d.id))
    if not args.oui and not Confirm.ask(f"Supprimer « {d.title} » ({n} cartes et leur historique) ?", default=False):
        return 1
    db.delete_deck(d.id)
    console.print("Paquet supprimé.")
    return 0


# ------------------------------------------------------------------ parseur ---

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="revise", description="Révision espacée (FSRS) à partir de tes CM en PDF.")
    p.add_argument("--version", action="version", version=f"revise {__version__}")
    p.add_argument("--base", type=Path, help="fichier de base de données (défaut : ~/.local/share/revise/revise.db)")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("importer", aliases=["import"], help="créer des cartes à partir de PDF")
    s.add_argument("pdf", nargs="+")
    s.add_argument("-m", "--matiere", help="matière (défaut : nom du dossier du PDF)")
    s.add_argument("--moteur", choices=["auto", "abonnement", "api", "simple"], default="auto",
                   help="abonnement = Claude Code avec ton abonnement (défaut si installé), "
                        "api = API Claude facturée à l'usage, simple = sans IA")
    s.add_argument("--titre", help="titre du cours (un seul PDF)")
    s.add_argument("--oui", action="store_true", help="ne pas demander de confirmation (coût)")
    s.add_argument("--forcer", action="store_true", help="réimporter un PDF déjà importé (remplace le paquet)")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("estimer", help="estimer le coût d'un import avec Claude")
    s.add_argument("pdf", nargs="+")
    s.add_argument("-m", "--matiere")
    s.set_defaults(func=cmd_estimate)

    s = sub.add_parser("reviser", aliases=["r"], help="lancer une séance de révision")
    s.add_argument("-m", "--matiere")
    s.add_argument("-n", "--nouvelles", type=int, default=20, help="nouvelles cartes max par jour (défaut 20)")
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("stats", help="statistiques et régularité")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("liste", aliases=["ls"], help="lister les paquets")
    s.add_argument("-m", "--matiere")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("cartes", help="afficher les cartes d'un paquet")
    s.add_argument("paquet", type=int)
    s.set_defaults(func=cmd_cards)

    s = sub.add_parser("editer", help="modifier les cartes d'un paquet dans $EDITOR")
    s.add_argument("paquet", type=int)
    s.set_defaults(func=cmd_edit)

    s = sub.add_parser("supprimer", help="supprimer un paquet")
    s.add_argument("paquet", type=int)
    s.add_argument("--oui", action="store_true")
    s.set_defaults(func=cmd_delete)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db = Database(args.base) if args.base else Database()
    try:
        if not args.cmd:
            if db.subjects():
                args.matiere, args.nouvelles = None, 20
                return cmd_review(db, args)
            parser.print_help()
            return 0
        return args.func(db, args)
    except ReviseError as e:
        err_console.print(f"[red]Erreur :[/] {e}")
        return 1
    except KeyboardInterrupt:
        err_console.print("Interrompu.")
        return 130
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
