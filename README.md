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
revise importer ~/Downloads/*CM*.pdf -m LIFAPSD   # génère les cartes (moteur abonnement)
revise importer cours.pdf --moteur simple         # sans IA, gratuit
revise                                            # séance de révision (= revise reviser)
revise reviser -m LIFAPSD -n 30                   # une matière, 30 nouvelles cartes/jour max
revise stats                                      # régularité, prévisions, rétention
revise liste                                      # paquets importés
revise editer 3                                   # retoucher les cartes du paquet 3 dans $EDITOR
revise estimer cours.pdf                          # coût d'un import avec --moteur api
```

Pendant la révision : `Espace` affiche la réponse, `1` à revoir, `2` difficile, `3` bien,
`4` facile, `e` modifier la carte, `s` la suspendre, `q` quitter.

Données : `~/.local/share/revise/revise.db` (SQLite).

## Tests

```bash
.venv/bin/pytest
```
