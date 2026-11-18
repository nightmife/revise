**Tu as déjà revise ?** À partir de la version 0.6.0, un bouton « Nouvelle version » apparaît en bas à gauche de l'application et l'installe tout seul. Avant la 0.6.0, télécharge le fichier ci-dessous une dernière fois.

**Clé de licence** : au premier lancement, revise demande la clé reçue par mail après l'achat (Internet nécessaire une seule fois).

## Windows

Télécharge **revise.exe** et lance-le. Rien d'autre à installer.
Au premier lancement, Windows affiche « éditeur inconnu » : clique sur « Informations complémentaires » puis « Exécuter quand même ».

## Mac

1. Télécharge le bon fichier : **revise-mac-arm64.dmg** pour un Mac récent (puce Apple M1, M2, M3…), **revise-mac-intel.dmg** pour un Mac Intel (avant 2020). Pour savoir : menu Pomme → « À propos de ce Mac ».
2. Ouvre le fichier `.dmg` et glisse **revise** dans le dossier **Applications**.
3. Ouvre revise depuis Applications. La première fois, le Mac refuse (« Apple n'a pas pu vérifier… ») : clique sur « Terminé », puis va dans **Réglages Système → Confidentialité et sécurité**, descends tout en bas et clique sur **« Ouvrir quand même »**. C'est à faire une seule fois.

Sur un Mac plus ancien (macOS 14 ou avant) : clic droit sur revise → « Ouvrir » → « Ouvrir ».
Autre méthode, dans le Terminal : `xattr -dr com.apple.quarantine /Applications/revise.app`

Cet avertissement apparaît parce que l'application n'est pas signée avec un compte développeur Apple payant (99 € par an). Le code de revise est public dans ce dépôt.
