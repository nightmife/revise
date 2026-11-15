"""Interface en ligne de commande."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from revise import __version__, editfmt
from revise.db import Database
from revise.models import ReviseError

console = Console()
err_console = Console(stderr=True)


def pick_engine(name: str):
    from revise.engines.claude_code import ClaudeCodeEngine
    from revise.engines.embedded import EmbeddedEngine
    from revise.engines.online import OnlineEngine
    from revise.engines.simple import SimpleEngine

    return {"auto": EmbeddedEngine, "ia": EmbeddedEngine, "en-ligne": OnlineEngine, "simple": SimpleEngine,
            "abonnement": ClaudeCodeEngine}[name]()


# --------------------------------------------------------------- commandes ---

def cmd_import(db: Database, args) -> int:
    from revise import share
    from revise.importer import guess_subject, import_pdf

    engine = None
    total = 0
    for raw in args.pdf:
        pdf = Path(raw).expanduser()
        if share.is_share_file(pdf):  # cours partagé : cartes déjà écrites, aucun moteur à lancer
            for r in share.import_file(db, pdf, args.matiere):
                if r.skipped:
                    console.print(f"[yellow]{r.name} déjà importé[/] (paquet {r.deck_id}).")
                else:
                    total += r.cards
                    console.print(f"[green]✓[/] {pdf.name} → paquet {r.deck_id} « {r.name} » : "
                                  f"[bold]{r.cards} cartes[/]")
            continue
        if engine is None:
            engine = pick_engine(args.moteur)
        subject = args.matiere or guess_subject(pdf)
        try:
            with console.status(f"{pdf.name}…") as status:
                res = import_pdf(db, engine, pdf, subject, lambda m: status.update(f"{pdf.name} : {m}"),
                                 title=args.titre if len(args.pdf) == 1 else None, force=args.forcer)
        except BaseException:
            getattr(engine, "close", lambda: None)()
            raise
        if res.skipped:
            console.print(f"[yellow]{pdf.name} déjà importé[/] (paquet {res.deck_id}). --forcer pour réimporter.")
            continue
        total += len(res.cards)
        console.print(f"[green]✓[/] {pdf.name} → paquet {res.deck_id} « {res.title} » ({subject}) : "
                      f"[bold]{len(res.cards)} cartes[/]")
        for c in res.cards[:3]:
            console.print(Panel(Markdown(f"{c.question}\n\n---\n\n{c.answer}"), title=f"exemple · p. {c.page or '?'}",
                                title_align="left", border_style="grey50", expand=False, width=90))
    getattr(engine, "close", lambda: None)()  # sans effet si aucun moteur n'a été lancé
    if total:
        console.print("\nC'est parti : [bold]revise reviser[/]  (ou [bold]revise editer N[/] pour retoucher les cartes)")
    return 0


def cmd_share(db: Database, args) -> int:
    from revise import share

    deck_ids = resolve_decks(db, args.cours, None) or [d.id for d in db.decks()]
    dest = Path(args.fichier).expanduser()
    n = (share.export_anki if args.anki else share.export_courses)(db, deck_ids, dest)
    console.print(f"[green]✓[/] {n} cartes de {len(deck_ids)} cours enregistrées dans {dest}")
    return 0


def cmd_backup(db: Database, args) -> int:
    dest = Path(args.fichier).expanduser()
    db.backup_to(dest)
    console.print(f"[green]✓[/] Sauvegarde enregistrée : {dest}")
    return 0


def cmd_restore(db: Database, args) -> int:
    src = Path(args.fichier).expanduser()
    if not args.oui and not Confirm.ask("Remplacer tous les cours et la progression actuels par cette sauvegarde ?",
                                        default=False):
        return 1
    previous = db.restore_from(src)
    console.print(f"[green]✓[/] Sauvegarde restaurée ({len(db.decks())} cours)."
                  + (f" Anciennes données gardées dans {previous}" if previous else ""))
    return 0


def cmd_key(db: Database, args) -> int:
    from revise import config
    from revise.engines.online import PROVIDERS, settings

    values = {k: v for k, v in (("online_provider", args.fournisseur), ("online_key", args.cle),
                                ("online_model", args.modele), ("online_url", args.url)) if v is not None}
    if args.fournisseur:  # changer de fournisseur remet son adresse et son modèle par défaut
        values.setdefault("online_model", "")
        values.setdefault("online_url", "")
    if values:
        config.save(values)
    s = settings()
    console.print(f"Service : [bold]{PROVIDERS[s['provider']][0]}[/]  ({s['url'] or 'adresse à préciser avec --url'})")
    console.print(f"Modèle : {s['model'] or 'à préciser avec --modele'}")
    console.print("Clé : " + ("enregistrée" if s["key"] else f"[yellow]aucune[/] — crée-la sur "
                                                              f"{PROVIDERS[s['provider']][3] or 'le site du service'}"))
    return 0


def cmd_traps(db: Database, args) -> int:
    """Fait écrire par l'IA les mauvaises réponses de QCM des cartes qui n'en ont pas."""
    from revise.engines import distractors
    from revise.quiz import prepared_count

    deck_ids = resolve_decks(db, args.cours, None) or [d.id for d in db.decks()]
    cards = db.cards(deck_ids=deck_ids, include_suspended=False)
    missing = len(cards) - prepared_count(cards)
    if not missing:
        console.print("Toutes les questions ont déjà leurs réponses pièges.")
        return 0
    engine = pick_engine(args.moteur) if args.moteur else distractors.default_engine()
    try:
        getattr(engine, "check", lambda: None)()
        with console.status(f"{missing} questions à préparer…") as status:
            engine.progress = status.update
            filled = distractors.prepare(db, deck_ids, engine.chat, status.update)
    finally:
        getattr(engine, "close", lambda: None)()
    console.print(f"[green]✓[/] Réponses pièges écrites pour {filled} question(s) sur {missing}.")
    return 0


def resolve_decks(db: Database, tokens: list[str] | None, subject: str | None) -> list[int] | None:
    """`--cours 3 8 CM9` : numéros de paquet ou morceaux de titre (« CM8 », « pile »)."""
    if not tokens:
        return None
    decks = db.decks(subject)
    ids: list[int] = []
    for tok in tokens:
        for part in tok.split(","):
            part = part.strip()
            if not part:
                continue
            if part.isdigit() and any(d.id == int(part) for d in decks):
                matches = [d for d in decks if d.id == int(part)]
            else:
                # On cherche dans le titre et dans le nom du PDF d'origine.
                # « CM8 » ne doit pas attraper « CM80 » : on compare des mots entiers d'abord.
                def names(d):
                    return f"{d.title} {Path(d.source).stem if d.source else ''}".lower()
                words = [d for d in decks if part.lower() in re.split(r"[\s\-–—:,()\[\]_.]+", names(d))]
                matches = words or [d for d in decks if part.lower() in names(d)]
            if not matches:
                raise ReviseError(f"aucun cours ne correspond à « {part} » (voir : revise liste)")
            ids += [d.id for d in matches if d.id not in ids]
    return ids


def cmd_review(db: Database, args) -> int:
    from revise import tui

    if not db.subjects():
        console.print("Aucun cours importé. Commence par : [bold]revise importer cours.pdf -m Matière[/]")
        return 1
    if args.matiere and args.matiere.lower() not in {s.lower() for s in db.subjects()}:
        raise ReviseError(f"matière inconnue « {args.matiere} » (connues : {', '.join(db.subjects())})")
    deck_ids = resolve_decks(db, getattr(args, "cours", None), args.matiere)
    if deck_ids:
        titles = ", ".join(d.title for d in db.decks() if d.id in deck_ids)
        console.print(f"Cours : {titles}")
    done = tui.run(db, args.matiere, args.nouvelles, deck_ids, getattr(args, "examen", False))
    console.print(f"{done} carte(s) révisée(s).")
    return 0


def has_display() -> bool:
    import os
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def cmd_app(db: Database, args) -> int:
    try:
        from revise.gui.app import main as gui_main
    except ImportError as e:
        raise ReviseError(f"Interface graphique indisponible ({e}). Installe : .venv/bin/pip install PySide6-Essentials")
    return gui_main(db)


def cmd_shortcut(db: Database, args) -> int:
    import os
    import shutil
    exe = shutil.which("revise") or sys.argv[0]
    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    desktop = apps / "revise.desktop"
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=revise\nComment=Réviser ses CM en cartes (répétition espacée)\n"
        f"Exec={Path(exe).resolve()} app\nIcon=accessories-dictionary\nTerminal=false\n"
        "Categories=Education;\n", encoding="utf-8")
    console.print(f"[green]✓[/] Raccourci créé : {desktop}")
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
    p.set_defaults(cours=None, examen=False)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("importer", aliases=["import"],
                       help="créer des cartes à partir de PDF, ou ajouter un cours partagé (.revise)")
    s.add_argument("pdf", nargs="+")
    s.add_argument("-m", "--matiere", help="matière (défaut : nom du dossier du PDF)")
    s.add_argument("--moteur", choices=["auto", "ia", "en-ligne", "abonnement", "simple"], default="auto",
                   help="ia = IA intégrée, gratuite et hors ligne (défaut ; téléchargée au premier import), "
                        "en-ligne = IA en ligne avec ta clé API gratuite (voir « revise cle »), "
                        "abonnement = ton abonnement Claude, via Claude Code installé sur la machine, simple = sans IA")
    s.add_argument("--titre", help="titre du cours (un seul PDF)")
    s.add_argument("--forcer", action="store_true", help="réimporter un PDF déjà importé (remplace le paquet)")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("partager", help="enregistrer des cours dans un fichier .revise à envoyer à quelqu'un")
    s.add_argument("fichier", help="fichier à écrire, ex. algo.revise")
    s.add_argument("-c", "--cours", nargs="+", metavar="COURS", help="seulement ces cours (défaut : tous)")
    s.add_argument("--anki", action="store_true", help="écrire un fichier texte à importer dans Anki")
    s.set_defaults(func=cmd_share)

    s = sub.add_parser("sauvegarder", help="copier toutes les données (cours, cartes, progression) dans un fichier")
    s.add_argument("fichier")
    s.set_defaults(func=cmd_backup)

    s = sub.add_parser("restaurer", help="remplacer toutes les données par celles d'une sauvegarde")
    s.add_argument("fichier")
    s.add_argument("--oui", action="store_true")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("cle", help="enregistrer la clé API de l'IA en ligne")
    s.add_argument("--fournisseur", choices=["groq", "gemini", "autre"])
    s.add_argument("--cle", help="la clé API")
    s.add_argument("--modele", help="nom du modèle (défaut : celui conseillé pour le fournisseur)")
    s.add_argument("--url", help="adresse de l'API (fournisseur « autre »)")
    s.set_defaults(func=cmd_key)

    s = sub.add_parser("pieges", help="faire écrire par l'IA les mauvaises réponses des QCM (cours déjà importés)")
    s.add_argument("-c", "--cours", nargs="+", metavar="COURS", help="seulement ces cours (défaut : tous)")
    s.add_argument("--moteur", choices=["ia", "en-ligne", "abonnement"], help="défaut : l'IA utilisée pour les imports")
    s.set_defaults(func=cmd_traps)

    s = sub.add_parser("reviser", aliases=["r"], help="lancer une séance de révision")
    s.add_argument("-m", "--matiere")
    s.add_argument("-n", "--nouvelles", type=int, default=20, help="nouvelles cartes max par jour (défaut 20)")
    s.add_argument("-c", "--cours", nargs="+", metavar="COURS",
                   help="seulement ces cours : numéros (revise liste) ou morceaux de titre, ex. --cours CM8 CM9")
    s.add_argument("-e", "--examen", action="store_true",
                   help="bachotage : toutes les cartes tout de suite, dans un ordre aléatoire, jusqu'à les savoir toutes")
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("app", help="ouvrir l'application graphique (par défaut si on tape juste « revise »)")
    s.set_defaults(func=cmd_app)

    s = sub.add_parser("raccourci", help="ajouter revise au menu des applications")
    s.set_defaults(func=cmd_shortcut)

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
            if has_display():
                return cmd_app(db, args)
            if db.subjects():
                args.matiere, args.nouvelles, args.cours, args.examen = None, 20, None, False
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
