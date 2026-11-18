# Publication de revise 1.0.0 (vente sur Payhip)

État au 18/11/2026. La liste dans l'ordre est plus bas, section « Étapes dans l'ordre ».

## Où on en est

**Fait (code)**
- Licence par clé dans les exécutables : `src/revise/licence.py`, fenêtre `src/revise/gui/licence_dialog.py`, 20 tests dans `tests/test_licence.py` (214 au total, tous verts).
- Version passée à **1.0.0** (`pyproject.toml`, `src/revise/__init__.py`).
- Commits locaux `27f8027` (licence Gumroad, abandonnée) et `c1bde76` (passage à Payhip).
- `27f8027` est **déjà poussé** sur GitHub. `c1bde76` ne l'est **pas encore**.
- Aucun tag `v1.0.0`, aucune Release 1.0.0 : les utilisateurs actuels (0.9) ne voient encore aucune mise à jour.

**Choix arrêtés**
- Plateforme : **Payhip**, pas Gumroad. Gumroad ne verse rien sous 100 $ pour la France, ce qui fait environ 50 ventes.
- Prix : **3 € minimum, prix libre au-dessus** (« pay what you want »).
- **1 clé = 1 ordinateur** (`MAX_MACHINES = 1`).
- Statut : pas de micro-entreprise pour une dizaine de ventes. Déclarer le total en **BNC non professionnels** (formulaire 2042-C-PRO) et garder le récap des ventes Payhip.
- Les fichiers restent publics sur GitHub : sans clé, l'app ne s'ouvre pas, et l'auto-update a besoin des Releases.
- Le code source lancé à la main (Linux) ne demande pas de clé. Pour voir la fenêtre quand même : `REVISE_LICENCE=1 .venv/bin/revise`.

**Ce qui manque encore**
- La **clé secrète du produit** Payhip, à mettre dans le secret GitHub `PAYHIP_SECRET`. Elle ne doit **jamais** apparaître dans le dépôt ni dans une conversation.
- L'**adresse de la page de vente** Payhip, à mettre dans `BUY_URL` dans `src/revise/licence.py`.
- Sans ces deux éléments, le build GitHub échoue volontairement, pour ne jamais publier une version gratuite par erreur.

## Étapes dans l'ordre

1. **Payhip : compte.** Créer le compte et connecter **PayPal ou Stripe** pour recevoir l'argent.
2. **Payhip : produit numérique.**
   - Nom `revise`, prix **3 €**, prix libre activé (minimum 3 €).
   - Description, cover et thumbnail : voir plus bas.
   - Cocher **« Generate unique license keys »**.
   - **Ne pas publier encore** si Payhip permet de laisser le produit en brouillon. Sinon, ne pas partager le lien.
3. **Secret GitHub.** La clé secrète du produit apparaît sous la case des licences une fois le produit créé.
   ```
   ! cd ~/claudeCode/revise && gh secret set PAYHIP_SECRET
   ```
   La commande demande la clé : la coller. Elle part sur GitHub sans s'afficher.
4. **`BUY_URL`.** Donner l'adresse de la page à Claude. Il la met dans `licence.py`, lance les tests et commite.
5. **Envoyer le code et construire les fichiers, sans Release.**
   ```
   ! cd ~/claudeCode/revise && GIT_SSH_COMMAND="ssh -6" git push origin master && gh workflow run release.yml --ref master
   ```
   - Lancée à la main (`workflow_dispatch`), la construction fabrique les fichiers sans publier de Release : personne ne reçoit de mise à jour.
   - Compter 20 à 30 minutes.
   - Claude surveille avec `gh run watch`, puis télécharge les 3 fichiers avec `gh run download <id>` dans `~/Downloads/revise-1.0.0/`.
6. **Essayer pour de vrai avant de vendre.**
   - Créer un code de réduction à 100 % et « acheter » soi-même.
   - Lancer le `.exe` (Windows, VM ou PC d'un proche) et coller la clé : l'app doit s'ouvrir.
   - Essayer la même clé sur un 2e ordinateur : elle doit être refusée (« déjà activée »).
   - Libérer ensuite la clé avec la commande `decrease` (section « Commandes utiles »).
   - Si possible, tester aussi un `.dmg` sur un vrai Mac : la version Mac n'a jamais été lancée sur un vrai Mac.
7. **Payhip : déposer les fichiers** `revise.exe`, `revise-mac-arm64.dmg` et `revise-mac-intel.dmg`, puis **publier** le produit.
8. **Codes gratuits.** Un code à 100 %, limité à 1 utilisation, pour chaque personne qui a **déjà** l'app (famille, amis). Leur envoyer **avant l'étape 9**.
9. **Publier la Release** : à partir de là, les apps 0.9 proposent la mise à jour, qui demande une clé.
   ```
   ! cd ~/claudeCode/revise && git tag v1.0.0 && GIT_SSH_COMMAND="ssh -6" git push origin v1.0.0
   ```

## Pièges connus

- **Push en partage de connexion iPhone** : « Could not resolve hostname github.com » → `GIT_SSH_COMMAND="ssh -6"`. Hors partage iPhone, la commande sans ce préfixe marche aussi.
- **Push en HTTPS refusé** quand `.github/workflows` change (le jeton de `gh` n'a pas le droit `workflow`) : pousser en SSH, comme ci-dessus.
- **Un build relancé après publication** fait échouer le job `publication` (la Release existe déjà). Ajouter alors le fichier à la main : `gh release upload v1.0.0 <fichier>`.
- **Ordre des étapes 8 et 9** : si le tag part avant les codes gratuits, les utilisateurs actuels qui font la mise à jour se retrouvent bloqués sans clé.
- **Réponse de Payhip pour une clé inconnue** : selon leur doc, c'est une « réponse vide ». Le code la traite comme « clé inexistante » à l'activation, et ne retire **jamais** une licence déjà active pour ça. Seul `enabled: false` (remboursement) la retire. Ce comportement n'a jamais été observé pour de vrai : l'étape 6 sert aussi à le vérifier. Un mauvais secret donne `401 authentication_fail` (vu pour de vrai) et s'affiche comme une erreur de connexion, pas comme une clé fausse.
- **La clé secrète est dans l'exécutable** : quelqu'un de très motivé peut la retrouver, mais elle ne sert qu'à manipuler une clé qu'on connaît déjà. Pour s'en passer complètement, Payhip propose d'écrire à contact@payhip.com pour une autre méthode adaptée aux applications publiques.

## Commandes utiles

```bash
# Libérer l'ordinateur d'un acheteur (il a changé de PC ou réinstallé)
curl -X PUT https://payhip.com/api/v2/license/decrease -d license_key=CLE --header "product-secret-key: SECRET"

# Voir l'état d'une clé (enabled, uses)
curl -G https://payhip.com/api/v2/license/verify -d license_key=CLE --header "product-secret-key: SECRET"

# Désactiver une clé à la main
curl -X PUT https://payhip.com/api/v2/license/disable -d license_key=CLE --header "product-secret-key: SECRET"
```

Mises à jour suivantes : changer la version, puis `git tag vX.Y.Z` et pousser comme d'habitude. Pas besoin de remettre les fichiers sur Payhip à chaque fois : l'app d'un nouvel acheteur se met à jour toute seule. On peut les remplacer de temps en temps.

## Contenu de la page de vente

**Images**
- Cover : `~/Images/Screenshots/2026-11-18_02-25-57.png`. Capture 1920×1080 de l'accueil avec des cours fictifs, rien de personnel.
- Thumbnail : `~/Images/revise-thumbnail.png`. Icône 1024×1024, régénérable avec `.venv/bin/python packaging/make_icon.py ~/Images/revise-thumbnail.png`.
- Nouvelles captures avec des cours fictifs : `.venv/bin/python packaging/demo_db.py /tmp/demo.db`, puis `REVISE_DB=/tmp/demo.db revise`. Passer en plein écran avec Super+F et capturer avec Super+S.

**Résumé** : Windows et Mac · Clé pour 1 ordinateur · Mises à jour gratuites

**Description**

> Tu passes plus de temps à faire tes fiches qu'à vraiment réviser ? **revise** s'en occupe pour toi.
>
> Donne-lui ton cours (PDF, PowerPoint ou Word) et il en fait des cartes question-réponse, une fiche résumée et des QCM. Il te fait réviser un peu chaque jour, en te reposant chaque question juste avant que tu l'oublies. Quelques minutes par jour suffisent, et tu n'arrives plus à la veille de l'exam en découvrant la moitié du cours.
>
> Tu y trouves aussi :
> - un **examen blanc** noté sur 20, pour savoir où tu en es vraiment ;
> - tes **points faibles**, pour retravailler direct les questions que tu rates souvent ;
> - la **date d'examen** : tu la rentres et le rythme s'adapte pour que tu aies tout vu à temps.
>
> L'IA est intégrée et gratuite : pas de compte, pas d'abonnement, et tes cours restent sur ton ordi.
>
> Ça marche sur **Windows et Mac**. Tu reçois une clé pour 1 ordinateur, et les mises à jour sont gratuites. Au premier lancement, ton ordi peut afficher un avertissement « éditeur inconnu » : c'est normal pour une petite app indépendante, et les étapes pour l'ouvrir sont dans le lien de téléchargement.
>
> Un souci ou une idée ? Réponds au mail de ton achat.

**Détails (si Payhip propose des champs)**
- Système : Windows 10/11, macOS (puce Apple et Intel)
- Licence : 1 ordinateur
- Mises à jour : gratuites
- Formats de cours : PDF, PowerPoint, Word

**Texte après achat / mail de confirmation**

> **Merci pour ton achat !**
>
> 1. Télécharge le fichier pour ton ordinateur :
>    - Windows : `revise.exe`
>    - Mac récent (puce M1, M2…) : `revise-mac-arm64.dmg`
>    - Mac Intel : `revise-mac-intel.dmg`
> 2. Au premier lancement, colle ta clé de licence. Elle marche sur 1 ordinateur.
>
> **Premier lancement :**
> - **Windows** affiche « éditeur inconnu » : clique sur « Informations complémentaires », puis « Exécuter quand même ».
> - **Mac** : ouvre le `.dmg` et glisse revise dans Applications. À la première ouverture, le Mac refuse. Va dans Réglages Système → Confidentialité et sécurité, descends tout en bas et clique sur « Ouvrir quand même ».
>
> C'est à faire une seule fois. Les mises à jour arrivent ensuite toutes seules dans l'app. Un souci ? Réponds simplement à ce mail.

## Notes légales (rappel)

- Vente légale. Pour quelques ventes occasionnelles, pas besoin de micro-entreprise : déclarer en BNC non professionnels. Si les ventes deviennent régulières, passer en micro-entreprise.
- Rattaché fiscalement aux parents : le revenu s'ajoute à leur déclaration (négligeable ici).
- Les licences des bibliothèques utilisées (PySide6 en LGPL, pypdf, etc.) autorisent la vente. Il resterait à joindre leurs notices de licence à l'app : pas encore fait.
- Le service IA sans clé (Pollinations) et le moteur « abonnement » (Claude Code) : vérifier leurs conditions pour un usage dans une app payante.
