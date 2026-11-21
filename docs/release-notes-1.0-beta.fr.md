# Raye Linux 1.0 Bêta Sundog

La deuxième bêta de Raye Linux 1.0, sortie le 21 novembre 2026. Elle
apporte un second bureau au choix, une apparence Windows 10, vos fichiers
de Windows, un mode jeu automatique et beaucoup de corrections. C'est
toujours une bêta : installez-la sur un ordinateur de rechange ou à côté de
votre système actuel, pas sur la seule machine dont vous dépendez.

English: https://dl.rayelinux.com/iso/1.0-beta/release-notes-1.0-beta.md

## Mettre à jour ou installer

- **Déjà sous Raye (0.5 Bêta ou 1.0 Bêta Brocken) ?** Pas besoin du nouveau
  téléchargement. Raye Update apporte Sundog tout seul. Pour l'avoir tout de
  suite, ouvrez Paramètres > Raye Update et cliquez sur Rechercher des mises
  à jour, puis redémarrez quand il le demande. La mise à jour s'installe
  pendant le redémarrage ; laissez le PC allumé jusqu'au retour du bureau.
- **Nouvelle installation :** téléchargez l'image sur
  https://rayelinux.com/fr/telecharger/, vérifiez-la, et écrivez-la sur une
  clé USB de 8 Go ou plus avec Rufus (mode DD Image) ou balenaEtcher.
  Démarrez l'ordinateur sur la clé (souvent F12, F11, F8 ou Échap à
  l'allumage).

## Nouveautés de la 1.0 Bêta Sundog

- **Choisissez votre bureau.** L'installation demande quel bureau vous
  voulez : KDE Plasma (le bureau Raye que vous connaissez) ou Hyprland, un
  bureau en mosaïque plus léger avec la même barre des tâches, le même menu
  Démarrer, les mêmes paramètres rapides et notifications. Paramètres >
  Personnalisation > Environnement de bureau passe de l'un à l'autre en
  quelques secondes, sans mot de passe, et vos applis ouvertes reviennent.
  L'écran de connexion montre quel bureau il va ouvrir.
- **Une apparence Windows 10.** Paramètres > Personnalisation propose un
  style Windows 10 : barre des tâches à gauche avec une zone de recherche,
  coins carrés, et un menu Démarrer avec une liste d'applis et des groupes
  de vignettes redimensionnables.
- **Des animations comme sous Windows.** Les fenêtres s'ouvrent et se
  ferment comme sous Windows 11, l'agrandissement et l'ancrage sont animés,
  et Démarrer, les volets et les menus apparaissent en fondu.
- **Vos fichiers de Windows.** Une nouvelle page, Paramètres > Comptes >
  Fichiers de Windows, copie les Documents, Images, Musique, Vidéos,
  Téléchargements et le Bureau de chaque compte Windows, avec le fond
  d'écran et les favoris du navigateur. Windows est seulement lu, jamais
  modifié, et chaque fichier est vérifié après la copie. Si vous installez
  Raye à côté de Windows, c'est proposé après la première connexion. Quand
  Raye remplace un autre système, il garde maintenant aussi votre fond
  d'écran, vos réseaux Wi-Fi, votre profil Firefox ou Chrome et vos applis
  Flatpak.
- **Le mode jeu s'active tout seul** pendant un jeu Steam, du Store ou
  Windows : processeur à pleine vitesse, un ordonnanceur pour les jeux,
  effets en pause et meilleur mode d'alimentation sur secteur. Tout revient
  à la fin du jeu. Paramètres > Jeux > Mode jeu liste les jeux trouvés.
- **NVIDIA :** les jeux tournent de nouveau à pleine vitesse après
  l'installation ou la mise à jour du pilote (ce correctif est aussi parti
  en mise à jour urgente le 20 novembre). Paramètres ne propose que le
  pilote NVIDIA recommandé, et Écran et graphismes ouvre le Panneau de
  configuration NVIDIA.
- **Les cartes AMD récentes** (RX 5000 et plus, graphismes Ryzen récents)
  n'ont plus d'écran noir sans écran de démarrage pendant la première mise
  à jour. Les PC restés bloqués dans le mode sans échec en basse résolution
  retrouvent leurs graphismes normaux.
- **Des mises à jour fiables.** Une mise à jour finit toujours sur la
  version la plus récente, même si une nouvelle sort pendant le
  téléchargement. Les mises à jour ne s'arrêtent plus à moitié, et un PC
  resté à moitié mis à jour se répare tout seul (aussi parti en mise à jour
  urgente le 20 novembre). Rechercher des mises à jour donne toujours une
  réponse, même juste après l'installation. Les mises à jour d'Ubuntu
  viennent maintenant d'abord d'un serveur de votre pays, les autres en
  secours.
- **Moins de mémoire.** Environ 850 Mo au repos, contre environ 1 Go avant.
  Le Store, Paramètres, Horloge, le Gestionnaire des tâches et l'Explorateur
  en utilisent nettement moins.
- **Raye Store :** Affinity, TikTok LIVE Studio et rekordbox, et chercher
  une appli de DJ montre aussi Mixxx. 14 programmes Windows de plus, chacun
  installé et essayé d'abord (foobar2000, ShareX, WinMerge, SumatraPDF,
  iTunes, l'appli EA et d'autres). La Bibliothèque ne liste que les applis
  que vous avez installées, Obtenir les mises à jour installe tout de suite
  les mises à jour des applis, le Store a sa page de paramètres et des
  raccourcis clavier comme sous Windows (F1 les liste). Synaptic n'est plus
  là : le Store fait son travail.
- **Les programmes Windows** ouvrent et enregistrent les fichiers avec la
  fenêtre de Raye, en partant de Documents. Ils voient votre webcam, ont un
  synthé MIDI intégré et une imprimante Imprimer en PDF, et reçoivent ce
  qu'il leur faut au premier démarrage (Visual Basic 6, .NET 6 à 9 et
  d'autres). Le Gestionnaire des tâches montre chacun sous son propre nom
  et son icône.
- **Sûr par défaut :** le pare-feu est activé, chaque réseau Wi-Fi reçoit
  une adresse matérielle privée, et le DNS chiffré est à un clic dans les
  propriétés du réseau. Les fichiers OpenVPN (.ovpn) s'ajoutent dans
  Paramètres > VPN.
- **Une veille qui ne casse rien.** Si un PC ne se réveille pas de la
  veille deux fois de suite, Raye coupe la veille et le dit ; fermer le
  capot verrouille alors le PC et éteint l'écran. Paramètres > Système >
  Alimentation la réactive.
- **Les alarmes d'Horloge** sortent le PC de la veille quand le PC le
  permet, et le disent clairement sinon. Le calendrier de l'horloge de la
  barre des tâches a un bouton « Alarmes et horloge ».
- **Plus de paramètres, comme Windows 11 :** Assistant de stockage
  programmé, Ne pas déranger à heures fixes, boutons de barre des tâches
  plus petits, trouver le pointeur avec Ctrl, une disposition de clavier
  par fenêtre, l'orthographe, et d'autres.
- **L'installation** dit quand le processeur est trop ancien pour certaines
  applis et certains jeux (sans arrêter l'installation), Essayer Raye ne
  touche jamais au swap du PC, et le nouveau système utilise le serveur
  Ubuntu du pays choisi.
- **Petites corrections :** les boutons de la barre des tâches, Démarrer et
  l'horloge répondent jusqu'au bord de l'écran et dans les coins,
  l'agrandissement n'a plus de défaut d'affichage, la fenêtre Fusionner les
  dossiers de l'Explorateur est corrigée, et les Chromebooks (Intel et AMD)
  ont leur rangée de touches du haut reconnue.

## Problèmes connus

- La mémoire au repos est d'environ 850 Mo (jusqu'à 1 Go juste après la
  première connexion), pas encore les 600 à 700 Mo visés pour la 1.0 finale.
- Le correctif de vitesse des jeux NVIDIA est testé sur nos machines de
  test, pas encore par nous sur une vraie carte NVIDIA. Si vos jeux sont
  encore lents, dites-le-nous.
- Hyprland est nouveau dans cette bêta et a surtout été testé dans des
  machines virtuelles. Après un changement de bureau avec connexion
  automatique, le trousseau de mots de passe (KWallet) peut rester
  verrouillé jusqu'à ce que vous le déverrouilliez.
- Le nouveau noyau Raye n'est pas encore dans cette bêta ; il arrivera dans
  une prochaine mise à jour.
- Le nom de la version n'apparaît pas encore dans le menu de démarrage,
  seulement dans Paramètres > À propos et sur l'écran de connexion.
- Sur un PC mis à jour depuis une bêta précédente, Synaptic peut apparaître
  dans « Ajoutés récemment » du menu Démarrer pendant environ 15 minutes,
  jusqu'à ce que Raye Update le retire.
- Dans la Bibliothèque du Store, Obtenir les mises à jour ne dit rien quand
  il n'y a rien à mettre à jour.
- Certaines anciennes cartes AMD (séries RX 400 et 500) peuvent encore
  démarrer en basse résolution avec peu d'images par seconde sur certains
  PC. Nous y travaillons encore.
- Tous les programmes Windows ne fonctionnent pas, et les applis faites
  uniquement pour le Microsoft Store ne peuvent pas fonctionner du tout. Les
  programmes qui existent aussi pour Raye (Discord, Steam) s'installent
  mieux depuis le Raye Store.

## Signaler un problème

Dites-le-nous sur Discord, https://discord.gg/TrxhUkabyB, ou écrivez à
bonjour@rayelinux.com. Dites quel ordinateur vous avez, ce que vous avez
fait, ce que vous attendiez et ce qui s'est passé. Une photo de l'écran
aide.

## Avant : Raye Linux 1.0 Bêta Brocken (19 novembre 2026)

La première bêta de Raye Linux 1.0 : un bureau disposé comme Windows 11,
dessiné aux couleurs de Raye, avec des mises à jour qui s'installent toutes
seules. C'est une bêta. Installez-la sur un ordinateur de rechange ou à côté
de votre système actuel, pas sur la seule machine dont vous dépendez. Une
0.5 Bêta déjà installée reçoit tout ceci par Raye Update ; le nouvel
installateur ne compte que pour les nouvelles installations.

### Nouveautés de la 1.0 Bêta Brocken

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
- **Des avis dans le Raye Store** : la page de chaque appli montre ses
  étoiles et ce que les gens en disent, et une fois l'appli installée, vous
  pouvez la noter et écrire votre propre avis. Les avis sont partagés avec
  d'autres magasins d'applis Linux.
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
  est simplement réessayé plus tard, la recherche de mises à jour ne reste
  plus bloquée des minutes quand un serveur ne répond plus, et Paramètres
  montre la vitesse, le temps restant et l'état de chaque mise à jour.
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
- **Essayer Raye Linux sans l'installer** : le menu de la clé a un nouveau
  choix qui ouvre le bureau directement depuis la clé, sans que
  l'installation s'ouvre. Rien ne change sur le PC.
- **Remplacer et garder vos fichiers** : quand Raye remplace Windows ou un
  autre système, l'installation peut emporter votre Bureau, vos Documents,
  Téléchargements, Musique, Images et Vidéos. Elle vérifie d'abord qu'il y a
  la place et demande avant d'effacer quoi que ce soit.
- **Machines virtuelles** : Raye apporte maintenant les outils invités de
  VirtualBox et de VMware, et le PC reste éveillé pendant l'installation.
- **Les applis web** installées depuis votre navigateur et épinglées à la
  barre des tâches gardent leur propre icône et leur nom.
- Ctrl+Win+Entrée active ou coupe le lecteur d'écran.

Raye Linux est basé sur Ubuntu. Il n'est ni affilié à Canonical Ltd. ni
approuvé par elle.
