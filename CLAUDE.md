# revise — carte du projet

Appli de révision à partir de cours en PDF : cartes (répétition espacée FSRS), fiche du cours, QCM.
Public visé : n'importe qui (pas seulement des informaticiens) — textes de l'interface sans jargon.
Python ≥ 3.11, Qt (PySide6), SQLite. Dépôt : `github.com/nightmife/revise` (public).

## Commandes

```bash
.venv/bin/pytest -q                              # tests (92), GUI en offscreen
.venv/bin/revise                                 # ouvre l'appli
.venv/bin/python packaging/revise_gui.py --selftest   # vérifie que la fenêtre se construit
git tag vX.Y.Z && git push origin master vX.Y.Z  # GitHub Actions construit et publie revise.exe + les .dmg Mac
```

Version à changer à deux endroits : `pyproject.toml` et `src/revise/__init__.py`.

## Où est quoi (`src/revise/`)

| Fichier | Rôle |
|---|---|
| `db.py` | SQLite : tables `decks`, `cards`, `reviews` ; classe `Database` ; une seule migration (`_migrate`, `cards.distractors`) ; `backup_to` / `restore_from` (sauvegarde vérifiée, copie de secours `avant-restauration.db`) |
| `share.py` | partage : `export_courses` / `import_file` (fichier `.revise` = JSON, sans progression ni chemin personnel ; contenu reçu vérifié champ par champ), `export_anki` |
| `updates.py` | `available_update()` : dernière Release GitHub comparée à `__version__` ; anonyme, erreurs ignorées ; réglage `check_updates` |
| `models.py` | `CardDraft` (kind qa/cloze/code, question, answer, page, section, distractors), `ReviseError` (message affiché tel quel) |
| `config.py` | `data_dir()` (`~/.local/share/revise` ; Mac : `~/Library/Application Support/revise`), réglages JSON (`~/.config/revise/config.json`, `%APPDATA%` sous Windows, dossier de données sur Mac) |
| `pdf.py` | texte page par page (pypdf) |
| `net.py` | `urlopen` HTTPS avec les certificats de `certifi` (indispensable dans l'appli Mac empaquetée) ; tout appel Internet passe par là |
| `importer.py` | `import_pdf(db, engine, pdf, …)` : dédoublonnage par sha256, appelle `engine.generate` |
| `engines/prompt.py` | commun aux IA : `SYSTEM`, `RULES`, `CARD_SCHEMA`, `text_chunks`, `parse_cards`, filtre `grounded`, `generate_cards(…, chat, label)` |
| `engines/embedded.py` | moteur `ia` : télécharge llama.cpp (version figée `LLAMA_TAG`) + Gemma 3 (12B si RAM ≥ 14 Go, sinon 4B) dans `data_dir()/ia`, lance `llama-server` (Vulkan → sans GPU → build CPU ; Mac : une seule archive, Metal inclus) |
| `engines/online.py` | moteur `en-ligne` : API compatible OpenAI avec la clé de l'utilisateur (`PROVIDERS` : groq, gemini, autre) |
| `engines/distractors.py` | réponses pièges des QCM écrites par l'IA : `add_to_drafts` (fin d'un import), `prepare` (cours déjà en base, lot par lot), `default_engine` |
| `engines/claude_code.py` | moteur `abonnement` : `claude -p` (abonnement Claude de l'utilisateur, sans outils, sortie JSON) ; proposé dans l'interface seulement si `claude_binary()` trouve Claude Code |
| `engines/simple.py` | moteur `simple` : règles sans IA |
| `scheduler.py` | FSRS, `Session` (file de révision ; `cram=True` = mode examen, ordre aléatoire) |
| `quiz.py` | QCM : `build_quiz` ; mauvaises réponses = `Card.distractors` (IA), sinon réponses des cartes les plus ressemblantes |
| `stats.py`, `editfmt.py`, `tui.py`, `cli.py` | stats, édition Markdown, révision en terminal (Textual), commandes |
| `gui/app.py` | `MainWindow` : barre latérale + `QStackedWidget` ; index `COURSES, LEARN, QUIZ, IMPORT, STATS` (l'ordre du menu est différent) ; `open_with` ouvre fiche/QCM sur les cours cochés |
| `gui/backup_dialog.py` | fenêtre « Sauvegarde » (bouton en bas de la barre latérale) |
| `gui/*_page.py`, `review.py`, `courses.py`, `cards_dialog.py` | une page par fichier ; « Partager… » est dans `courses.py`, la réception d'un `.revise` dans `import_page.py` (`ImportWorker`, sans moteur) ; `common.py` (helpers, `ActionCard`, `confirm`), `theme.py` (couleurs, QSS, icône dessinée) |
| `packaging/revise_gui.py` | point d'entrée des exécutables ; `make_icon.py` ; `INSTALLATION.md` = notes de la Release ; `.github/workflows/release.yml` : tests, PyInstaller (exe Windows, .dmg Mac arm64 + Intel), Release |

## Conventions

- Un moteur = une classe avec `name` et `generate(pdf, subject, progress) -> (titre, [CardDraft])`, plus `close()` facultatif.
  Un moteur à IA a aussi `chat(system, user, schema)` et `progress` (utilisés pour les réponses pièges).
  Pour en ajouter un : `cli.pick_engine` (+ `choices` de `--moteur`) et `gui/import_page.py` (`ENGINES`, `make_engine`, bouton radio).
- Ajouter une page : la créer avec `refresh()`, l'ajouter au tuple de `MainWindow.__init__` et à `show_page`.
- Erreurs utilisateur : lever `ReviseError` avec un message en français.
- Les tests n'utilisent ni le réseau ni les réglages réels (fixture `isolated_settings` dans `tests/conftest.py`) ; les moteurs IA reçoivent de faux `chat`/`post`/`opener`.
- Le QCM et « Apprendre » ne modifient jamais le planning FSRS.
- La vérification des mises à jour part de `gui.app.main()`, jamais de `MainWindow.__init__` (tests et `--selftest` sans réseau).
- Un fichier `.revise` vient d'un inconnu : ne jamais lui faire confiance (types, tailles) ; changer le format = incrémenter `share.FORMAT_VERSION`.
- Tout doit marcher sous Windows et macOS (pas de chemin ou de commande propre à Linux hors `cli.cmd_shortcut`).
- Sur Mac, ne jamais lire Téléchargements/Documents sans action de l'utilisateur (demande d'autorisation du système).
- Boîtes de dialogue : `common.confirm` et `save_cancel_buttons` (boutons en français), pas `QMessageBox.question`.

## Non vérifié

- L'IA intégrée et l'IA en ligne n'ont jamais tourné pour de vrai ici (seulement avec des faux serveurs dans les tests).
  Le moteur `abonnement`, lui, a été essayé sur un vrai cours (77 cartes, pièges crédibles, 3 min 45).
- La version Mac (build GitHub Actions, .dmg, IA intégrée) n'a jamais été lancée sur un vrai Mac.
- Les noms de modèles par défaut de `online.PROVIDERS` peuvent être périmés : si le service refuse le modèle,
  `OnlineEngine._replace_model` en choisit un dans la liste du service (`pick_model`) et l'enregistre.
