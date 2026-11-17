"""Fenêtre « Comment ça marche ? » : le mode d'emploi en une page."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout

from revise.gui.common import row
from revise.gui.review import markdown_view

HELP = """## Comment ça marche ?

**1. Ajoute un cours.** Dans *Ajouter un cours*, glisse un PDF, un PowerPoint ou un Word. L'application \
le transforme en cartes question-réponse.

**2. Apprends.** *Fiches* te montre le cours résumé, réponses visibles. Lis-le une fois avant de te tester.

**3. Révise chaque jour.** Sur l'*Accueil*, clique sur **Commencer ma révision**. Pour chaque carte : \
cherche la réponse dans ta tête, affiche-la, puis dis honnêtement si tu la savais. L'application repose \
chaque question juste avant que tu l'oublies : quelques minutes par jour suffisent.

**4. Avant un contrôle.** Dans *Mes cours*, coche les cours concernés puis **Tout revoir** : toutes les \
cartes, jusqu'à ce que tu les saches. Donne aussi la **date de l'examen** : le rythme s'adapte tout seul.

**Le QCM** sert à se tester autrement ; il ne change rien au planning de révision.

**L'examen blanc** mélange QCM et réponses à écrire, en temps limité, noté sur 20 avec un corrigé.

**Mes points faibles** (dans *Mes progrès*, et sur l'*Accueil*) : les questions que tu rates souvent, en révision, au QCM ou à l'examen blanc. Un clic pour les retravailler.

**Écrire mes réponses** (case en haut d'une révision) : tape ta réponse avant de la voir ; l'application la compare à celle de la carte et te conseille une note.

**Une carte bizarre ?** Pendant la révision, *Voir la page du cours* montre d'où elle vient, et *Carte mal faite ?* demande à l'IA de la réécrire (tu choisis la version à garder).

**Un cours d'une ancienne version**, ou dont le fichier a changé (marqué ↻ dans *Mes cours*) : coche-le puis *Mettre à jour…* — les cartes et QCM sont refaits, ta progression est gardée.

**Apparence** (en bas à gauche) : sombre, clair, ou comme ton ordinateur.

---

### Au clavier, pendant une révision

| Touche | Action |
|---|---|
| `Espace` | afficher la réponse |
| `1` `2` `3` `4` | à revoir · difficile · bien · facile |
| `X` | demander une explication à l'IA |
| `P` | voir la page du cours |
| `R` | carte mal faite : la faire réécrire par l'IA |
| `Entrée` | (en écrivant ta réponse) la vérifier |
| `E` | corriger la carte |
| `S` | ne plus me poser cette carte |
| `Échap` | terminer la séance |

Pendant un QCM : `1` à `4` pour répondre, `Entrée` pour continuer.
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comment ça marche ?")
        self.resize(680, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 20, 26, 20)
        view = markdown_view(12)
        view.setMarkdown(HELP)
        lay.addWidget(view, 1)
        close = QPushButton("J'ai compris")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        lay.addLayout(row(None, close))
