# 07 — Matrice des tests d'acceptation

**Objectif :** prouver que chaque règle importante résiste au scénario nominal,
aux cas limites, aux autorisations, à la concurrence et aux pannes. Un scénario
nominal qui passe ne suffit pas.

---

## 1. Stratégie de test

| Niveau | Objet | Outils indicatifs |
|---|---|---|
| **Unitaire** | Agrégats, machines à états, politiques | pytest, tests paramétrés |
| **Propriété** | Invariants de progression, d'argent, d'entitlement | Hypothesis |
| **Intégration** | PostgreSQL, transactions, contraintes, outbox | pytest + PostgreSQL réel |
| **Contrat** | Adaptateur AURA, prestataire de paiement | Mock serveur / sandbox |
| **E2E** | Parcours achat → bibliothèque → écoute → remboursement | Playwright/API |
| **Sécurité** | IDOR, CSRF, élévation, webhook forgé | tests dédiés + revue |
| **Charge/soak** | Concurrence, latence, reprise | k6/Locust, 24 h |
| **Résilience** | AURA 503, PSP timeout, DB coupée, worker tué | injection de fautes |
| **Migration** | Données du portail existant | jeu de données réel anonymisé |

**Règle :** chaque test d'acceptation référence un invariant (`INV-xx`) et une
règle (`BR-xx-xx`). Un test sans invariant est un test de confort, pas une
preuve.

---

## 2. Jeux de données de référence

| Fixture | Contenu |
|---|---|
| `listener_active` | Compte actif, e-mail vérifié, 1 appareil |
| `listener_suspended` | Compte suspendu, bibliothèque et achat existants |
| `listener_other` | Autre auditeur, mêmes droits potentiels |
| `work_published` | Œuvre avec auteur/narrateur, édition publiée |
| `edition_ready` | Édition avec 3 pistes `ready`, 3 chapitres, droits actifs |
| `edition_no_rights` | Édition prête mais fenêtre de droits absente/expirée |
| `asset_corrupt` | Actif avec checksum invalide |
| `subscription_active` | Abonnement actif, plan catalogue |
| `subscription_expired` | Abonnement expiré, même plan |
| `purchase_paid` | Commande payée, entitlement direct |
| `payment_pending` | Commande `pending_payment` |
| `device_active` / `device_revoked` | Appareils |
| `grant_active` / `grant_expired` | Téléchargements |
| `personal_import` | Import privé prêt |

Les fixtures sont construites par des factories, jamais par des INSERT dispersés.

---

## 3. Matrice d'acceptation

### 3.1 Identité et sécurité

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-SEC-01 | Auditeur A et auditeur B | A demande la bibliothèque/progression de B | 404, aucune donnée, audit de tentative | SEC | INV-01 |
| AT-SEC-02 | Requête avec `listener_id`, `role`, `price` ou `status` falsifiés | Appel API | 422/403, aucun champ client appliqué | SEC | INV-21 |
| AT-SEC-03 | Session sans CSRF | POST mutation | 403, aucun effet | SEC | — |
| AT-SEC-04 | Webhook avec signature invalide | POST webhook | 401/400, aucun événement, alerte | SEC | BR-BIL-11 |
| AT-SEC-05 | Rôle support | Tentative de remboursement | 403, audit | SEC | BR-ADM-01 |
| AT-SEC-06 | Admin | Lecture des octets d'un import personnel | 403 sans procédure légale | SEC | BR-ADM-04 |
| AT-SEC-07 | Appareil révoqué | Requête de lecture | 401/403, lease non renouvelé | SEC | BR-USR-09 |
| AT-SEC-08 | Rate limit login dépassé | Nouvelle tentative | 429, pas de fuite d'existence du compte | SEC | — |

### 3.2 Comptes

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-USR-01 | Abonnement actif | Demande de suppression | Suppression différée, abonnement résolu, factures conservées | I | INV-18 |
| AT-USR-02 | Compte actif | Changement d'e-mail vers une adresse existante | 409, aucune modification | I | BR-USR-07 |
| AT-USR-03 | Compte actif | Changement d'e-mail valide | Vérification, notification ancienne adresse, audit | I | BR-USR-07 |
| AT-USR-04 | Compte suspendu pendant l'écoute | Heartbeat suivant | Écoute refusée, données conservées, message explicite | I | BR-USR-03 |
| AT-USR-05 | Compte en suppression | Reconnexion | Lecture seule ou refus selon état, pas de nouvelle donnée | I | BR-USR-05 |
| AT-USR-06 | 4e appareil | Enregistrement | Refus avec limite explicite, pas de suppression silencieuse | I | BR-USR-08 |

### 3.3 Catalogue et publication

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-CAT-01 | Édition sans droits | Publication | 409 avec blockers, aucun `published_at` | I | INV-02, INV-11 |
| AT-CAT-02 | Édition avec actif `rejected` | Publication | 409, aucun accès public | I | INV-20 |
| AT-CAT-03 | Édition prête | Publication valide | Visible en découverte, auditable | I | BR-CAT-06 |
| AT-CAT-04 | Édition publiée | Changement de titre | ID/slug conservés, version auditée | I | BR-CAT-11 |
| AT-CAT-05 | Chapitres qui se chevauchent | Validation | 422, publication bloquée | U | BR-CAT-05 |
| AT-CAT-06 | Édition retirée | Recherche et bibliothèque | Absente de la recherche, visible « indisponible » en bibliothèque | I | BR-CAT-09 |
| AT-CAT-07 | Collection avec 2 éditions | Suppression de la collection | Les 2 éditions existent toujours | I | BR-CAT-12 |

### 3.4 Bibliothèque

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-LIB-01 | Import personnel prêt | Tentative de publication | 403, aucun slug, aucune indexation | SEC | INV-07 |
| AT-LIB-02 | Collection personnelle avec 3 livres | Suppression | 3 entrées de bibliothèque conservées | I | INV-08 |
| AT-LIB-03 | Auditeur A | Accès à l'import de B | 404 | SEC | INV-17 |
| AT-LIB-04 | Livre déjà dans la bibliothèque | Ajout répété | 200 idempotent, une seule entrée | I | BR-LIB-02 |
| AT-LIB-05 | Livre acheté | Retrait de la bibliothèque | Entitlement et progression conservés | I | BR-LIB-04 |
| AT-LIB-06 | Même fichier importé deux fois | Import | Détection checksum, choix utilisateur | I | BR-LIB-11 |

### 3.5 Actifs audio

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-AST-01 | Fichier corrompu | Upload/validation | `rejected`, aucune lecture, motif | I | INV-03 |
| AT-AST-02 | Upload interrompu | Commit | Actif non `ready`, reprise ou expiration | I | BR-AST-06 |
| AT-AST-03 | Fichier infecté | Scan AV | `blocked`, notification, aucun accès | I | BR-AST-05 |
| AT-AST-04 | Nouvel actif `ready` | Remplacement de piste | Bascule atomique, ancien conservé, rollback possible | I | BR-AST-08 |
| AT-AST-05 | Actif sans référence | GC après grâce | Non purgé si référence ou legal hold | I | BR-AST-10 |
| AT-AST-06 | Type MIME falsifié | Upload | Rejet sur magic bytes, pas sur extension | I | BR-AST-04 |

### 3.6 Écoute et progression

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-PLY-01 | Session A à 25:00, A inactive | B envoie 18:00 | Événement stocké, progression 25:00, 409 | I | INV-06 |
| AT-PLY-02 | Deux heartbeats concurrents | Même version | Un gagne, l'autre 409, version croissante | P | INV-13 |
| AT-PLY-03 | Même `event_id` | Rejeu | No-op, une seule ligne | I | INV-14 |
| AT-PLY-04 | Position 99 % sans `ended` | Heartbeat | Pas de complétion ; seuil explicite seulement | U | INV-15 |
| AT-PLY-05 | Livre terminé | Redémarrage | Nouveau run, `completed_at` conservé | I | BR-PLY-11 |
| AT-PLY-06 | Session active | Seek à 05:00 | Position 05:00 acceptée, pas de max | I | BR-PLY-06 |
| AT-PLY-07 | Lot offline en désordre | Sync | Ordre `client_seq`, conflit signalé | I | BR-PLY-12 |
| AT-PLY-08 | Position invalide (`-1`, `NaN`, > durée) | API | 422, progression inchangée | U | BR-PLY-04 |
| AT-PLY-09 | Abonnement expiré | Segment suivant | 403, URL expirée, message | I | BR-ACC-05 |

### 3.7 Droits et autorisations

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-ACC-01 | Livre dans la bibliothèque, aucun entitlement | Lecture | 403, raison `NO_ACTIVE_ENTITLEMENT`, audit | I | INV-04 |
| AT-ACC-02 | Droits expirés | Lecture | 403, aucun flux | I | INV-11 |
| AT-ACC-03 | Décision `allow` | Requête suivante | Audit avec sources et expiration | I | INV-16 |
| AT-ACC-04 | Achat `pending_payment` | Lecture | 403 | I | BR-ACC-03 |
| AT-ACC-05 | Abonnement actif, livre hors plan | Lecture | 403, pas de fallback | I | BR-ACC-04 |
| AT-ACC-06 | Remboursement total | Lecture après | 403 ; si autre source, 200 avec source restante | I | BR-ACC-06 |
| AT-ACC-07 | Territoire interdit | Lecture | 403, raison `TERRITORY_RESTRICTED` | I | BR-ACC-08 |
| AT-ACC-08 | Cache d'accès chaud | Révocation entitlement | Invalidation ≤ 60 s, refus | I | BR-ACC-11 |

### 3.8 Paiements et abonnements

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-BIL-01 | Double clic checkout | Même clé | Une commande, un paiement | I | INV-05 |
| AT-BIL-02 | Webhook `succeeded` rejoué | Deux réceptions | Un entitlement, une écriture | I | INV-05 |
| AT-BIL-03 | Webhook `failed` après `succeeded` | Réception | `ignored_stale`, pas de régression | I | INV-05 |
| AT-BIL-04 | Paiement pending 24 h | Job | Commande expirée, aucun accès | I | BR-BIL-04 |
| AT-BIL-05 | Annulation avant renouvellement | Fin de période | Pas de prélèvement, accès coupé à la fin | I | BR-BIL-07 |
| AT-BIL-06 | Remboursement partiel | Lecture | Accès selon politique, grand livre équilibré | I | BR-BIL-06 |
| AT-BIL-07 | Échec de renouvellement | Grâce | `past_due`, notifications, puis `expired` | I | BR-BIL-08 |
| AT-BIL-08 | Chargeback | Réception | Accès révoqué, écriture, alerte | I | BR-BIL-12 |
| AT-BIL-09 | Prestataire timeout | Checkout | `processing`, pas d'accès, réconciliation | I | BR-BIL-11 |
| AT-BIL-10 | Double remboursement | Deux requêtes | Plafond respecté, second refusé | I | BR-BIL-06 |

### 3.9 Hors ligne et téléchargements

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-OFF-01 | Aucun entitlement | Demande de grant | 403 | I | INV-12 |
| AT-OFF-02 | Grant actif, droits expirant demain | Lease 30 jours | Lease tronqué à demain | U | INV-19 |
| AT-OFF-03 | Téléchargement incomplet | Reprise | Non disponible, checksum final requis | I | BR-OFF-04 |
| AT-OFF-04 | Appareil révoqué | Renouvellement | 403, lease existant jusqu'à expiration | I | BR-OFF-08 |
| AT-OFF-05 | Progression offline | Sync après 2 jours | Événements historisés, conflit explicite | I | BR-OFF-07 |
| AT-OFF-06 | Retrait de droits | Renouvellement | 403, pas de nouveau contenu | I | BR-OFF-09 |

### 3.10 Découverte, notifications, administration, analytique

| ID | Given | When | Then | Niveau | Invariant |
|---|---|---|---|---|---|
| AT-DSC-01 | Édition indisponible | Recherche | Affichée « indisponible », pas « écouter » | I | BR-DSC-02 |
| AT-DSC-02 | Import personnel | Recherche publique | Jamais présent | SEC | BR-DSC-04 |
| AT-DSC-03 | Popularité calculée | Écoutes synthétiques | Signal détecté/plafonné, pas de classement artificiel | I | BR-DSC-03 |
| AT-NOT-01 | Paiement pending | Notification | Aucune confirmation avant `succeeded` | I | BR-NOT-01 |
| AT-NOT-02 | Événement rejoué | Notification | Une seule notification | I | BR-NOT-03 |
| AT-NOT-03 | Préférence désactivée | Notification produit | Supprimée ; transactionnelle envoyée | I | BR-NOT-02 |
| AT-ADM-01 | Admin | Action sensible | Audit complet, acteur/cible/motif | I | INV-10 |
| AT-ADM-02 | Remboursement > seuil | Un seul admin | Refus tant que second validateur absent | I | BR-ADM-03 |
| AT-ADM-03 | Support | Accès imports personnels | 403 | SEC | BR-ADM-04 |
| AT-ADM-04 | Action admin rejouée | Même clé | No-op, un seul audit | I | FAIL-20 |
| AT-ADM-05 | Modération | Décision | Motif, notification, recours possible | I | BR-ADM-06 |
| AT-ANA-01 | Événements rejoués | Rebuild projection | Totaux identiques | I | INV-22 |
| AT-ANA-02 | Dashboard commercial | Comparaison grand livre | Écart = 0 ou alerte | I | BR-ANA-04 |
| AT-ANA-03 | Dashboard auditeur | Accès autre auditeur | 404 | SEC | BR-ANA-03 |

### 3.11 Parcours de bout en bout

| ID | Parcours | Critère |
|---|---|---|
| AT-E2E-01 | Achat → entitlement → bibliothèque → écoute → progression → reprise | Toutes les étapes, aucun accès avant paiement |
| AT-E2E-02 | Abonnement → catalogue → écoute → expiration → refus | Accès coupé proprement, message clair |
| AT-E2E-03 | Achat → remboursement → révocation → historique conservé | Grand livre équilibré, accès futur refusé |
| AT-E2E-04 | Import personnel → écoute → suppression → bibliothèque | Fichier supprimé, entrée conservée en état « supprimé » |
| AT-E2E-05 | Publication → retrait → bibliothèque → réactivation | Références préservées, états cohérents |

---

## 4. Tests de propriété (invariants)

| Propriété | Énoncé | Générateur |
|---|---|---|
| `P-PROGRESS-01` | Pour toute suite d'événements valides, `version` est strictement croissante et `position` est toujours la dernière position acceptée. | Séquences aléatoires de start/heartbeat/seek/pause/ended |
| `P-PROGRESS-02` | Aucune position invalide ne modifie `listening_progress`. | Positions négatives, NaN, > durée |
| `P-PROGRESS-03` | Un doublon d'`event_id` ne change pas l'état. | Rejeu aléatoire |
| `P-MONEY-01` | Somme des débits = somme des crédits pour chaque devise. | Commandes, paiements, remboursements |
| `P-MONEY-02` | Somme des remboursements ≤ montant payé. | Remboursements aléatoires |
| `P-ACCESS-01` | `allow` implique compte actif + entitlement actif + droits actifs + actif prêt. | Combinaisons d'états |
| `P-ACCESS-02` | Un entitlement `pending`/`revoked`/`expired` ne produit jamais `allow`. | États |
| `P-LIB-01` | Une entrée de bibliothèque ne crée jamais d'entitlement. | Ajout/suppression |
| `P-OFF-01` | `lease.expires_at ≤ min(entitlement.valid_until, rights.ends_at)`. | Dates aléatoires |

---

## 5. Tests non fonctionnels

| Catégorie | Scénario | Critère |
|---|---|---|
| Charge | 1 000 écoutes concurrentes, 100 req/s de progression | Latence p95 < 300 ms, aucune perte d'événement |
| Soak | 24 h de heartbeats et recherches | Pas de fuite mémoire, pas de dérive de projection |
| Concurrence | 50 achats simultanés du même livre | Un seul débit par auditeur |
| Résilience | AURA 503 pendant 5 min | Aucune URL émise, reprise automatique |
| Résilience | PSP timeout | Commandes `processing`, réconciliation |
| Résilience | Worker tué en plein job | Reprise sans double effet |
| Sauvegarde | Restauration complète | Invariants vérifiés, projections reconstruites |
| Sécurité | Scan IDOR/CSRF/rate limit/webhook | Aucun accès croisé |
| Migration | Jeu de données portail | 100 % des auditeurs/progressions mappés ou signalés |

**Note :** les chiffres de charge sont des hypothèses de conception. Ils doivent
être remplacés par les objectifs business validés (nombre d'auditeurs, pics,
concurrence) avant le test de performance.

---

## 6. Definition of Done par domaine

Un domaine n'est pas « terminé » parce que le parcours nominal fonctionne. Il
l'est lorsque :

1. ses règles sont documentées et tracées à un test ;
2. ses invariants sont couverts par un test unitaire/propriété ;
3. ses permissions sont couvertes par un test d'accès refusé ;
4. ses transitions interdites sont testées ;
5. ses scénarios de panne critiques sont testés ;
6. ses événements sont idempotents et auditables ;
7. ses métriques et alertes existent ;
8. sa procédure de reprise est documentée ;
9. la revue de sécurité est passée ;
10. la documentation utilisateur/admin est à jour.

---

## 7. Traçabilité

Chaque test de la matrice est relié à :

- une règle (`BR-...`) ;
- un invariant (`INV-...`) ;
- un scénario de défaillance (`FAIL-...`) le cas échéant ;
- un lot de livraison (`Lot 1..5`).

La matrice de traçabilité globale est tenue dans
[`09-design-review-and-decisions.md`](09-design-review-and-decisions.md).
