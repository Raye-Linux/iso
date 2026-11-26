# Raye Linux 1.0

La première version stable de Raye Linux, sortie le 26 novembre 2026. Elle
apporte le noyau Raye, Raye Proton pour les jeux, une couche Windows plus
récente, la prise en charge des PC plus anciens, un compte Raye qui vous
suit, les canaux de mise à jour Raye Insider, quatre nouvelles langues et un
nouveau look.

English: https://dl.rayelinux.com/iso/1.0/release-notes-1.0.md

## Mettre à jour ou installer

- **Déjà sur Raye (0.5 Bêta ou une 1.0 Bêta) ?** Pas besoin du nouveau
  téléchargement : Raye Update apporte la 1.0 tout seul. Pour l'avoir tout
  de suite, ouvrez Paramètres > Raye Update, cliquez sur Rechercher des
  mises à jour, puis redémarrez quand il le demande. La mise à jour
  s'installe pendant le redémarrage : laissez le PC allumé jusqu'au retour
  du bureau.
- **Nouvelle installation :** téléchargez l'image sur
  https://rayelinux.com/fr/download/, vérifiez-la, puis écrivez-la sur une
  clé USB de 8 Go ou plus avec Rufus (mode Image DD) ou balenaEtcher.
  Démarrez l'ordinateur sur la clé (souvent F12, F11, F8 ou Échap à
  l'allumage). La clé ouvre Essayer Raye, avec une icône Installer sur le
  bureau.

## Nouveautés de Raye Linux 1.0

- **Le noyau Raye.** Les correctifs de CachyOS et XanMod plus les réglages
  de Raye, signé pour le Secure Boot, et open source. Il remplace le noyau
  d'Ubuntu. Sur un PC avec le Secure Boot, Raye demande une fois au
  démarrage d'inscrire sa clé (un code à 6 chiffres sur un écran bleu) ;
  Paramètres peut aussi le faire plus tard. Il est prêt pour Easy Anti-Cheat
  v2 : nous envoyons la clé de notre noyau à Epic.
- **Raye Proton pour Steam.** GE-Proton construit par Raye depuis ses
  sources, avec le pont de Steam, pour que les jeux Steamworks puissent
  fonctionner. Steam l'utilise par défaut sur une nouvelle installation,
  jamais contre un choix que vous avez déjà fait. Steam voit aussi vos
  autres disques.
- **Une couche Windows plus récente** (Wine 11.22). Les programmes Windows
  s'installent en silence avec une vraie barre de progression, voient vos
  disques, imprimantes, réseau et ports, et la page Programmes Windows liste
  ceux installés depuis le Store. Quand un programme ne peut pas
  fonctionner, Raye le dit clairement.
- **PC plus anciens.** Raye démarre en mode BIOS (disques MBR compris), sur
  des processeurs plus anciens comme le Core 2 Duo, et avec 2 à 4 Go de
  mémoire, où un mode léger s'active tout seul. La mémoire au repos reste à
  peu près la même sur tous les PC, et le PC ralentit un peu au lieu de
  geler quand la mémoire manque.
- **Plus de matériel.** Plus de pilotes Wi-Fi (Broadcom et autres)
  s'installent tout seuls quand un appareil en a besoin. Nouvelle page
  Imprimantes et scanners, une appli Scan, et plus d'autonomie sur les
  portables.
- **Bureau.** La barre des tâches se place sur n'importe quel bord de
  l'écran, ses icônes à gauche ou au centre, à la taille voulue. Les
  fenêtres élastiques s'activent d'un interrupteur dans Paramètres.
  Hyprland est plus fluide, a un guide complet, et d'autres configurations
  Hyprland s'installent en une étape (avec retour à celle de Raye quand
  vous voulez). Le VPN WireGuard se met en place en un clic. Un disque
  chiffré a maintenant un vrai écran de déverrouillage Raye au démarrage.
- **Compte Raye.** Vos réglages vous suivent sur chaque PC, avec profils
  publics, badges et connexion en deux étapes sur le nouveau site des
  comptes.
- **Raye Insider.** Paramètres > Raye Update propose les canaux Bêta
  publique, Bêta et Dev. Vous pouvez les quitter à tout moment, sans
  retour en arrière des versions.
- **Raye Community, bêta.** Le chat de Raye, sur le site et dans Raye
  Linux, avec votre compte Raye, des rôles, la modération et des amis. C'est
  une première bêta : salons, images, messages privés et tickets arrivent
  en 1.1.
- **Langues.** L'espagnol, l'allemand, le portugais du Brésil et l'italien
  rejoignent l'anglais et le français.
- **Pour les développeurs.** Paramètres > Système > Avancé propose les
  options pour les développeurs et un portail local de l'appareil.
- **Nouveau look.** Le nouveau logo de Raye partout et une nouvelle
  animation de démarrage.
- **Installation.** La clé démarre sur Essayer Raye avec une icône
  Installer, le menu de démarrage est en anglais, et l'installation s'ouvre
  en plein écran.

## Problèmes connus

- Les anciennes cartes AMD (séries RX 400 et 500) qui n'affichent pas le
  bureau passent toutes seules à un mode d'affichage plus simple ; nous
  n'avons pas encore pu l'essayer sur ces cartes. Le scintillement de
  certaines cartes NVIDIA à 144 Hz n'est pas encore corrigé : si votre PC
  l'a, envoyez-nous ses journaux (Paramètres > Système > Avancé).
- Un jeu Steamworks avec Raye Proton n'a pas encore été essayé avec un vrai
  compte Steam. Si l'un d'eux échoue, choisissez GE-Proton ou Proton pour ce
  jeu dans ses propriétés Steam, et dites-le-nous.
- Avec la barre des tâches sur un côté et ses icônes au centre, les icônes
  restent en haut. Les icônes du bureau peuvent se trouver sous une barre à
  gauche. Un deuxième écran n'a pas encore la barre sur le côté.
- Raye Community est une bêta : il manque des fonctions.
- Tous les programmes Windows ne fonctionnent pas, et les applis faites
  uniquement pour le Microsoft Store ne peuvent pas fonctionner.

## Signaler un problème

Dites-le-nous sur Discord, https://discord.gg/TrxhUkabyB, ou écrivez à
bonjour@rayelinux.com. Indiquez votre ordinateur, ce que vous avez fait, ce
que vous attendiez et ce qui s'est passé. Une photo de l'écran aide.

Raye Linux est basé sur Ubuntu. Il n'est ni affilié à Canonical Ltd. ni
approuvé par elle.
