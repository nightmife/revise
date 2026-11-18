# revise — carte du projet

Appli de révision à partir de cours en PDF : cartes (répétition espacée FSRS), fiche du cours, QCM.
Public visé : n'importe qui (pas seulement des informaticiens) — textes de l'interface sans jargon.
Python ≥ 3.11, Qt (PySide6), SQLite. Dépôt : `github.com/nightmife/revise` (public).

## Publication en cours

Mise en vente de la 1.0.0 sur Payhip pas terminée : suivre `PUBLICATION.md`, section « Reste à faire » (état au 18/11 17 h).

## Commandes

```bash
.venv/bin/pytest -q                              # tests (214), GUI en offscreen
.venv/bin/revise                                 # ouvre l'appli
.venv/bin/python packaging/revise_gui.py --selftest   # vérifie que la fenêtre se construit
git tag vX.Y.Z && git push origin master vX.Y.Z  # GitHub Actions construit et publie revise.exe + les .dmg Mac
```

Version à changer à deux endroits : `pyproject.toml` et `src/revise/__init__.py`.

## Où est quoi (`src/revise/`)

| Fichier | Rôle |
|---|---|
| `db.py` | SQLite : tables `decks`, `cards`, `reviews`, `quiz_answers` (QCM / examens blancs : `record_quiz_answer`, `set_quiz_answer`) ; classe `Database` ; migrations dans `_migrate` (`cards.distractors`, `cards.quiz_answer`, `decks.exam_date`, `decks.gen_version`) ; `answer_history` (résultats 1 / 0,5 / 0 par carte) ; `replace_deck_cards` (cours refait, progression gardée) ; `backup_to` / `restore_from` (sauvegarde vérifiée, copie de secours `avant-restauration.db`) |
| `share.py` | partage : `export_courses` / `import_file` (fichier `.revise` = JSON, sans progression ni chemin personnel ; contenu reçu vérifié champ par champ), `export_anki` |
| `licence.py` | clé Payhip des exécutables (`required()` : figé + `SECRET`, ou `REVISE_LICENCE=1`) ; `SECRET` = clé secrète du produit, écrite au build dans `_licence_secret.py` (secret GitHub `PAYHIP_SECRET`, jamais commitée) ; `activate` (verify → `enabled`, `uses` < `MAX_MACHINES` → PUT usage, `decrease` si course), réglage `licence` = clé + `product_tag()` + `machine_id()` (haché) ; `due_key` / `remote_status` (fil) / `record` (interface) : revérif tous les `RECHECK_DAYS`, seul `enabled: false` retire la licence (réponse vide ou hors ligne = rien) ; fenêtre `gui/licence_dialog.py` (`ensure_licence` dans `gui.app.main()`) |
| `updates.py` | `available_update()` → `Release` (version + fichiers avec empreinte sha256) : dernière Release GitHub comparée à `__version__` ; anonyme, erreurs ignorées ; réglage `check_updates` |
| `selfupdate.py` | installation automatique (exécutables seulement, `app_target()`) : `download` vérifié → `--selftest` de la nouvelle version → `_swap` (ancienne gardée en `revise-ancien.exe` / `revise.app.ancien`, supprimée au lancement suivant) → `relaunch` ; `child_env()` retire les variables PyInstaller |
| `documents.py` | texte des `.pptx`, `.docx`, `.txt`, `.md` (zip + XML, sans dépendance) ; appelé par `pdf.page_texts` selon l'extension |
| `exam.py` | date d'examen : `days_left`, `new_per_day` (cartes par jour pour tout voir à temps), `readiness` |
| `mathtext.py` | formules LaTeX des cartes → texte lisible (`render` pour du Markdown, `to_text` pour une formule) |
| `models.py` | `CardDraft` (kind qa/cloze/code, question, answer, page, section, distractors, quiz_answer), `ReviseError` (message affiché tel quel) |
| `config.py` | `data_dir()` (`~/.local/share/revise` ; Mac : `~/Library/Application Support/revise`), réglages JSON (`~/.config/revise/config.json`, `%APPDATA%` sous Windows, dossier de données sur Mac) |
| `pdf.py` | texte page par page (pypdf) ; `visual_pages` (pages scannées ou avec schéma), `pages_pdf` (extrait de pages) ; `clean_pages` (en-têtes/pieds de page répétés et pages « à étapes » retirés, numérotation gardée ; `slides=False` pour Word/texte) |
| `pageview.py` | page du cours d'une carte : `render_page` (image via `pypdfium2`, None s'il manque ou échoue), `page_text` |
| `answercheck.py` | `check_answer(tapé, attendu, kind)` → `Check` (juste / presque / faux / vide, mots manquants) : mots importants, fautes tolérées, nombres exacts, oui/non contraires |
| `weak.py` | `weak_cards` : points faibles d'après `answer_history` (ratée, pas sue deux fois de suite depuis) |
| `mock_exam.py` | examen blanc : `build_exam` (part de réponses écrites), `answer_choice`, `answer_written`, `mark` (note /20 au demi-point) |
| `matching.py` | `match_cards(anciennes, nouvelles)` : rapprochement (Jaccard question 0,6 + réponse 0,4, seuil 0,45) pour garder la progression |
| `net.py` | `urlopen` HTTPS avec les certificats de `certifi` (indispensable dans l'appli Mac empaquetée) ; tout appel Internet passe par là |
| `importer.py` | `import_pdf(db, engine, pdf, …)` : dédoublonnage par sha256, appelle `engine.generate` ; `GENERATOR_VERSION` (enregistrée dans `decks.gen_version`, `is_outdated`) ; `update_deck` (refait un cours depuis son fichier ou un nouveau, progression gardée via `matching`) ; `source_file` |
| `engines/__init__.py` | `Progress`, `Step` (message qui porte `fraction` 0-1 et `phase` "work"/"download"), `scaled` (tranche de la barre), `fraction_of` |
| `engines/prompt.py` | commun aux IA : `SYSTEM`, `RULES`, `CARD_SCHEMA`, `text_chunks`, `parse_cards`, filtre `grounded`, `generate_cards(…, chat, label)` (pages passées par `clean_pages` ; réponses gardées dans `data_dir()/cache/cartes` pour reprendre un import coupé, effacées après un import réussi) ; `TRAPS_START` = 0,7 (cartes 70 % de la barre, pièges 30 %) |
| `engines/embedded.py` | moteur `ia` : télécharge llama.cpp (version figée `LLAMA_TAG`) + Gemma 3 (12B si RAM ≥ 14 Go, sinon 4B) dans `data_dir()/ia`, lance `llama-server` (Vulkan → sans GPU → build CPU ; Mac : une seule archive, Metal inclus) |
| `engines/online.py` | moteur `en-ligne` : API compatible OpenAI ; `PROVIDERS` (groq, gemini, cerebras, mistral, openrouter, `sans-cle` = Pollinations sans clé, autre) ; une clé par service (`online_keys`), `chain()` = ordre d'essai (choisi, autres avec clé, sans clé si `online_keyless`) ; `OnlineEngine` passe au service suivant quand l'un échoue (`_ServiceFailed`) |
| `engines/distractors.py` | propositions des QCM écrites par l'IA : bonne réponse réécrite (`right` → `cards.quiz_answer`) + 3 pièges de même longueur ; `imbalance` > 1 = redemandé une fois (`RETRY`) ; `add_to_drafts` (fin d'un import), `prepare` (cartes sans propositions ou d'avant la 0.8), `default_engine` |
| `engines/explain.py` | « Explique-moi » : `explain(question, réponse, …, chat)` |
| `engines/rewrite.py` | « Carte mal faite ? » : `rewrite(question, réponse, texte de la page, …, chat)` → (question, réponse, ce qui a changé) |
| `engines/claude_code.py` | moteur `abonnement` : `claude -p` (abonnement Claude de l'utilisateur, sans outils, sortie JSON) ; modèle `--model` = alias de `MODELS` (réglage `claude_model`, `REVISE_MODELE`, `--claude-modele`) ; `chat_pdf` joint les pages à regarder en PDF dans le message (stream-json), seul moteur à lire scans et schémas ; proposé dans l'interface seulement si `claude_binary()` trouve Claude Code |
| `engines/simple.py` | moteur `simple` : règles sans IA (`course_cards`) : énoncés, sigles vérifiés (`acronym_matches`), arrêts (`ARRET`), complexités, définitions / rôles / « consiste à » (filtre strict `is_term` : pas de verbe, de mot vide, de code), listes annoncées par « : », énumérations, dates en texte à trous ; mieux vaut moins de cartes que des fausses (essayé sur les vrais cours de `~/Documents/Cours`) |
| `scheduler.py` | FSRS, `Session` (file de révision ; `card_ids` = mode examen limité à ces cartes (points faibles) ; ordre aléatoire dans les deux modes : `rng`, rang tiré par carte dans `order` ; mode normal = cartes à revoir d'abord, puis nouvelles tirées au hasard dans tous les cours choisis ; `cram=True` = mode examen) |
| `today.py` | programme du jour : `today()` → `Today` (à revoir, nouvelles, faites, série, maîtrise, prochain examen), `mastery` (cartes sues par cours), `exam_plan` / `new_per_day_for` (rythme relevé si un examen approche) |
| `quiz.py` | QCM : `build_quiz` ; mauvaises réponses = `Card.distractors` (IA, bonne réponse = `quiz_answer` via `right_answer`), sinon réponses des cartes les plus ressemblantes ; `is_prepared`, `outdated_count` |
| `stats.py`, `editfmt.py`, `tui.py`, `cli.py` | stats, édition Markdown, révision en terminal (Textual), commandes |
| `gui/app.py` | `MainWindow` : barre latérale (icônes `theme.nav_icon`) + `QStackedWidget` (chaque page dans une `QScrollArea` via `scrollable`, `current_page()` ; fenêtre jamais plus grande que l'écran) ; index `COURSES, LEARN, QUIZ, IMPORT, STATS, HOME, EXAM` (l'ordre du menu est différent ; la révision est la dernière page) ; `start_weak` (séance sur les points faibles), `next_theme` / `apply_theme` (réglage `theme` : sombre / clair / automatique) ; s'ouvre sur `HOME` ; `open_with` ouvre fiche/QCM sur les cours cochés, `quick_quiz` lance un QCM de 10 questions ; une séance revient à la page d'où elle est partie (`_review_from`) |
| `gui/home_page.py` | accueil « Aujourd'hui » : anneau d'avancement (`Ring`), bouton principal selon l'état du jour, tuiles (série, maîtrise, examen), raccourcis ; mode d'emploi en 3 étapes s'il n'y a aucun cours |
| `gui/help_dialog.py` | « Comment ça marche ? » (F1) : mode d'emploi et raccourcis clavier |
| `gui/backup_dialog.py`, `gui/update_dialog.py` | fenêtres « Sauvegarde » et « Mise à jour » (boutons en bas de la barre latérale) |
| `gui/exam_page.py` | examen blanc : réglages, questions (QCM sans correction immédiate ou réponse écrite), minuterie, note et corrigé (réponse écrite à cocher = comptée juste, `set_quiz_answer`) |
| `gui/update_courses.py` | « Mettre à jour… » de Mes cours : `UpdateCoursesDialog` (moteur au choix, fichier à retrouver, `ImportWorker(updates=…)`) |
| `gui/page_dialog.py` | « Voir la page du cours » : image ou texte, zoom, « Retrouver le fichier… » (`relocate` → `set_deck_source`) |
| `gui/render.py` | `show_markdown(view, texte)` : à utiliser pour tout texte de carte (formules + code coloré par pygments) |
| `gui/*_page.py`, `review.py`, `courses.py`, `cards_dialog.py` | une page par fichier ; « Partager… » est dans `courses.py`, la réception d'un `.revise` dans `import_page.py` (`ImportWorker`, sans moteur) ; `common.py` (helpers, `ActionCard`, `confirm`, `step_header` pour les étapes numérotées, `Background`, `flow` / `FlowLayout` pour une rangée de boutons qui passe à la ligne), `theme.py` (palettes `DARK` / `LIGHT`, `apply(kind)` réécrit les couleurs du module et la QSS (`QSS_TEMPLATE`), `resolve(mode)`, icônes dessinées) ; `Eta` (temps restant) ; `import_page.py` : `find_courses` (recherche à toute profondeur, dossiers `scan_dirs()` = réglage `scan_dirs`, en arrière-plan), `ImportWorker.status(texte, avancement global, phase)` ; `courses.py` dessine la colonne « Maîtrise » avec `MasteryBar` |
| `packaging/revise_gui.py` | point d'entrée des exécutables ; `make_icon.py` ; `demo_db.py` (cours fictifs pour les captures) ; `INSTALLATION.md` = notes de la Release ; `.github/workflows/release.yml` : tests, PyInstaller (exe Windows, .dmg Mac arm64 + Intel), Release |

## Conventions

- Un moteur = une classe avec `name` et `generate(pdf, subject, progress) -> (titre, [CardDraft])`, plus `close()` facultatif.
  Un moteur à IA a aussi `chat(system, user, schema)` et `progress` (utilisés pour les réponses pièges).
  Pour en ajouter un : `cli.pick_engine` (+ `choices` de `--moteur`) et `gui/import_page.py` (`ENGINES`, `make_engine`, bouton radio).
- Ajouter une page : la créer avec `refresh()`, l'ajouter au tuple de `MainWindow.__init__` et à `show_page`.
  Les pages défilent (petite fenêtre, Windows à 125-150 %) : ne pas compter sur la hauteur de la fenêtre ;
  vérifier avec `QT_SCALE_FACTOR=1.5` et une fenêtre de 1280×690. Une rangée de nombreux boutons : `common.flow`
  (pas `row`, qui déborde en largeur).
- Erreurs utilisateur : lever `ReviseError` avec un message en français.
- Les tests n'utilisent ni le réseau ni les réglages réels (fixture `isolated_settings` dans `tests/conftest.py`) ; les moteurs IA reçoivent de faux `chat`/`post`/`opener`.
- Le QCM, l'examen blanc et « Apprendre » ne modifient jamais le planning FSRS (le QCM et l'examen blanc
  enregistrent leurs réponses dans `quiz_answers`, pour les points faibles).
- Couleurs : toujours lire `theme.X` au moment de dessiner (pas en valeur par défaut d'argument ni figée à la
  construction) : le thème peut changer pendant que l'application tourne.
- Changer nettement ce que fabriquent les moteurs = augmenter `importer.GENERATOR_VERSION` : les cours fabriqués
  avant sont proposés à la mise à jour (↻).
- Avancement d'un moteur : `progress(Step(texte, fraction))` ; un téléchargement : `Step(…, phase="download")`.
- Un test ne doit jamais dépendre de l'ordre des cartes d'une séance (aléatoire) : passer `rng=random.Random(graine)` à `Session`, ou raisonner sur la carte affichée.
- Le nombre de nouvelles cartes par jour est un réglage mémorisé (`new_per_day` dans la config), lu par l'accueil et par « Mes cours ».
- La licence (`ensure_licence`, `recheck_in_background`) et la vérification des mises à jour partent de `gui.app.main()`, jamais de `MainWindow.__init__` (tests et `--selftest` sans réseau).
- `generate_cards(…, chat_pdf=None)` : un moteur qui sait regarder un PDF passe son `chat_pdf` ; les autres ne reçoivent que du texte.
- Le build (`release.yml`) essaie pour de vrai la mise à jour automatique : `revise --install-from <fichier>` puis `--selftest` et `--cleanup-update`.
- Build Mac puce Apple sur `macos-15` : `macos-latest` restait en file d'attente sans machine, `macos-14` est retiré
  par GitHub. Même `macos-15` reste parfois en attente puis est annulé au bout de 15 min (17/11, 18/11) : `gh run rerun <id> --failed`. Un build relancé après publication fait échouer le job `publication` (la Release existe) : ajouter le
  fichier à la main avec `gh release upload vX.Y.Z <fichier>` (l'empreinte sha256 est publiée quand même).
- Travail en arrière-plan dans l'interface : `common.Background` (file de messages vidée par une minuterie). Ne jamais émettre un signal Qt ni toucher un widget depuis un `threading.Thread` : plantage aléatoire à la fermeture (vu sur Windows et Mac).
- Un fichier `.revise` vient d'un inconnu : ne jamais lui faire confiance (types, tailles) ; changer le format = incrémenter `share.FORMAT_VERSION`.
- Tout doit marcher sous Windows et macOS (pas de chemin ou de commande propre à Linux hors `cli.cmd_shortcut`).
- Sur Mac, ne jamais lire Téléchargements/Documents sans action de l'utilisateur (demande d'autorisation du système).
- Boîtes de dialogue : `common.confirm` et `save_cancel_buttons` (boutons en français), pas `QMessageBox.question`.

## Non vérifié

- Licence Payhip : essayée pour de vrai le 18/11 sur `revise.exe` (Windows, build du run 44338165088) avec une clé achetée
  à 0 € (coupon) : activation, puis relance sans redemander la clé. Pas encore vus pour de vrai : refus sur un 2e ordinateur,
  « réponse vide » pour une clé inconnue, clé désactivée après remboursement, `machine_id` sur Mac (`ioreg`).

- 0.9 : l'image des pages (`pypdfium2` 5.x) a tourné ici (PDF de cours, fenêtre hors écran) ; les exécutables
  (`--collect-all pypdfium2`) se construisent et démarrent sur les 3 builds, mais l'affichage d'une page n'y a jamais
  été essayé (le `--selftest` n'en affiche pas). Le thème « automatique » suit `styleHints().colorScheme()`
  (non essayé sur un vrai Windows/Mac). La reprise d'import et le nettoyage des pages n'ont tourné qu'avec de faux
  `chat` et avec le moteur sans IA sur de vrais cours.

- L'IA intégrée et l'IA en ligne avec clé n'ont jamais tourné pour de vrai ici (seulement avec des faux serveurs dans
  les tests). Le service sans clé (Pollinations, gpt-oss-20b, 1 réponse / 45 s par IP, code 402 « Retry after Ns ») a
  été essayé pour de vrai (0.8.0). Noms de modèles de Cerebras/Mistral non vérifiés (remplacés via `pick_model` si refusés).
  Le moteur `abonnement`, lui, a été essayé sur un vrai cours (77 cartes, pièges crédibles, 3 min 45).
- La version Mac (build GitHub Actions, .dmg, IA intégrée) n'a jamais été lancée sur un vrai Mac.
- Mise à jour automatique : l'échange des fichiers est essayé dans le build (Windows, Mac arm64 et Intel), le
  téléchargement vérifié a été essayé ici ; la relance (`relaunch`) et le parcours complet depuis la fenêtre
  n'ont jamais tourné sur un vrai Windows ou Mac.
- Lecture des scans/schémas et « Explique-moi » : essayés pour de vrai avec le moteur `abonnement` seulement.
- Refonte de l'interface (0.7.0) : contrôlée sur captures hors écran seulement ; les pages QCM, Mes progrès, fin de
  séance et la fenêtre d'aide n'ont pas été retouchées après relecture (réglages du QCM peu guidés, « 0 min » en fin
  de séance courte, noms de mois qui se chevauchent dans « Régularité »). Pages qui défilent (0.8.0) : contrôlées
  hors écran à 150 % (1280×690), pas sur un vrai Windows.
- Service sans clé : sortie coupée vers 1500 jetons (d'où `reasoning_effort: low` et `KEYLESS_BATCH` = 4 questions par
  lot de pièges) ; peu de cartes par morceau (≈ 4 pour 7 000 caractères). Si un service avec clé tombe en panne au
  milieu des pièges, la suite passe au sans-clé avec des lots de 10 (réponse coupée possible : pièges à refaire).
- Les noms de modèles par défaut de `online.PROVIDERS` peuvent être périmés : si le service refuse le modèle,
  `OnlineEngine._replace_model` en choisit un dans la liste du service (`pick_model`) et l'enregistre.
