# Raye Linux 0.5 Bêta Alpenglow

Une mise à jour de la 0.3 Bêta de Raye Linux : un bureau disposé comme
Windows 11, dessiné aux couleurs de Raye, avec des mises à jour qui
s'installent toutes seules. C'est une bêta : installez-la sur un
ordinateur de rechange ou à côté de votre système actuel, pas sur la
seule machine dont vous dépendez. Une 0.3 Bêta déjà installée reçoit
tout ceci par Raye Update.

English: https://dl.rayelinux.com/iso/0.5-beta/release-notes-0.5-beta.md

## Nouveau dans la 0.5

- **Les archives dans l'Explorateur de fichiers**, avec le moteur
  d'archives de Raye : ZIP, 7z, RAR, tar et d'autres s'ouvrent comme des
  dossiers, même sans extension. Extraire tout, Extraire ici, Compresser
  en ZIP, 7z ou tar.zst, et une fenêtre Ajouter à l'archive avec les
  niveaux, le découpage en parties et les mots de passe. Les archives RAR
  s'ouvrent mais ne se créent pas.
- **Les programmes Windows** tournent sur la couche propre à Raye, qui
  apporte .NET, le moteur web que certains programmes intègrent, et
  DirectX par Vulkan. Les bibliothèques Visual C++ et les polices de base
  de Microsoft arrivent en arrière-plan dès que le PC est en ligne. Un
  programme n'ouvre plus tout seul le sélecteur de partage d'écran, la
  capture d'écran passe par ce sélecteur, OBS Studio pour Windows démarre
  et enregistre, et FL Studio peut faire tourner le son à 44,1 kHz. Taper
  notepad ou regedit dans un terminal ouvre l'appli Raye.
- **Le Raye Store** propose des programmes Windows connus et dit comment
  chacun fonctionne ici : Optimisé pour Raye, Fonctionne sur Raye ou Ne
  fonctionne pas sur Raye, avec la raison.
- **Sécurité de l'appareil**, dans les Paramètres : activer ou désactiver
  le chiffrement du disque pendant que le PC tourne, avec une clé de
  récupération montrée une seule fois, et les étapes pour activer le
  Secure Boot.
- **Le Panneau de configuration** est rempli avec les éléments classiques
  et leurs tâches.
- **Paramètres** : les pages Sons et Manettes, Protection contre les virus
  et menaces, et un interrupteur pour le petit son joué quand on change
  le volume.
- **Pour les développeurs**, dans Paramètres > Système > Avancé : le Mode
  développeur, le Portail d'appareil (une page web pour gérer ce PC
  depuis un autre sur votre réseau) et OpenSSH avec clés seulement.
- **Mises à jour** : Ctrl+Alt+Suppr et l'écran de verrouillage proposent
  Mettre à jour et redémarrer quand des mises à jour sont prêtes, Installer
  maintenant dit quand il attend le chargeur, et un redémarrage est
  redemandé quand de nouvelles versions des mêmes paquets arrivent.
- **L'accès root** est ce que demandent les invites de mot de passe, et
  les comptes sont Utilisateur sudo ou Utilisateur standard. L'Éditeur du
  Registre demande le mot de passe root pour chaque changement du système
  et ne touche pas aux fichiers qui appartiennent aux paquets.
- **Réseau** : ni pages Wi-Fi ni liste Wi-Fi sur un PC sans carte Wi-Fi, et
  les Paramètres rapides disent Ethernet quand un câble est branché.
- **Démarrage** : une image de démarrage plus petite et plus d'attente du
  réseau rendent le démarrage plus rapide, l'écran de démarrage est au
  milieu de chaque écran, le menu de démarrage a une entrée « Raye Linux,
  états précédents » pour démarrer sur un point de restauration, et une
  installation sans chiffrement garde le menu de démarrage caché.
- **Bureau** : le centre de notifications et le calendrier tiennent
  toujours dans l'écran, le menu Démarrer glisse en douceur, la recherche
  répond plus vite, et un petit son se fait entendre quand on change le
  volume.
- **L'installation** est plus sobre : des illustrations plates, des
  champs de mot de passe nommés et un moyen d'afficher le mot de passe du
  disque.
- **Le mode jeu** passe à un ordonnanceur fait pour les jeux le temps
  d'une partie.
- Les Performances du Gestionnaire des tâches ne clignotent plus, les
  menus et les volets sont de nouveau opaques, et les textes anglais
  suivent l'orthographe américaine.

## Nouveau dans la 0.3

- **Gestionnaire des tâches** avec Processus, Performances, Applications
  de démarrage, Utilisateurs, Détails et Services. Il remplace le
  Moniteur système.
- **Explorateur de fichiers** redessiné : onglets dans la barre de titre,
  barre d'adresse et barre de commandes, Accueil, Ce PC, Galerie, les huit
  affichages de Windows et une nouvelle fenêtre Propriétés.
- **Calendrier**, **Panneau de configuration** et **Éditeur du Registre**,
  ceux de Raye. L'horloge montre les événements du jour.
- **Des mises à jour sans redémarrage** : seuls le noyau, les pilotes, les
  micrologiciels et le bureau lui-même attendent un redémarrage, et chacun
  le dit. Le reste s'installe pendant que vous travaillez.
- **Démarrage et arrêt** restent sur l'image de Raye du menu de démarrage
  jusqu'à l'écran de connexion, sans texte.
- **Paramètres rapides** avec des pages pour le réseau, le Bluetooth et le
  son, des couleurs plus calmes, de nouveaux fonds d'écran (dont deux
  animés) et de nouveaux pointeurs.
- **Points de restauration** pris chaque jour et autour de chaque mise à
  jour, et Points de restauration pour revenir en arrière.

## Ce qu'il contient

- **Bureau** : barre des tâches centrée avec Démarrer, les applis
  épinglées et l'horloge sur chaque écran, un menu du clic droit avec le
  Gestionnaire des tâches et les paramètres de la barre, Win+R pour
  lancer un programme, un dossier ou une adresse web. Les couleurs Raye
  Nuit, la police Inter, les fonds d'écran et les icônes Raye.
- **Installateur** : une installation guidée en français et en anglais.
  Il suit la connexion réseau en direct, peut garder Windows à côté de
  Raye et peut chiffrer le disque avec la puce TPM, pour ne taper un mot
  de passe que si quelque chose a changé.
- **Paramètres Raye** : une seule appli pour le système, avec Affichage
  (choisir l'écran principal), Barre des tâches, Wi-Fi, Bluetooth, son,
  comptes, mises à jour, pilotes et noyau Raye.
- **Raye Store** : les applis de Flathub et celles de Raye, avec la
  progression et Annuler pendant l'installation, Ouvrir et Désinstaller
  une fois installées. Les liens de la recherche du menu Démarrer ouvrent
  la fiche de l'appli dans le Store.
- **Raye Update** : les mises à jour du système, de sécurité et des
  applis se téléchargent en arrière-plan. La plupart s'installent tout de
  suite ; celles qui demandent un redémarrage s'installent au redémarrage
  suivant, avec la progression sur l'écran de démarrage. Elles attendent
  quand vous êtes sur batterie, sur une connexion limitée ou en train de
  jouer.
- **Programmes Windows** : beaucoup d'installateurs .exe s'ouvrent d'un
  double-clic et ajoutent leur entrée au menu Démarrer.
- **Démarrage sécurisé (Secure Boot)** reste activé. Le noyau Raye 7.0 est
  inclus et s'active depuis les Paramètres, sans connexion.
- **Écrans de verrouillage et de connexion** au style Raye, avec le champ
  du mot de passe sur l'écran où se trouve la souris, et Arrêter et
  Redémarrer qui fonctionnent.

## Avant de commencer

- Un ordinateur 64 bits Intel ou AMD qui démarre en mode UEFI (la plupart
  des ordinateurs depuis 2012). Les machines BIOS seulement ne peuvent pas
  démarrer cette image.
- 4 Go de mémoire (8 Go conseillés) et 25 Go d'espace disque libre, le
  chiffre que l'installateur exige lui-même.
- Une clé USB de 8 Go ou plus. Tout ce qu'elle contient sera effacé.
- Une connexion Internet pendant l'installation est utile, mais pas
  obligatoire.
- Raye occupe environ 680 Mio de mémoire à l'écran de connexion, avant toute
  ouverture de session (la médiane de huit démarrages dans une machine
  virtuelle de 4 Go), et environ 1200 Mio une fois la session ouverte, sans
  rien d'ouvert. 4 Go est donc le minimum qui fonctionne, et 8 Go le
  chiffre confortable.

## Télécharger et vérifier

| Fichier | |
|---|---|
| `raye-0.5-beta-amd64.iso` | l'image, sur https://dl.rayelinux.com/iso/0.5-beta/ |
| `raye-0.5-beta-amd64.iso.part1`, `.part2` | la même image en deux morceaux, sur GitHub (limite de 2 Go par fichier) |
| `SHA256SUMS`, `SHA256SUMS.asc` | les sommes de contrôle et leur signature |
| `raye-archive.asc` | la clé de l'archive Raye Linux |

Depuis GitHub, recollez d'abord les morceaux :

    cat raye-0.5-beta-amd64.iso.part1 raye-0.5-beta-amd64.iso.part2 > raye-0.5-beta-amd64.iso

Dans une invite de commandes : `copy /b raye-0.5-beta-amd64.iso.part1 + raye-0.5-beta-amd64.iso.part2 raye-0.5-beta-amd64.iso`

Puis vérifiez le téléchargement :

    gpg --show-keys raye-archive.asc      # empreinte EA73 69D4 C3A3 10B2 DF3D  FC16 D3AA 2E62 5DDE 161E
    gpg --import raye-archive.asc
    gpg --verify SHA256SUMS.asc SHA256SUMS
    sha256sum --check --ignore-missing SHA256SUMS

`gpg --verify` doit afficher « Good signature from Raye Linux Archive
Signing Key », et `sha256sum` doit afficher `raye-0.5-beta-amd64.iso: OK`.

## L'écrire sur une clé USB

- **Rufus** : choisissez l'ISO et, quand il le demande, écrivez-la en
  **mode image DD**. Le mode ISO de Rufus donne une clé qui ne démarre pas.
- **balenaEtcher** : choisissez l'ISO, la clé, puis Flash.
- **dd** sous Linux (remplacez `sdX` par votre clé, vérifiez deux fois avec
  `lsblk`) :
  `sudo dd if=raye-0.5-beta-amd64.iso of=/dev/sdX bs=4M conv=fsync status=progress`

Démarrez l'ordinateur sur la clé (souvent F12, F11, F8 ou Échap à
l'allumage).

## Problèmes connus

- L'écran devient noir 3 à 5 secondes juste avant que l'écran de
  connexion apparaisse.
- Certaines applis gardent encore leur propre allure : le terminal,
  l'outil de capture et quelques boîtes de dialogue sont aux couleurs de
  Raye, mais pas encore redessinés en applis Raye.
- Le menu Démarrer et la barre des tâches sont proches de Windows 11, mais
  pas encore identiques (champ de recherche, section Recommandé).
- L'image de compte par défaut n'est pas la même à l'écran de connexion et
  à l'écran de verrouillage. Un bouton « OK » isolé s'affiche sous « Mot
  de passe incorrect ».
- Programmes Windows : le premier programme ouvert après l'installation
  prend du temps, certains installateurs montrent une fenêtre grise à
  l'ancienne, et tous les programmes ne fonctionnent pas. Les programmes
  qui existent aussi pour Raye (Discord, Steam) s'installent mieux depuis
  le Raye Store.
- Les polices de base de Microsoft n'arrivent qu'une fois le PC passé en
  ligne après l'installation. Un programme Windows ouvert avant reçoit
  une police du système à la place, si bien que quelques fenêtres sont
  mal disposées.
- Les jeux Windows ont à peine été essayés. Les programmes dessinent par
  Vulkan, mais le seul jeu joué jusqu'ici est un vieux jeu Direct3D 9, et
  aucun jeu Direct3D 11 ou 12 n'a été essayé sur une vraie carte
  graphique.
- Les programmes faits avec .NET ont à peine été essayés. Raye apporte
  .NET et le moteur web que certains programmes intègrent, mais
  l'installateur de Paint.NET s'arrête encore sur une erreur.
- Roblox Studio ne permet pas encore de se connecter depuis sa propre
  fenêtre : passez par Login via Browser.
- Raye Update va chercher les paquets de Raye sur rayelinux.com
  et sur GitHub. Tant que vous n'êtes pas connecté, les Paramètres
  indiquent que la recherche de mises à jour n'a pas pu se faire.
- Les mesures de performance face à Windows sur du vrai matériel ne sont
  pas encore faites.
- `add-apt-repository -c` et `-p` (ajouter un composant ou une poche) peuvent
  choisir la source des paquets de Raye et la réécrire. apt répond alors 404
  pour les paquets Raye, et comme le fichier appartient à un paquet, il est
  remplacé à la mise à jour suivante. Ajoutez un PPA avec
  `add-apt-repository ppa:...` tout court, qui écrit son propre fichier. Si
  c'est déjà arrivé : `sudo apt install --reinstall raye-archive-keyring`.
- Les paquets source sont déclarés mais éteints, pour qu'`apt update` ne
  télécharge pas 18 Mo d'index de sources sur chaque machine. Pour compiler
  un paquet depuis ses sources, allumez-les d'abord :
  `sudo sed -i 's/^Enabled: no$/Enabled: yes/' /etc/apt/sources.list.d/ubuntu.sources && sudo apt update`.
- Le liseré qui marque l'élément actif est peu visible sur quelques surfaces
  sombres, et davantage encore si vous choisissez une couleur d'accent très
  claire ou très foncée. Le texte et les commandes gardent leur contraste ;
  c'est le fin anneau de focus qui n'atteint pas toujours le 3:1 qu'attend
  quelqu'un qui navigue au clavier.

## Signaler un problème

Ouvrez un ticket sur https://github.com/Raye-Linux/releases/issues ou
écrivez à bonjour@rayelinux.com. Dites quel ordinateur vous avez, ce que
vous avez fait, ce que vous attendiez et ce qui s'est passé. Une photo de
l'écran aide beaucoup.

Raye Linux est basé sur Ubuntu. Il n'est ni affilié à Canonical Ltd. ni
approuvé par elle.
