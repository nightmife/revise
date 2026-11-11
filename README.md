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

Moteur Claude (recommandé) : crée une clé sur https://console.anthropic.com puis
`export ANTHROPIC_API_KEY=sk-ant-...` (dans `~/.bashrc` pour la garder). Sans clé, le moteur
sans IA est utilisé automatiquement.

## Utilisation

```bash
revise importer ~/Downloads/*CM*.pdf -m LIFAPSD   # génère les cartes (coût affiché avant, moteur Claude)
revise importer cours.pdf --moteur simple         # sans IA, gratuit
revise                                            # séance de révision (= revise reviser)
revise reviser -m LIFAPSD -n 30                   # une matière, 30 nouvelles cartes/jour max
revise stats                                      # régularité, prévisions, rétention
revise liste                                      # paquets importés
revise editer 3                                   # retoucher les cartes du paquet 3 dans $EDITOR
revise estimer cours.pdf                          # coût d'un import avec Claude, sans rien générer
```

Pendant la révision : `Espace` affiche la réponse, `1` à revoir, `2` difficile, `3` bien,
`4` facile, `e` modifier la carte, `s` la suspendre, `q` quitter.

Données : `~/.local/share/revise/revise.db` (SQLite).

## Tests

```bash
.venv/bin/pytest
```
