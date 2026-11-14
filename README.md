# revise

Transforme tes CM en PDF en cartes de révision, puis te les fait réviser au bon moment
(répétition espacée, algorithme FSRS), avec une fiche « Apprendre » et des QCM.

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
| `en-ligne` — IA en ligne | gratuit avec ta propre clé API (Groq, Gemini…) | quelques secondes | très bonne |
| `abonnement` — ton abonnement Claude | compris dans l'abonnement (Pro, Max…) | quelques minutes par cours | excellente |
| `simple` — sans IA | gratuit, hors ligne | instantané | moyenne, à retoucher, QCM facile |

**IA intégrée.** Au premier import, l'application télécharge toute seule le moteur d'IA (llama.cpp, ~40 Mo) et le
modèle : Gemma 3 12B (7,3 Go) si la machine a 16 Go de mémoire ou plus, sinon Gemma 3 4B (2,5 Go). Un téléchargement
interrompu reprend où il s'était arrêté. La carte graphique est utilisée s'il y en a une. Tout est rangé dans
`~/.local/share/revise/ia/` (`~/Library/Application Support/revise/ia/` sur Mac). Pour imposer un modèle : `REVISE_IA_MODELE=4b`, `12b` ou le chemin d'un fichier `.gguf`.

**IA en ligne.** Bouton « Configurer… » de l'onglet Ajouter un cours (ou `revise cle --fournisseur groq --cle …`) : choisis le
service, colle ta clé gratuite. La clé reste sur ta machine ; le texte du cours est envoyé au service choisi.

**Abonnement Claude.** Passe par Claude Code (`claude -p`), qui doit être installé et connecté sur la machine ;
l'option n'apparaît dans l'application que dans ce cas. Aucune clé à créer ; l'usage compte dans les limites de
l'abonnement.

Les IA lisent le texte du PDF : pas les schémas ni les PDF scannés.

**Réponses pièges des QCM.** Après les cartes, l'IA écrit pour chaque question trois fausses réponses crédibles sur
le même sujet. Sans elles (moteur `simple`, cours importés avant la version 0.4), le QCM emprunte les réponses d'autres
questions du cours, qui se repèrent vite. Pour un cours déjà importé : bouton « Préparer les réponses pièges » de
l'onglet QCM, ou `revise pieges` (une seule fois par cours, on peut arrêter et reprendre).

## Utilisation

```bash
revise              # ouvre l'application
revise raccourci    # ajoute « revise » au menu des applications
```

Dans l'application :
- **Ajouter un cours** : glisse des PDF (ou « Choisir des PDF… »), choisis qui écrit les cartes, « Créer les cartes ».
- **Mes cours** : coche un ou plusieurs cours (un clic sur la ligne), puis choisis une activité :
  - **Réviser** : planning de répétition espacée (cartes à revoir + nouvelles du jour) ;
  - **Tout revoir** : toutes les cartes tout de suite, dans un ordre aléatoire, jusqu'à les savoir toutes ; les cartes
    déjà connues sont sautées (on peut quitter et reprendre) ;
  - **Lire la fiche** : le cours partie par partie, réponses visibles ;
  - **QCM** : quatre propositions (touches `1` à `4`, `Entrée` pour continuer), score et erreurs à refaire.
    Le QCM ne modifie pas le planning de révision.
- Révision : `Espace` affiche la réponse, `1` à revoir, `2` difficile, `3` bien, `4` facile,
  `E` corriger la carte, `S` ne plus la poser, `Échap` terminer.
- **Mes progrès** : série, réponses justes, régularité, prévisions.

En ligne de commande (sans interface) :

```bash
revise importer ~/Downloads/*CM*.pdf -m LIFAPSD      # --moteur ia | en-ligne | simple
revise reviser --cours CM7 CM8 --examen
revise pieges --cours CM7                            # réponses pièges des QCM d'un cours déjà importé
revise pieges --moteur abonnement                    # … pour tous les cours, avec l'abonnement Claude
revise stats
```

Données : `~/.local/share/revise/revise.db` (SQLite) ; sur Mac `~/Library/Application Support/revise/revise.db`.

## Publier une version (Windows et Mac)

```bash
git tag v0.4.0 && git push origin master v0.4.0
```

GitHub Actions lance les tests sous Windows et macOS, construit `revise.exe` et les deux `revise-mac-….dmg`
(PyInstaller) et les publie dans une Release. Les applications ne sont pas signées (pas de compte développeur) :
d'où l'avertissement au premier lancement.

## Tests

```bash
.venv/bin/pytest
```
