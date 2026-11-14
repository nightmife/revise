# revise : plan

Réviser ses CM (PDF) en répétition espacée, dans le terminal.

## Modules (`src/revise/`)
| Fichier | Rôle |
|---|---|
| `db.py` | SQLite (`~/.local/share/revise/revise.db`) : paquets, cartes, révisions |
| `pdf.py` | lecture PDF (pages, texte, découpage en morceaux) |
| `engines/prompt.py` | commun aux IA : consignes, schéma JSON, découpage du texte, filtrage des cartes inventées |
| `engines/embedded.py` | IA intégrée : télécharge llama.cpp et le modèle Gemma 3, lance `llama-server` en arrière-plan |
| `engines/online.py` | IA en ligne : API compatible OpenAI avec la clé de l'utilisateur (Groq, Gemini…) |
| `config.py` | réglages (`~/.config/revise/config.json`) et dossier de données |
| `engines/simple.py` | génération sans IA : définitions, énoncés, listes à puces, textes à trous |
| `scheduler.py` | planification FSRS (bibliothèque `fsrs`), file de révision, limite de nouvelles cartes |
| `engines/distractors.py` | réponses pièges des QCM écrites par l'IA (à l'import ou après coup) |
| `quiz.py` | QCM : bonne réponse d'une carte + réponses pièges de l'IA, sinon réponses de cartes ressemblantes |
| `gui/` | application Qt : cours, apprendre, QCM, import, révision, statistiques |
| `tui.py` | séance de révision (Textual) |
| `stats.py` | statistiques : heatmap de régularité, prévisions, rétention, série |
| `editfmt.py` | édition des cartes en Markdown dans `$EDITOR` |
| `cli.py` | commandes `importer`, `cle`, `pieges`, `reviser`, `stats`, `liste`, `cartes`, `editer`, `supprimer` |

## Étapes
1. Projet, venv, dépendances, base de données
2. Extraction PDF + moteur simple + tests
3. Moteur Claude (sortie structurée, découpage des gros PDF, coût) + tests avec client simulé
4. FSRS + file de révision + tests
5. TUI de révision, stats, édition
6. README, essai sur un vrai PDF, commit
