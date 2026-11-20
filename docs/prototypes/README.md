# Prototypes UI

## `audiolivre-dashboard.html`

Reproduction UI autonome du dashboard « AudioLivre » décrit dans le master prompt.

- **Un seul fichier** : HTML + CSS + 15 lignes de JS pour le sélecteur de thème.
- **Aucun backend, aucune logique métier, aucun moteur audio** : les boutons sont
  des éléments de maquette.
- **Aucune modification** du portail AURA, de l'API ou de la configuration.
- **Données réelles** : les titres proviennent du catalogue publié et les
  couvertures sont les JPEG extraits localement, servis par `/covers/{oid}.jpg`
  sur le domaine public. Les initiales typographiques ne servent que de repli
  quand un livre n'a pas de couverture intégrée.
- Le nom **AudioLivre** est celui de la maquette ; l'identité de production
  reste **AURA** (décision validée précédemment).

Ouvrir le fichier directement dans un navigateur. Les couvertures distantes
nécessitent une connexion Internet.

### Périmètre volontaire

Le prompt demande une reproduction fidèle : proportions 278 / flexible / 372 px,
sidebar, topbar, carte « Reprendre l'écoute », grille « Pour vous », catégories,
panneau droit, lecteur fixe bas, thèmes clair/sombre, responsive desktop/tablette/
mobile. Aucune section supplémentaire n'a été ajoutée.

**Vérification :** structure HTML contrôlée (31 symboles d'icônes, 31 références,
aucune référence manquante) et URLs de couvertures testées en direct (302).
Le rendu visuel n'a pas pu être capturé : aucun Chrome/Chromium n'est installé
sur l'hôte.
