# Raye Linux 1.0 Bêta Brocken

La première bêta de Raye Linux 1.0 : un bureau disposé comme Windows 11,
dessiné aux couleurs de Raye, avec des mises à jour qui s'installent toutes
seules. C'est une bêta. Installez-la sur un ordinateur de rechange ou à côté
de votre système actuel, pas sur la seule machine dont vous dépendez. Une
0.5 Bêta déjà installée reçoit tout ceci par Raye Update ; le nouvel
installateur ne compte que pour les nouvelles installations.

English: https://dl.rayelinux.com/iso/1.0-beta/release-notes-1.0-beta.md

## Nouveautés de la 1.0 Bêta

- **Horloge**, une nouvelle appli : des alarmes qui sonnent même fenêtre
  fermée (jours, son, Répéter), des minuteurs, un chronomètre avec tours et
  des horloges du monde.
- **Carte graphique**, une nouvelle appli : l'état de votre carte graphique
  en direct. Sur les cartes AMD Radeon, elle règle le mode de performance,
  le profil de charge, la limite de puissance et une courbe de ventilateur,
  gardés au redémarrage. Les cartes NVIDIA ont le Panneau de configuration
  NVIDIA, installé avec le pilote et nommé ainsi dans Démarrer.
- **Paramètres > Système > Options de performances** : un seul choix coupe
  les animations, la transparence et les ombres sur un PC lent, ou réglez
  chaque effet à part.
- **Le Raye Store** est bien plus grand : cherchez un programme Windows
  (Photoshop, Office, Battle.net...) et il trouve les applis qui font le
  même travail. Steam et Heroic sont mis en avant, et Steam Play est activé
  pour tous les jeux dès que le Store installe Steam. TeamViewer, Mullvad VPN
  et balenaEtcher ont été ajoutés.
- **Les fichiers .deb** s'installent d'un double-clic, dans une petite
  fenêtre qui va chercher ce qu'il leur faut et explique tout problème en
  mots simples.
- **Les programmes Windows** ont les polices qu'ils demandent, démarrent dans
  leur propre dossier, et les jeux 32 bits peuvent utiliser 4 Go de mémoire.
  Les paquets du Microsoft Store (.msix, .appx) s'ouvrent avec Raye, ou
  disent clairement pourquoi ils ne peuvent pas.
- **Explorateur** : la molette défile de trois lignes par cran comme sous
  Windows, une copie vers une clé USB montre ce qui est vraiment écrit et ne
  se termine que lorsque la clé peut être retirée, et Propriétés et Options
  des dossiers sont plus clairs.
- **Raye Update** est plus discret et plus fiable : les mises à jour de
  Plasma arrivent d'un seul bloc, un fichier qui n'a pas pu être téléchargé
  est simplement réessayé plus tard, et Paramètres montre la vitesse, le
  temps restant et l'état de chaque mise à jour.
- **Démarrage plus rapide** : plus d'attente sur le menu de démarrage tant
  que tout va bien, des fichiers de démarrage plus petits, et les aides des
  vieux programmes ne démarrent que quand l'un d'eux en a besoin.
- **Cartes graphiques plus anciennes** : si le bureau ne s'affiche pas deux
  fois de suite, Raye passe tout seul à un mode d'affichage plus simple.
- **L'installateur** sait installer à côté d'un autre Linux (il peut
  réduire des partitions ext4 et btrfs), fonctionne sur les PC démarrés en
  mode BIOS, et demande avant d'effacer un disque, de supprimer une
  partition ou d'en réduire une. Le menu de la clé a « Check the USB stick
  for errors », et une clé mal écrite le dit au lieu d'une erreur obscure.
- **Les applis web** installées depuis votre navigateur et épinglées à la
  barre des tâches gardent leur propre icône et leur nom.
- Ctrl+Win+Entrée active ou coupe le lecteur d'écran.

## Installer

Téléchargez l'image sur https://rayelinux.com, vérifiez-la, et écrivez-la
sur une clé USB de 8 Go ou plus avec Rufus (mode DD Image) ou balenaEtcher.
Démarrez l'ordinateur sur la clé (souvent F12, F11, F8 ou Échap à
l'allumage).

## Problèmes connus

- Les anciennes cartes AMD (séries RX 400 et 500) peuvent démarrer en basse
  résolution avec peu d'images par seconde sur certains PC. Le mode
  d'affichage plus simple automatique aide certaines cartes, pas toutes ;
  nous y travaillons encore.
- Le noyau Raye n'est pas proposé sur les PC qui utilisent le pilote NVIDIA :
  les modules précompilés de NVIDIA ne se chargent qu'avec le noyau standard.
- La courbe de ventilateur et la limite de puissance de l'appli Carte
  graphique ont été vérifiées sur des données de test, pas encore sur
  chaque génération de carte AMD.
- Tous les programmes Windows ne fonctionnent pas, et les applis faites
  uniquement pour le Microsoft Store ne peuvent pas fonctionner du tout. Les
  programmes qui existent aussi pour Raye (Discord, Steam) s'installent
  mieux depuis le Raye Store.
- Les alarmes ne sonnent que lorsque le PC est allumé : Horloge ne peut pas
  encore le sortir de la veille.

## Signaler un problème

Ouvrez un ticket sur https://github.com/Raye-Linux/releases/issues, ou
écrivez à bonjour@rayelinux.com. Dites quel ordinateur vous avez, ce que
vous avez fait, ce que vous attendiez et ce qui s'est passé. Une photo de
l'écran aide.

Raye Linux est basé sur Ubuntu. Il n'est ni affilié à Canonical Ltd. ni
approuvé par elle.
