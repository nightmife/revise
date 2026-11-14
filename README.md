# revise

Transforme tes CM en PDF en cartes de révision, puis te les fait réviser au bon moment
(répétition espacée, algorithme FSRS), avec une fiche « Apprendre » et des QCM.

## Installation

**Windows** : télécharge `revise.exe` depuis la page *Releases* du dépôt GitHub et lance-le. Rien d'autre à installer.
Au premier lancement, Windows affiche « éditeur inconnu » : « Informations complémentaires » puis « Exécuter quand même ».

**Linux (Arch)** :

```bash
cd ~/claudeCode/revise
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
ln -s ~/claudeCode/revise/.venv/bin/revise ~/.local/bin/revise   # pour taper juste `revise`
```

## Génération des cartes

Trois moteurs, au choix dans l'onglet **Importer** (ou `--moteur`) :

| Moteur | Coût | Vitesse | Qualité |
|---|---|---|---|
| `ia` — IA intégrée (défaut) | gratuit, hors ligne, sans compte | plusieurs minutes par cours | bonne |
| `en-ligne` — IA en ligne | gratuit avec ta propre clé API (Groq, Gemini…) | quelques secondes | très bonne |
| `simple` — sans IA | gratuit, hors ligne | instantané | moyenne, à retoucher |

**IA intégrée.** Au premier import, l'application télécharge toute seule le moteur d'IA (llama.cpp, ~40 Mo) et le
modèle : Gemma 3 12B (7,3 Go) si la machine a 16 Go de mémoire ou plus, sinon Gemma 3 4B (2,5 Go). Un téléchargement
interrompu reprend où il s'était arrêté. La carte graphique est utilisée s'il y en a une. Tout est rangé dans
`~/.local/share/revise/ia/`. Pour imposer un modèle : `REVISE_IA_MODELE=4b`, `12b` ou le chemin d'un fichier `.gguf`.

**IA en ligne.** Bouton « Clé API… » de l'onglet Importer (ou `revise cle --fournisseur groq --cle …`) : choisis le
service, colle ta clé gratuite. La clé reste sur ta machine ; le texte du cours est envoyé au service choisi.

Les deux IA lisent le texte du PDF : pas les schémas ni les PDF scannés.

## Utilisation

```bash
revise              # ouvre l'application
revise raccourci    # ajoute « revise » au menu des applications
```

Dans l'application :
- **Importer** : coche les PDF (Téléchargements/Documents listés automatiquement, ou glisser-déposer),
  choisis le moteur, « Importer la sélection ».
- **Mes cours** : coche un ou plusieurs CM puis
  - **Réviser** : planning de répétition espacée (cartes dues + nouvelles du jour) ;
  - **Mode examen** : toutes les cartes tout de suite, dans un ordre aléatoire, jusqu'à les savoir toutes ; les cartes déjà
    sues sont sautées (on peut quitter et reprendre).
- Révision : `Espace` affiche la réponse, `1` à revoir, `2` difficile, `3` bien, `4` facile,
  `E` modifier, `S` suspendre, `Échap` terminer.
- **Apprendre** : le cours en fiche, partie par partie, réponses visibles.
- **QCM** : quatre réponses proposées (touches `1` à `4`, `Entrée` pour continuer), score et erreurs à refaire.
  Le QCM ne modifie pas le planning de révision.
- **Statistiques** : série, rétention, régularité, prévisions.

En ligne de commande (sans interface) :

```bash
revise importer ~/Downloads/*CM*.pdf -m LIFAPSD      # --moteur ia | en-ligne | simple
revise reviser --cours CM7 CM8 --examen
revise stats
```

Données : `~/.local/share/revise/revise.db` (SQLite).

## Publier une version Windows

```bash
git tag v0.3.0 && git push origin master v0.3.0
```

GitHub Actions lance les tests sous Windows, construit `revise.exe` (PyInstaller) et le publie dans une Release.

## Tests

```bash
.venv/bin/pytest
```
