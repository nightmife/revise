# revise

Transforme tes cours (PDF, PowerPoint, Word, texte) en cartes de révision, puis te les fait réviser au bon
moment (répétition espacée, algorithme FSRS), avec une fiche « Apprendre » et des QCM.

## Installation

**Windows** : télécharge `revise.exe` depuis la page *Releases* du dépôt GitHub et lance-le. Rien d'autre à installer.
Au premier lancement, Windows affiche « éditeur inconnu » : « Informations complémentaires » puis « Exécuter quand même ».

**Mac** : sur la même page *Releases*, télécharge `revise-mac-arm64.dmg` (puce Apple M1 et suivantes) ou
`revise-mac-intel.dmg` (Mac Intel), ouvre-le et glisse revise dans Applications. Au premier lancement le Mac refuse
(application non signée) : Réglages Système → Confidentialité et sécurité → tout en bas, « Ouvrir quand même ».
Détails dans [packaging/INSTALLATION.md](packaging/INSTALLATION.md).

**Linux (Arch)** :

```bash
cd ~/claudeCode/revise
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
ln -s ~/claudeCode/revise/.venv/bin/revise ~/.local/bin/revise   # pour taper juste `revise`
```

## Génération des cartes

Quatre moteurs, au choix dans l'onglet **Ajouter un cours** (ou `--moteur`) :

| Moteur | Coût | Vitesse | Qualité |
|---|---|---|---|
| `ia` — IA intégrée (défaut) | gratuit, hors ligne, sans compte | plusieurs minutes par cours | bonne |
| `en-ligne` — IA en ligne | gratuit : sans clé (lent), ou avec tes clés API gratuites (Groq, Cerebras, Gemini, Mistral, OpenRouter) | ~15 min par cours sans clé, quelques secondes avec | bonne à très bonne |
| `abonnement` — ton abonnement Claude | compris dans l'abonnement (Pro, Max…) | quelques minutes par cours | excellente |
| `simple` — sans IA | gratuit, hors ligne | instantané | correcte : moins de cartes, mais exactes ; QCM facile |

**IA intégrée.** Au premier import, l'application télécharge toute seule le moteur d'IA (llama.cpp, ~40 Mo) et le
modèle : Gemma 3 12B (7,3 Go) si la machine a 16 Go de mémoire ou plus, sinon Gemma 3 4B (2,5 Go). Un téléchargement
interrompu reprend où il s'était arrêté. La carte graphique est utilisée s'il y en a une. Tout est rangé dans
`~/.local/share/revise/ia/` (`~/Library/Application Support/revise/ia/` sur Mac). Pour imposer un modèle : `REVISE_IA_MODELE=4b`, `12b` ou le chemin d'un fichier `.gguf`.

**IA en ligne.** Marche sans rien régler : le service gratuit sans clé de Pollinations écrit les cartes (une réponse
toutes les 45 s par adresse IP, donc environ un quart d'heure par cours). Pour aller vite, bouton « Configurer… » de
l'onglet Ajouter un cours : colle une ou plusieurs clés gratuites (Groq, Cerebras, Google Gemini, Mistral, OpenRouter,
ou tout service compatible OpenAI). Quand le quota gratuit d'un service est épuisé ou qu'une clé est refusée,
l'application passe au suivant, puis au service sans clé. En ligne de commande :
`revise cle --fournisseur groq --cle …` (une clé par service, `--sans-cle non` pour couper le service sans clé). Les
clés restent sur ta machine ; le texte du cours est envoyé au service qui répond.

**Abonnement Claude.** Passe par Claude Code (`claude -p`), qui doit être installé et connecté sur la machine ;
l'option n'apparaît dans l'application que dans ce cas. Aucune clé à créer ; l'usage compte dans les limites de
l'abonnement. Le modèle se choisit à côté de l'option (Automatique, Opus, Sonnet, Haiku) ; en ligne de commande :
`--claude-modele opus`.

**Sans IA.** Repère ce qui s'apprend à coup sûr : énoncés (théorème, définition…), définitions (« Une pile
est… », « On appelle… », « L'impôt : … »), rôles (« X permet de… »), sigles (initiales vérifiées), arrêts et
décisions (« CE, 28 juin 1963, Narcy »), complexités, énumérations (« Les trois critères sont : … ») et dates (texte
à trous). Les en-têtes, pieds de page et pages « à étapes » des diaporamas sont retirés avant.

**Moins d'appels à l'IA.** Avant d'envoyer un cours à une IA, les en-têtes, pieds de page et pages « à étapes »
sont retirés (souvent un bon tiers du texte d'un diaporama). Si un import est coupé (quota épuisé, coupure), le
relancer reprend où il s'était arrêté : les morceaux déjà écrits par l'IA ne sont pas redemandés.

**Formats lus** : PDF, PowerPoint (`.pptx`, une diapositive = une page), Word (`.docx`), texte (`.txt`, `.md`).
Les anciens `.ppt` / `.doc` sont à enregistrer en `.pptx` / `.docx`.

**Pages scannées et schémas** : seul « Mon abonnement Claude » les lit (les pages scannées ou qui portent une
figure lui sont envoyées en PDF, il les regarde). Les autres IA ne lisent que le texte.

**Réponses pièges des QCM.** Après les cartes, l'IA écrit pour chaque question les quatre propositions du QCM : la
bonne réponse, raccourcie si besoin, et trois fausses réponses crédibles, toutes de la même longueur et de la même
forme (si l'une se repère à sa longueur, elles sont redemandées une fois). Les cours préparés avant la version 0.8
n'avaient que les fausses réponses, souvent plus courtes que la bonne : l'onglet QCM propose de les refaire.
Sans réponses pièges (moteur `simple`, cours importés avant la version 0.4), le QCM emprunte les réponses d'autres
questions du cours, qui se repèrent vite. Pour un cours déjà importé : bouton « Préparer les réponses pièges » de
l'onglet QCM, ou `revise pieges` (une seule fois par cours, on peut arrêter et reprendre).

## Utilisation

```bash
revise              # ouvre l'application
revise raccourci    # ajoute « revise » au menu des applications
```

Dans l'application :
- **Accueil** : l'application s'ouvre sur le programme du jour (cartes à revoir, nouvelles cartes, durée estimée)
  avec un seul bouton « Commencer ma révision ». En dessous : série de jours, part des cartes sues, prochain
  examen, et des raccourcis (QCM rapide, fiche, choisir mes cours, ajouter un cours). À la première visite, elle
  montre le mode d'emploi en trois étapes.
- **Comment ça marche ?** (en bas à gauche, ou touche `F1`) : le mode d'emploi en une page et les raccourcis clavier.
- **Ajouter un cours** : glisse des PDF (ou « Choisir des fichiers… »), choisis qui écrit les cartes (et, pour
  l'abonnement Claude, le modèle), « Créer les cartes ». « Configurer… » règle les clés de l'IA en ligne.
  La liste propose tous les cours du dossier choisi (« Choisir le dossier… », par défaut Téléchargements et
  Documents) **et de tous ses sous-dossiers**, rangés par dossier ; la recherche filtre aussi sur le dossier.
  Pendant l'import, une barre donne le pourcentage et le temps restant.
- **Mes cours** : coche un ou plusieurs cours (un clic sur la ligne), puis choisis une activité :
  - **Réviser** : planning de répétition espacée (cartes à revoir, puis nouvelles du jour). Les cartes sont
    posées dans un ordre aléatoire et tirées au hasard dans tous les cours cochés ;
  - **Tout revoir** : toutes les cartes tout de suite, dans un ordre aléatoire, jusqu'à les savoir toutes ; les cartes
    déjà connues sont sautées (on peut quitter et reprendre) ;
  - **Lire la fiche** : le cours partie par partie, réponses visibles ;
  - **QCM** : quatre propositions de même longueur (touches `1` à `4`, `Entrée` pour continuer), score et
    erreurs à refaire.
    Le QCM ne modifie pas le planning de révision.
  - **Examen blanc** : QCM et réponses à écrire mélangés, chronométré, noté sur 20, avec corrigé (une réponse
    écrite mal corrigée par l'application peut être comptée juste).
- **Mettre à jour…** (dans Mes cours) : refait les cartes et les QCM des cours cochés — ceux fabriqués par une
  ancienne version sont marqués ↻, ou ceux dont le fichier a changé — sans perdre la progression (une nouvelle
  carte qui dit la même chose qu'une ancienne reprend son planning). Plus besoin de supprimer et réimporter.
- **Mes points faibles** (Mes progrès, et Accueil) : les questions souvent ratées en révision, au QCM ou en
  examen blanc, et un bouton pour les retravailler.
- **Apparence** (en bas à gauche) : sombre, clair ou automatique (comme le système).
- Révision : `Espace` affiche la réponse, `1` à revoir, `2` difficile, `3` bien, `4` facile,
  `E` corriger la carte, `S` ne plus la poser, `X` « Explique-moi », `P` voir la page du cours,
  `R` « Carte mal faite ? » (l'IA la réécrit d'après la page, tu choisis la version), `Échap` terminer.
  Case **Écrire mes réponses** : tu tapes ta réponse, l'application la compare à la bonne (fautes de frappe et
  accents tolérés, chiffres exacts) et conseille une note.
- **Voir la page du cours** affiche la page du PDF en image (module `pypdfium2`, installé avec l'application),
  sinon son texte ; si le fichier a été déplacé, « Retrouver le fichier… ».
- **Explique-moi** (réponse affichée) : l'IA choisie pour les imports explique la réponse avec d'autres mots
  et un exemple.
- **Date d'examen…** (dans Mes cours) : donne le jour de l'examen des cours cochés. La colonne « Examen » montre
  le compte à rebours et la part des cartes déjà sues, et « Réviser » augmente tout seul le nombre de nouvelles
  cartes par jour pour que tout soit vu à temps (la veille reste libre pour « Tout revoir »).
- Les formules LaTeX des cartes (`$x^2$`, `\(\alpha\)`) s'affichent en clair (x², α) et le code est coloré.
- **Mes progrès** : série, réponses justes, régularité, prévisions.
- **Partager…** (dans Mes cours) : enregistre les cours cochés dans un fichier `.revise` à envoyer à quelqu'un, qui
  le glisse dans « Ajouter un cours » — sans IA ni attente. Les cartes et les réponses pièges sont partagées, pas ta
  progression. Le même bouton exporte aussi vers Anki (fichier texte, Fichier → Importer dans Anki).
- **Sauvegarde…** (en bas à gauche) : copie tous tes cours et ta progression dans un fichier, ou les reprend d'une
  sauvegarde (changement d'ordinateur). Avant une restauration, les données remplacées sont gardées dans
  `avant-restauration.db`, à côté de la base.
- **Mises à jour** : au lancement, l'application regarde s'il existe une version plus récente sur GitHub et affiche
  un bouton en bas à gauche. Sous Windows et Mac, un clic l'installe : téléchargement, vérification de l'empreinte
  et du démarrage de la nouvelle version, remplacement, relance (tes données ne sont pas touchées ; l'ancienne
  version est gardée jusqu'au lancement suivant). Sous Linux, le bouton ouvre la page de téléchargement
  (`git pull` suffit). Rien n'est envoyé ; pour couper la vérification, mets `"check_updates": false` dans le
  fichier de réglages.

En ligne de commande (sans interface) :

```bash
revise importer ~/Downloads/*CM*.pdf -m LIFAPSD      # --moteur ia | en-ligne | abonnement | simple
revise importer cours.pdf --moteur abonnement --claude-modele sonnet   # modèle : auto | opus | sonnet | haiku
revise cle --fournisseur groq --cle gsk_…            # une clé par service (groq, gemini, cerebras, mistral, openrouter)
revise cle --sans-cle non                            # couper le service gratuit sans clé
revise reviser --cours CM7 CM8 --examen
revise pieges --cours CM7                            # réponses pièges des QCM d'un cours déjà importé
revise maj                                           # refaire les cours d'une ancienne version (progression gardée)
revise maj --cours CM7 --fichier CM7-v2.pdf --moteur abonnement   # nouvelle version du fichier d'un cours
revise pieges --moteur abonnement                    # … pour tous les cours, avec l'abonnement Claude
revise stats
revise partager algo.revise --cours CM7 CM8          # cours à envoyer à quelqu'un (--anki : fichier pour Anki)
revise importer algo.revise                          # ajouter un cours partagé
revise sauvegarder ~/revise-sauvegarde.db            # tout mettre à l'abri
revise restaurer ~/revise-sauvegarde.db              # tout reprendre d'une sauvegarde
```

Données : `~/.local/share/revise/revise.db` (SQLite) ; sur Mac `~/Library/Application Support/revise/revise.db`.

## Publier une version (Windows et Mac)

```bash
git tag vX.Y.Z && git push origin master vX.Y.Z      # version d'abord changée dans pyproject.toml et __init__.py
```

GitHub Actions lance les tests sous Windows et macOS, construit `revise.exe` et les deux `revise-mac-….dmg`
(PyInstaller) et les publie dans une Release. Les applications ne sont pas signées (pas de compte développeur) :
d'où l'avertissement au premier lancement.

## Vente sur Gumroad (clé de licence)

`revise.exe` et les `.dmg` demandent une clé de licence au premier lancement (le code source lancé à la main, non :
`REVISE_LICENCE=1 .venv/bin/revise` pour essayer la fenêtre). Les fichiers peuvent rester publics sur GitHub :
sans clé, l'application ne s'ouvre pas.

1. Gumroad → nouveau produit (« Digital product »), prix au choix.
2. Dans le contenu du produit, ajouter le bloc **License key** (« Generate a unique license key per sale ») : il
   affiche le `product_id`.
3. Le recopier dans `src/revise/licence.py` (`PRODUCT_ID`), avec l'adresse de la page de vente (`BUY_URL`). Le build
   d'une étiquette `v…` échoue tant qu'ils sont vides.
4. Accès gratuits : Checkout → Discounts → code à **100 %**, quantité **1** (un code par personne).

Une clé s'active sur 1 ordinateur (`MAX_MACHINES`) ; une clé remboursée ou contestée cesse de marcher
(revérifiée tous les 14 jours quand il y a Internet). Rendre un ordinateur à quelqu'un (jeton d'accès Gumroad :
Settings → Advanced → Applications) :

```bash
curl -X PUT https://api.gumroad.com/v2/licenses/decrement_uses_count \
  -d access_token=JETON -d product_id=PRODUCT_ID -d license_key=CLE
```

## Tests

```bash
.venv/bin/pytest
```
