# revise : plan

Réviser ses cours (PDF, PowerPoint, Word, texte) en répétition espacée : application Qt (Windows, Mac, Linux),
plus une ligne de commande. Carte détaillée du code : `CLAUDE.md`.

## Modules (`src/revise/`)
| Fichier | Rôle |
|---|---|
| `db.py` | SQLite (`~/.local/share/revise/revise.db`) : paquets, cartes, révisions |
| `pdf.py` | lecture PDF (pages, texte, découpage en morceaux) |
| `engines/prompt.py` | commun aux IA : consignes, schéma JSON, découpage du texte, filtrage des cartes inventées |
| `engines/embedded.py` | IA intégrée : télécharge llama.cpp et le modèle Gemma 3, lance `llama-server` en arrière-plan |
| `engines/online.py` | IA en ligne : API compatible OpenAI ; clés gratuites (Groq, Gemini, Cerebras, Mistral, OpenRouter), passage au service suivant si un quota est épuisé, service sans clé (Pollinations) en dernier recours |
| `config.py` | réglages (`~/.config/revise/config.json`) et dossier de données |
| `engines/simple.py` | génération sans IA : définitions, énoncés, listes à puces, textes à trous |
| `scheduler.py` | planification FSRS (bibliothèque `fsrs`), file de révision, limite de nouvelles cartes |
| `engines/claude_code.py` | IA de l'abonnement Claude via Claude Code (`claude -p`), modèle au choix |
| `engines/distractors.py` | propositions des QCM écrites par l'IA, toutes de la même longueur (à l'import ou après coup) |
| `quiz.py` | QCM : bonne réponse réécrite + réponses pièges de l'IA, sinon réponses de cartes ressemblantes |
| `gui/` | application Qt : accueil, cours, fiches, QCM, import, révision, statistiques (pages qui défilent) |
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
7. Application Qt, exécutables Windows/Mac (GitHub Actions), mise à jour automatique (0.4 → 0.6)
8. Accueil « Aujourd'hui », interface refaite (0.7)
9. Pages qui défilent, QCM aux propositions équilibrées, choix du modèle Claude, IA en ligne multi-clés et sans clé (0.8)
