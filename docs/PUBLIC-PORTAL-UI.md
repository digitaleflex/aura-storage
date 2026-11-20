# Portail public — direction visuelle

## Étoile polaire

Une bibliothèque accueillante : papier crème, encre bleu nuit et titrage serif.
Une seule action mise en avant — entrer avec Google.

## Périmètre

- Page de connexion (anonyme) et page du catalogue (session connectée), servies
  sans JavaScript par l'API (`api/public_ui.py`).
- Aucune police, image ou bibliothèque externe : tout est inline pour rester
  rapide et compatible avec la CSP du bord.

## Décisions

| Élément | Choix | Raison |
|---|---|---|
| Fond | Papier crème `#f6f1e7` avec deux halos très légers | Donne le ton « livre papier » sans image |
| Texte | Encre bleu nuit `#1b2b3a`, secondaires `#5f5d55` | Contraste 12,8 / 5,9 sur le fond |
| Accent | Laiton `#875f24` (pas `#a87a35`) | 5,05 sur papier : lisible en petits libellés |
| Titrage | Georgia / Iowan Old Style / Palatino, 400, 1.13 de line-height | Serif éditoriale, disponible partout |
| Action | Bouton blanc bordé, logo Google 4 couleurs, ombre portée fine | Reconnu comme connexion Google sans copier la console |
| Structure | Deux colonnes en grand écran, une colonne en mobile | Intro à gauche, accès à droite ; hiérarchie claire |
| Motion | Micro-transitions au survol/actif du bouton, désactivées si `prefers-reduced-motion` | Retour d'action sans distraction |

## Suppressions faites

- Ancien bloc HTML en une seule ligne et centrage pauvre dans `api/main.py`.
- Bordures grises génériques, rayons 10 px et texte bleu « lien » du bouton.
- Aucun texte de remplissage ajouté : les phrases restent courtes et utiles.

## Vérification

Contraste calculé pour chaque couple texte/fond. Tests hors-ligne du portail :
`4 passed`. **Visuel non vérifié par capture** : aucun Chrome/Chromium installé
sur l'hôte, Playwright échoue sur `libatk-1.0.so.0` manquante. La page en
production a été vérifiée par son HTML servi (`200`, marqueurs de la nouvelle
interface présents), pas par screenshot.
