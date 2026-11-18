# Publication de revise 1.0.0 (vente sur Payhip)

État au 18/11/2026, 17 h. Reprendre à la section « Reste à faire ».

## Où on en est

**Fait**
- Code : licence par clé (`src/revise/licence.py`, fenêtre `gui/licence_dialog.py`), version **1.0.0**, 214 tests verts. Tout est poussé sur `master` (dernier commit de code : `9acd84b`).
- `BUY_URL` = **https://payhip.com/b/8XCQ2**, déjà dans le code.
- Secret GitHub **`PAYHIP_SECRET`** enregistré (mis à jour le 18/11 à 15:38:45). Le job Windows l'a bien trouvé.
- Payhip :
  - compte créé, **PayPal (compte Particulier) connecté**, devise EUR, libellé bancaire `REVISE` ;
  - produit **revise** créé à 3 €, clés de licence activées, **invisible (HIDDEN)** ;
  - fichier provisoire = la thumbnail (à remplacer) ;
  - pas d'option de prix libre trouvée à la création : à revérifier dans Edit.
- **Coupons à 100 %** (1 utilisation chacun) créés dans Marketing → Coupons, dont un pour l'essai. **Pas encore envoyés.**
- Construction sans Release (`workflow_dispatch`), run **44338165088** :
  - `revise.exe` et `revise-mac-intel.dmg` sont prêts dans `~/Downloads/revise-1.0.0/` ;
  - **`revise-mac-arm64.dmg` (Mac puce Apple) manque.** Le job `macos-15` est resté en file d'attente chez GitHub et a été annulé au bout de 15 min. Il a été relancé (`gh run rerun 44338165088 --failed`).
- Aucun tag `v1.0.0`, aucune Release 1.0.0 : les utilisateurs 0.9 ne voient rien.

**Fait le 18/11 au soir** :
- 3 fichiers récupérés (le Mac puce Apple est passé à la 3e tentative). Payhip refuse `.exe` : ils sont envoyés en `.zip` (`revise-windows.zip`, `revise-mac-arm64.zip`, `revise-mac-intel.zip`), et la description comprend les étapes d'installation.
- **Essai réel réussi sous Windows** : achat à 0 € avec un coupon, clé affichée après l'achat et dans le mail de confirmation, activation, relance sans redemander la clé.

**Pas encore fait** : produit en Visible, envoi des coupons, tag.

## Reste à faire

1. **Récupérer le .dmg puce Apple.**
   ```
   ! cd ~/claudeCode/revise && gh run view 44338165088 --json jobs --jq '.jobs[] | "\(.name): \(.status) \(.conclusion)"'
   ! cd ~/claudeCode/revise && gh run download 44338165088 -n revise-mac-arm64 -D ~/Downloads/revise-1.0.0
   ```
   - Si le job est encore annulé, relancer avec `gh run rerun 44338165088 --failed`.
   - Ou lancer une nouvelle construction complète avec `gh workflow run release.yml --ref master`, puis télécharger les fichiers du nouveau run.
   - Ce n'est pas un bug du code : la machine `macos-15` a marché le 17/11 à 18:10 et le 18/11 à 01:42.
2. **Essai avec une vraie clé**, avant toute vente :
   - « acheter » revise avec ton coupon d'essai (le produit doit être visible ou accessible par lien, sinon le passer en Unlisted le temps de l'essai) ;
   - lancer `revise.exe` sur un Windows et coller la clé reçue : l'app doit s'ouvrir ;
   - sur un 2e ordinateur, la même clé doit être refusée (« déjà activée ») ;
   - libérer ensuite la clé avec la commande `decrease` (section « Commandes utiles »).
3. **Payhip** :
   - remplacer le fichier provisoire par `revise.exe` + `revise-mac-arm64.dmg`. La version Intel est facultative : si tu ne la mets pas, enlever la ligne « Mac Intel » des textes ;
   - vérifier le prix libre dans Edit ;
   - passer le produit en **Visible**.
4. **Envoyer les coupons** aux personnes qui ont déjà l'app.
5. **Tag**, uniquement après l'étape 4 :
   ```
   ! cd ~/claudeCode/revise && git tag v1.0.0 && GIT_SSH_COMMAND="ssh -6" git push origin v1.0.0
   ```
   Si le Mac puce Apple bloque encore pendant ce build, la Release est quand même publiée (`publication` ne dépend que de Windows). Ajouter le `.dmg` ensuite : `gh release upload v1.0.0 ~/Downloads/revise-1.0.0/revise-mac-arm64.dmg`.

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

## Détail des étapes (référence)

Étapes 1 à 5 de la première version de ce fichier : faites le 18/11 (voir « Fait »).
- Le secret se met dans un **terminal normal**, pas avec `!` : `cd ~/claudeCode/revise && gh secret set PAYHIP_SECRET`. Lancée avec `!`, la commande ne peut pas demander la valeur et enregistre un secret vide.
- Construction sans Release : `GIT_SSH_COMMAND="ssh -6" git push origin master && gh workflow run release.yml --ref master`.

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

**Texte après achat / mail de confirmation** (Payhip : champ du mail ou de la page de téléchargement, si présent)

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
