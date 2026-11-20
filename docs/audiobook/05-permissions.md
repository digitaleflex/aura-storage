# 05 — Permissions, rôles et séparation des devoirs

**Objectif :** garantir le moindre privilège, l'isolation des données privées et
la traçabilité des actions sensibles. Une permission accordée « pour simplifier »
est une dette de sécurité.

---

## 1. Principes

1. **Default deny.** Tout ce qui n'est pas explicitement accordé est refusé.
2. **Périmètre ressource.** Une permission globale ne donne jamais accès aux
   octets personnels d'un auditeur.
3. **Séparation des devoirs.** Celui qui crée une offre ne doit pas forcément
   pouvoir la publier, l'encaisser et la rembourser seul.
4. **Moindre privilège.** Les rôles sont cumulables uniquement si le besoin est
   documenté.
5. **Step-up.** Les actions à fort impact exigent une réauthentification
   (MFA/mot de passe) et, au-delà d'un seuil, une seconde validation.
6. **Audit avant effet.** Une action sensible non traçable est refusée.
7. **Pas de backdoor.** Aucun rôle ne contourne les invariants métier.
8. **404 plutôt que 403.** Une ressource hors périmètre ne révèle pas son
   existence.

---

## 2. Acteurs

| Acteur | Description | Authentification |
|---|---|---|
| **Visiteur** | Non connecté | Aucune |
| **Auditeur** | Utilisateur consommateur | Google OIDC / magic link, session + CSRF |
| **Support** | Assistance client | SSO interne + MFA |
| **Éditeur catalogue** | Crée et prépare les œuvres/éditions | SSO interne + MFA |
| **Valideur éditorial** | Approuve et publie | SSO interne + MFA + step-up |
| **Responsable des droits** | Gère contrats et fenêtres | SSO interne + MFA |
| **Finance** | Paiements, factures, remboursements | SSO interne + MFA |
| **Modérateur** | Signalements, sanctions | SSO interne + MFA |
| **Administrateur plateforme** | Rôles, configuration, incidents | SSO interne + MFA + step-up |
| **Auditeur de sécurité** | Lecture seule des audits | SSO interne + MFA |
| **Service audiobook → AURA** | Stockage/diffusion | Identité de service Bearer, scope minimal |
| **Webhook paiement** | Notifications prestataire | Signature + idempotence |
| **Worker interne** | Jobs, outbox, réconciliation | Rôle DB limité, pas d'accès externe |

---

## 3. Matrice des permissions

Légende : ✅ autorisé ; ◐ limité au périmètre / lecture seule ; ⚑ step-up ou
seconde validation ; — interdit.

| Action | Visiteur | Auditeur | Support | Éditeur | Valideur | Droits | Finance | Modérateur | Admin | Auditeur séc. |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Voir profil public | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Voir son propre profil privé | — | ✅ | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | ✅ | — |
| Modifier ses informations | — | ✅ | — | — | — | — | — | — | ⚑ | — |
| Changer son e-mail | — | ✅⚑ | — | — | — | — | — | — | ⚑ | — |
| Supprimer son compte | — | ✅⚑ | — | — | — | — | — | — | ⚑ | — |
| Gérer ses appareils/sessions | — | ✅ | ◐ révocation | — | — | — | — | — | ⚑ | — |
| Voir sa bibliothèque | — | ✅ | — | — | — | — | — | — | — | — |
| Gérer sa bibliothèque/collections | — | ✅ | — | — | — | — | — | — | — | — |
| Écouter un contenu autorisé | — | ✅ | — | — | — | — | — | — | — | — |
| Télécharger un contenu autorisé | — | ✅ | — | — | — | — | — | — | — | — |
| Acheter / s'abonner | — | ✅ | — | — | — | — | — | — | — | — |
| Voir ses factures | — | ✅ | ◐ | — | — | — | ◐ | — | ✅ | — |
| Créer/modifier œuvre/édition | — | — | — | ✅ | — | — | — | — | ⚑ | — |
| Uploader un actif | — | — | — | ✅ | — | — | — | — | ✅ | — |
| Valider un actif technique | — | — | — | ◐ | ✅ | — | — | — | ✅ | — |
| Approuver une édition | — | — | — | — | ✅ | — | — | — | ⚑ | — |
| Publier une édition | — | — | — | — | ✅⚑ | — | — | — | ⚑ | — |
| Suspendre/retirer une édition | — | — | — | — | ✅⚑ | ✅ | — | ✅ | ⚑ | — |
| Gérer les contrats/fenêtres de droits | — | — | — | — | ◐ lecture | ✅ | — | — | ⚑ | — |
| Voir tous les auditeurs | — | — | ◐ | — | — | — | — | ◐ | ✅ | — |
| Suspendre/bloquer un auditeur | — | — | ✅⚑ | — | — | — | — | ✅⚑ | ⚑ | — |
| Voir les paiements/écritures | — | — | — | — | — | — | ✅ | — | ◐ | ◐ |
| Rembourser ≤ seuil | — | — | — | — | — | — | ✅⚑ | — | ⚑ | — |
| Rembourser > seuil | — | — | — | — | — | — | ⚑ deux validateurs | — | ⚑ | — |
| Voir les imports personnels (métadonnées) | — | ✅ (siens) | ◐ | — | — | — | — | ◐ | ◐ | — |
| Lire les octets d'un import personnel | — | ✅ (siens) | — | — | — | — | — | — | — (sauf procédure légale) | — |
| Modérer un contenu/signalement | — | — | — | — | — | — | — | ✅ | ⚑ | — |
| Voir l'audit | — | — | — | — | — | — | — | — | ◐ | ✅ |
| Gérer les rôles | — | — | — | — | — | — | — | — | ✅⚑ | — |
| Configurer la plateforme | — | — | — | — | — | — | — | — | ✅⚑ | — |
| Exporter des analytiques agrégées | — | — | — | — | — | — | ◐ | — | ✅ | ◐ |
| Accéder à AURA (stockage) | — | — | — | — | — | — | — | — | — | — |

**Note :** la dernière ligne est volontairement vide pour les humains. Seul le
service audiobook, avec son identité dédiée, parle à AURA. Aucun opérateur ne
doit utiliser son compte AURA pour lire un contenu audiobook.

---

## 4. Règles de périmètre

### 4.1 Auditeur

- Toute requête est filtrée par `listener_id = principal.id`.
- Une ressource d'un autre auditeur répond **404**, jamais 403.
- L'auditeur ne peut pas modifier `entitlement`, `payment`, `status`,
  `published_at`, `rights_window`, `role`.
- Les imports personnels ne sont accessibles qu'au propriétaire et à ses
  appareils actifs.

### 4.2 Support

- Peut voir les métadonnées de compte et de facturation nécessaires au support.
- Peut révoquer un appareil et suspendre un compte avec motif.
- Ne peut pas lire les imports personnels, ni modifier un paiement, ni publier.
- Toute impersonation est consentie, limitée dans le temps, en lecture seule par
  défaut et auditée.

### 4.3 Éditeur / valideur

- L'éditeur prépare ; le valideur approuve et publie.
- Le valideur ne peut pas publier si les droits ne sont pas validés par le
  responsable des droits.
- Un contenu sensible (politique, légal, mineurs) exige une seconde validation.
- Aucun accès aux données de paiement ou aux imports personnels.

### 4.4 Droits

- Crée, suspend et termine les fenêtres de droits.
- Ne peut pas publier une édition.
- Peut demander un retrait immédiat ; l'exécution est tracée.
- Ne peut pas accéder aux données personnelles des auditeurs.

### 4.5 Finance

- Consulte commandes, paiements, factures, grand livre.
- Émet des remboursements dans la limite d'un seuil ; au-delà, seconde
  validation.
- Ne peut pas modifier une écriture de grand livre ; un remboursement est une
  nouvelle écriture.
- Ne peut pas publier ni modifier le catalogue.

### 4.6 Modération

- Traite les signalements, suspend un contenu ou un compte avec motif.
- Ne peut pas rembourser, publier, ni lire les imports personnels.
- Décision notifiée et susceptible de recours.

### 4.7 Administrateur

- Gère les rôles, la configuration, les incidents.
- Ne contourne pas les invariants ; les actions sensibles exigent step-up et
  parfois double validation.
- N'a pas accès par défaut aux octets personnels.
- Peut utiliser un break-glass limité, motivé, notifié et audité.

### 4.8 Auditeur de sécurité

- Lecture seule des audits, configurations et exports.
- Aucune capacité de modification.

---

## 5. Séparation des devoirs

| Action | Crée | Approuve | Exécute | Contrôle |
|---|---|---|---|---|
| Publication d'une édition | Éditeur | Valideur | Système | Audit |
| Retrait pour droits | Droits | Valideur/Admin | Système | Audit |
| Remboursement ≤ seuil | Finance | Finance (step-up) | Finance | Audit |
| Remboursement > seuil | Finance | Admin | Finance | Audit |
| Suppression de compte | Support/Auditeur | Admin | Worker | Audit |
| Suspension d'auditeur | Support/Modération | Modération/Admin | Système | Audit |
| Modification de rôle | Admin | Admin (step-up) | Système | Audit |
| Break-glass | Admin | Admin (step-up) | Admin | Audit + notification |

**Règle :** une même personne ne peut pas être `requested_by` et `approved_by`
pour une action à double validation.

---

## 6. Identités de service

### 6.1 Audiobook → AURA

| Élément | Règle |
|---|---|
| Type | Identité de service AURA, Bearer `aura_<id>_<secret>` |
| Scopes | `objects:read`, `objects:write` uniquement |
| Interdits | `objects:purge`, `admin:*` |
| Portée | Un espace AURA par environnement |
| Rotation | Planifiée, secret stocké dans un gestionnaire de secrets |
| Audit | Chaque appel porte `request_id` et l'ID de l'édition/piste |
| Panne | Erreur métier traduite, retry borné, aucun fallback non autorisé |

### 6.2 Webhook paiement

- Vérification de signature obligatoire.
- `(provider, event_id)` unique ; doublon = no-op.
- Aucun accès utilisateur ; aucun cookie.
- Réponse 2xx rapide ; traitement lourd en worker.
- Les événements en échec sont rejouables depuis la file morte.

### 6.3 Workers

- Rôle DB dédié, accès limité aux tables de travail.
- Pas de credentials externes en clair ; secrets injectés.
- Jobs idempotents, avec lease et retry borné.
- Toute action destructive est auditée.

---

## 7. Audit

Chaque événement d'audit contient :

- `actor_type` (`listener`, `support`, `admin`, `service`, `system`) ;
- `actor_id` ;
- `action` normalisée ;
- `target_type`, `target_id` ;
- `outcome` (`success`, `denied`, `failed`) ;
- `reason` (motif métier, pas une donnée sensible) ;
- `request_id` ;
- `before_hash` / `after_hash` (pas de contenu brut) ;
- `created_at` UTC.

**Interdits dans l'audit :** mot de passe, token, cookie, URL présignée, clé S3,
contenu d'un import personnel, numéro de carte, payload complet d'un
prestataire.

**Rétention :** configurable, alignée sur les obligations légales ; l'audit de
sécurité et les écritures financières ont des durées distinctes.

---

## 8. Matrice des capacités techniques (AURA)

| Capacité AURA | Audiobook service | Opérateur humain | Justification |
|---|:--:|:--:|---|
| `objects:read` | ✅ | — | Lire les actifs autorisés |
| `objects:write` | ✅ | — | Uploader les actifs |
| `objects:delete` | ◐ | — | Suppression d'imports personnels, jamais de catalogue sans validation |
| `objects:purge` | — | ✅ (admin AURA) | Destruction définitive hors du domaine audiobook |
| `admin:read` | — | ✅ | Administration AURA |
| `admin:write` | — | ✅ | Administration AURA |

Cette séparation garantit qu'une compromission du service audiobook ne peut pas
purger le stockage ni administrer AURA.

---

## 9. Tests de permissions

Chaque ligne de la matrice doit être couverte par au moins un test :

- accès autorisé ;
- accès refusé pour un rôle inférieur ;
- accès refusé pour un autre auditeur ;
- accès refusé sans step-up ;
- accès refusé sans seconde validation ;
- tentative d'élévation de privilège via un champ de payload ;
- vérification de l'audit (acteur, cible, résultat).

La matrice de tests est dans [`07-acceptance-tests.md`](07-acceptance-tests.md),
section « Sécurité et permissions ».
