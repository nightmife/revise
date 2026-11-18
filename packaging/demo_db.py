"""Base de démonstration pour les captures de la page de vente (cours fictifs, aucune donnée réelle).

Usage : .venv/bin/python packaging/demo_db.py /tmp/demo.db  puis  REVISE_DB=/tmp/demo.db revise"""
import random, sys
from datetime import date, timedelta
from pathlib import Path
from fsrs import Rating
from revise.db import Database, utcnow
from revise.models import CardDraft
from revise.scheduler import apply_review, make_scheduler

COURSES = {
    ("Biologie", "Biologie cellulaire — la mitochondrie"): [
        ("Quel est le rôle principal de la mitochondrie ?", "Produire l'énergie de la cellule (ATP) par la respiration cellulaire."),
        ("Où se déroule le cycle de Krebs ?", "Dans la matrice mitochondriale."),
        ("Que contient la membrane interne de la mitochondrie ?", "La chaîne respiratoire et l'ATP synthase.")],
    ("Histoire", "Histoire contemporaine — la Ve République"): [
        ("En quelle année la Constitution de la Ve République est-elle adoptée ?", "En 1958."),
        ("Qui est le premier président de la Ve République ?", "Charles de Gaulle."),
        ("Que permet l'article 49.3 ?", "Engager la responsabilité du gouvernement sur un texte, adopté sans vote sauf motion de censure.")],
    ("Maths", "Probabilités — variables aléatoires"): [
        ("Espérance d'une loi binomiale B(n, p) ?", "E(X) = np."),
        ("Variance d'une loi binomiale B(n, p) ?", "V(X) = np(1 − p)."),
        ("Que dit la loi des grands nombres ?", "La moyenne empirique converge vers l'espérance quand n grandit.")],
    ("Droit", "Droit constitutionnel — la séparation des pouvoirs"): [
        ("Quel auteur théorise la séparation des pouvoirs ?", "Montesquieu, dans De l'esprit des lois (1748)."),
        ("Quels sont les trois pouvoirs ?", "Législatif, exécutif et judiciaire.")],
}
path = Path(sys.argv[1]); path.unlink(missing_ok=True)
db = Database(path)
rng, sched, now = random.Random(4), make_scheduler(), utcnow()
for (subject, title), qa in COURSES.items():
    drafts = [CardDraft("qa", q, a, page=i + 1) for i, (q, a) in enumerate(qa)]
    drafts += [CardDraft("qa", f"{q.rstrip(' ?')} (point {k}) ?", a, page=k) for k in range(2, 9) for q, a in qa]
    did = db.add_deck(subject, title, None, None, "ia", drafts)
    if subject in ("Biologie", "Maths"):
        db.set_exam_date([did], (date.today() + timedelta(days=12)).isoformat())
cards = db.cards(); rng.shuffle(cards)
for i, c in enumerate(cards[:70]):                  # cartes vues sur 14 jours, revues une 2e et 3e fois
    t = now - timedelta(days=14 - i // 5, hours=rng.randint(0, 5))
    c = apply_review(db, sched, db.card(c.id), Rating.Good, t)
    c = apply_review(db, sched, c, rng.choice([Rating.Good, Rating.Easy]), t + timedelta(days=1))
    if (now - t).days > 6:
        apply_review(db, sched, c, Rating.Good, t + timedelta(days=5))
for c in cards[:4]:                                 # questions souvent ratées
    db.record_quiz_answer(c.id, False); db.record_quiz_answer(c.id, False)
for c in cards[70:78]:                              # un peu de travail fait aujourd'hui
    apply_review(db, sched, db.card(c.id), Rating.Good, now - timedelta(minutes=rng.randint(5, 60)))
db.close()
print(path)
