# revise : plan

Réviser ses CM (PDF) en répétition espacée, dans le terminal.

## Modules (`src/revise/`)
| Fichier | Rôle |
|---|---|
| `db.py` | SQLite (`~/.local/share/revise/revise.db`) : paquets, cartes, révisions |
| `pdf.py` | lecture PDF (pages, texte, découpage en morceaux) |
| `engines/claude.py` | génération des cartes par l'API Claude (PDF envoyé tel quel, sortie JSON structurée, estimation du coût) |
| `engines/simple.py` | génération sans IA : définitions, énoncés, listes à puces, textes à trous |
| `scheduler.py` | planification FSRS (bibliothèque `fsrs`), file de révision, limite de nouvelles cartes |
| `tui.py` | séance de révision (Textual) |
| `stats.py` | statistiques : heatmap de régularité, prévisions, rétention, série |
| `editfmt.py` | édition des cartes en Markdown dans `$EDITOR` |
| `cli.py` | commandes `importer`, `reviser`, `stats`, `liste`, `cartes`, `editer`, `supprimer`, `estimer` |

## Étapes
1. Projet, venv, dépendances, base de données
2. Extraction PDF + moteur simple + tests
3. Moteur Claude (sortie structurée, découpage des gros PDF, coût) + tests avec client simulé
4. FSRS + file de révision + tests
5. TUI de révision, stats, édition
6. README, essai sur un vrai PDF, commit
