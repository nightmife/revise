# revise

Transforme tes CM en PDF en cartes de révision, puis te les fait réviser au bon moment
(répétition espacée, algorithme FSRS), dans le terminal.

## Installation (Arch Linux)

```bash
cd ~/claudeCode/revise
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
ln -s ~/claudeCode/revise/.venv/bin/revise ~/.local/bin/revise   # pour taper juste `revise`
```

Trois moteurs pour générer les cartes (`--moteur`) :

| Moteur | Coût | Qualité |
|---|---|---|
| `abonnement` (défaut) | inclus dans ton abonnement Claude, via Claude Code (`claude -p`) | excellente |
| `api` | facturé à l'usage (clé `ANTHROPIC_API_KEY`) | excellente |
| `simple` | gratuit, hors ligne | moyenne, à retoucher |

Le moteur `abonnement` demande juste d'être connecté dans Claude Code (`claude` puis `/login`).
Il ne transmet jamais `ANTHROPIC_API_KEY` : rien n'est facturé en dehors de l'abonnement.

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
  - **Mode examen** : toutes les cartes tout de suite, jusqu'à les savoir toutes ; les cartes déjà
    sues sont sautées (on peut quitter et reprendre).
- Révision : `Espace` affiche la réponse, `1` à revoir, `2` difficile, `3` bien, `4` facile,
  `E` modifier, `S` suspendre, `Échap` terminer.
- **Statistiques** : série, rétention, régularité, prévisions.

En ligne de commande (sans interface) :

```bash
revise importer ~/Downloads/*CM*.pdf -m LIFAPSD
revise reviser --cours CM7 CM8 --examen
revise stats
```

Données : `~/.local/share/revise/revise.db` (SQLite).

## Tests

```bash
.venv/bin/pytest
```
