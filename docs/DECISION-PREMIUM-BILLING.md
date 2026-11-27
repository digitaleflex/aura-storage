# Décision — Modèle premium et facturation réels (audiobook Lots 3-5, #323)

**Date :** 2026-11-27 · **Statut :** décision produit **en attente de revue juridique/conformité** ; aucune activation en production avant cette revue.

## Contexte

Le portail public reconnaît aujourd'hui un plan `free`/`premium` dans le catalogue, mais le « premium » est accordé par une allow-list manuelle `AURA_PREMIUM_EMAILS` (ou par promotion manuelle en base). La capacité payante est le téléchargement complet (`/d/{slug}`) ; l'écoute en streaming reste ouverte aux visiteurs connectés. Les Lots 3-5 du service audiobook (Stripe/Tax, abonnements, DRM/offline, analytics) n'ont pas été intégrés.

## Décision produit

| Point | Décision |
|---|---|
| Modèle | **Abonnement** récurrent comme offre principale. Pas d'achat à l'unité au lancement. |
| Durée | **Mensuel 9 € TTC** et **annuel 90 € TTC** (deux mois offerts). Renouvellement automatique, résiliation à tout moment depuis le portail du prestataire. |
| Période d'essai | **7 jours**, conversion automatique ensuite ; rappel e-mail à J-3 géré par le prestataire. |
| Périmètre premium | Téléchargement hors-ligne des livres publiés (`/d/{slug}`) et écoute illimitée hors extrait. Le catalogue, la recherche, les favoris, listes et marque-pages restent gratuits. |
| Achat à l'unité | **Écarté pour l'instant** : le catalogue est un abonnement de bibliothèque, pas une boutique de fichiers. Réévaluable si un titre est vendu à l'acte. |
| Prix et devise | Fixés par l'opérateur dans le prestataire ; AURA ne stocke ni prix, ni TVA, ni historique de facturation. |

## Facturation et fiscalité

- **Prestataire unique :** Stripe (Checkout + Billing + **Stripe Tax**). Le paiement se déroule entièrement sur le domaine du prestataire.
- **Aucune donnée de carte dans AURA :** pas de numéro, pas de CVC, pas d'empreinte de carte, pas de journal de paiement dans le catalogue ni dans les logs applicatifs. Seul un identifiant opaque d'abonnement peut être conservé côté service audiobook.
- **TVA :** calculée, collectée et déclarée par Stripe Tax selon la localisation du client ; AURA reçoit uniquement l'issue de l'abonnement (`active` / `past_due` / `canceled`) via webhook signé.
- **Webhooks :** vérification de signature, idempotence par identifiant d'événement, journal borné sans données personnelles de paiement. Aucune action de retournement de grant n'est faite depuis un payload non vérifié.
- **Remboursements/litiges :** entièrement gérés chez le prestataire ; AURA n'exécute aucun remboursement.

## Droits (rights / entitlements)

- Les droits restent **dans le service audiobook** : c'est l'autorité qui décide si un compte dispose d'un abonnement actif et pour quels titres.
- AURA ne reçoit **que des grants courts** : jeton opaque ou JWT signé, TTL **≤ 15 min**, lié à un identifiant de compte public et à une liste de capacités (ex. `download:published`). Le grant n'est pas une session et n'accorde jamais de capacité objet `/api/v1/*`.
- Vérification du grant à chaque téléchargement ; aucun état de paiement n'est mis en cache plus longtemps que le TTL du grant. Un webhook de résiliation invalide les grants à la prochaine vérification, sans avoir à modifier le catalogue.
- Le mode hors-ligne du lecteur consomme le même grant court au moment du téléchargement ; il ne persiste aucun secret de paiement sur l'appareil.
- Transition : `AURA_PREMIUM_EMAILS` reste un **mécanisme de bootstrap manuel** (tests, accès opérateur). Il ne devient pas un système de facturation et doit être désactivé à l'activation de l'abonnement.

## Analytics

- Seules des agrégats anonymes (nombre d'abonnements actifs, taux de conversion, revenu net hors données de carte) sont conservés. Le détail des événements d'écoute reste dans le portail, avec la rétention et l'anonymisation décrites dans `ETAT-DES-FONCTIONNALITES.md` (#320).
- Aucun identifiant publicitaire, aucun recoupement hors du service audiobook.

## Conditions d'activation (bloquantes)

1. **Revue juridique et conformité** : CGV/CGU, droit de rétractation, mention TVA, GDPR (base légale, durée de conservation, sous-traitant Stripe), accessibilité du parcours de résiliation.
2. **Validation des webhooks** en environnement de test Stripe (signature, rejeux, expiration, résiliation).
3. **Désactivation explicite** de `AURA_PREMIUM_EMAILS` et vérification qu'un compte gratuit ne peut pas télécharger.
4. **Test de charge** du flux de grants courts et vérification qu'aucun secret de paiement n'apparaît dans les logs (`api/audit.py`, logs nginx/Traefik).
5. **Décision d'activation** enregistrée dans `docs/ETAT-DES-FONCTIONNALITES.md` avec la date et le responsable.

## Ce qui reste différé

Le DRM/outillage hors-ligne renforcé (Lots 4-5) reste différé après l'abonnement initial : les fichiers téléchargés ne sont pas chiffrés côté client dans cette version, ce qui doit être explicité dans les CGV. La reprise de l'issue #323 nécessitera une nouvelle décision si le modèle à l'unité ou un DRM est retenu.
