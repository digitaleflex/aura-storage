# 09 — Revue de conception, audit et décisions ouvertes

**Version :** 0.2
**Statut :** **conception revue ; recommandations D-01 à D-12 acceptées par l'utilisateur (2026-11-20).** Fondation Lot 1 implémentée dans `audiobook/` (voir [`10-lot1-implementation.md`](10-lot1-implementation.md)).
**But :** exposer honnêtement l'écart entre l'existant et la cible, vérifier la
cohérence du dossier, tracer les décisions de conception et les conditions
restantes avant déploiement/ouverture.

---

## 1. Méthode d'audit

**Périmètre examiné :**

- `api/schema.sql`, `api/migrations.py` : modèle de données et évolutions ;
- `api/db.py`, `api/db_pg.py` : repository, progression, collections ;
- `api/main.py` : routes publiques, publication, `/m/{slug}`, progression ;
- `api/public_ui.py` : portail HTML et lecteur ;
- `api/authz.py`, `api/identity.py` : rôles, sessions, identités de service ;
- `tests/test_public_portal.py` et suites associées ;
- `docs/PUBLIC-PORTAL.md`, `docs/DATA-MODEL.md`,
  `docs/AUTHORIZATION-MATRIX.md`, `docs/ETAT-DES-FONCTIONNALITES.md`.

**Vérification exécutée :** `pytest tests/test_public_portal.py -q` →
**8 tests passés** (environnement local, Google simulé, pas de S3 réel).
Aucun test sur le VPS, aucune charge, aucun test de sécurité externe.

**Limites :** audit statique et tests hors ligne. Le comportement réel en
production (S3, PostgreSQL, Google, réseau, sauvegarde/restauration) n'est pas
couvert par cette revue.

---

## 2. Constats d'audit

### 2.1 Points critiques

| ID | Constat | Preuve | Sévérité | Conséquence |
|---|---|---|---|---|
| F-01 | La publication tient lieu de contrôle d'accès : `GET /m/{slug}` renvoie une URL S3 à quiconque possède le slug, sans session ni droit. | `api/main.py:3527-3556` | **Critique** | Tout contenu « publié » est public ; incompatible avec un livre payant ou sous droits. |
| F-02 | Aucun modèle de droits : pas de licence, territoire, fenêtre, entitlement. | `api/schema.sql`, absence de tables | **Critique** | Impossible de garantir `INV-04`, `INV-11`, `INV-12`. |
| F-03 | Aucun paiement, abonnement, facture ou grand livre. | absence | **Critique** | Le modèle commercial n'est pas supporté. |
| F-04 | La progression est une seule ligne écrasée (`listen_progress`), sans session, appareil, événement ni version. | `api/schema.sql:363-371`, `api/db.py:175-190` | **Élevé** | Une vieille position peut écraser une récente ; pas de reprise fiable multi-appareils. |
| F-05 | Le catalogue confond fichier, piste et livre : `objects` est l'unité, `collections` est un pack, l'auteur/titre sont déduits du nom de fichier. | `api/main.py:1583-1640` | **Élevé** | Pas d'œuvre, édition, enregistrement, contributeurs, langues ou séries. |
| F-06 | L'identité mélange opérateurs et auditeurs dans `users` ; le rôle `public` n'a aucune capacité, mais les données et sessions sont partagées. | `api/schema.sql:14-24`, `api/authz.py:241-273` | **Élevé** | Couplage dangereux, pas de statut de compte, appareils, préférences, suppression. |
| F-07 | Aucune bibliothèque personnelle, favori ou collection privée. | absence | **Élevé** | Le produit hybride n'est pas supporté. |
| F-08 | L'administration est celle des objets AURA, pas un workflow éditorial/droits/finance. | `api/main.py` routes admin | **Élevé** | Pas de séparation des devoirs ni de validation de publication. |
| F-09 | Les actifs audio ne sont pas validés à l'ingestion : ffprobe/ffmpeg sont des scripts hors ligne ; pas de quarantaine audio ni de gate AV systématique. | `docs/PUBLIC-PORTAL.md`, scripts | **Moyen/Élevé** | Un fichier corrompu peut être publié si l'opérateur ne vérifie pas. |
| F-10 | L'analytique compte des vues/downloads d'objets, pas des événements d'écoute. | `object_usage_monthly` | **Moyen** | Popularité, complétion et rétention ne sont pas fiables. |
| F-11 | Les notifications sont absentes. | absence | **Moyen** | Pas de confirmation de paiement, d'expiration, de sécurité. |
| F-12 | Les tests couvrent le prototype, pas les règles métier de la cible. | `tests/test_public_portal.py` | **Moyen** | Le vert actuel ne prouve pas la solidité du backend cible. |

### 2.2 Points forts à conserver

| ID | Force | Réutilisation |
|---|---|---|
| S-01 | Checksum SHA-256, taille vérifiée, SSE-S3, lifecycle | Socle des actifs |
| S-02 | Upload en trois temps, idempotence, reprise | Adaptateur `StoragePort` |
| S-03 | Presigned URLs courtes, bytes hors API | Diffusion |
| S-04 | Audit JSONL, `request_id`, rôles default-deny | Audit et sécurité |
| S-05 | Isolation par espace/application | Multi-tenant |
| S-06 | HLS, sous-titres, covers, révisions | Médias |
| S-07 | Procédures de sauvegarde/restauration documentées | Exploitation |

### 2.3 Verdict

Le prototype est un **bon spike de découverte** : il prouve l'authentification
Google, le rendu catalogue, le lecteur et la persistance d'une position. Il ne
constitue pas un backend de plateforme de livres audio. La cible doit être
construite comme un domaine séparé, en réutilisant AURA pour le stockage.

---

## 3. Revue de cohérence du design

| Critère | Statut | Commentaire |
|---|---|---|
| Frontières de domaines | ✅ | 12 domaines, dépendances explicites, pas de cycle |
| Distinction des concepts | ✅ | Œuvre/édition/enregistrement/piste/actif, bibliothèque/droit, etc. |
| Règles métier | ✅ | 100+ règles identifiées, chacune avec couche d'application |
| Invariants | ✅ | 22 invariants, matrice de couverture |
| Cycles de vie | ✅ | 16 machines à états, transitions interdites |
| Scénarios de défaillance | ✅ | 40 scénarios + 3 études approfondies |
| Permissions | ✅ | Matrice, séparation des devoirs, identités de service |
| Tests d'acceptation | ✅ | Matrice de 60+ cas, tests de propriété |
| Plan de réalisation | ✅ | 5 lots, gates, migration |
| Registre des risques | ✅ | 20 risques, mitigations |
| Modèle de données physique | ⚠️ | DDL prototype dans `audiobook/migrations/0001_initial.sql`, non déployé ; à revalider après décisions |
| Migration | ⚠️ | Principe défini ; inventaire réel à mesurer |
| Juridique | ❌ | Non couvert : droits, RGPD, TVA, contenus personnels |
| Sécurité opérationnelle | ⚠️ | Principes définis ; threat model détaillé à produire |
| Performance | ⚠️ | Cibles hypothétiques ; tests à faire |
| Prestataires | ⚠️ | Non sélectionnés (paiement, e-mail, DRM) |

**Contradictions détectées :** aucune contradiction interne majeure dans le
dossier. Les points ouverts sont des **décisions non prises**, pas des règles
incohérentes.

---

## 4. Décisions ouvertes

Chaque décision est bloquante pour au moins un lot. Une décision non prise doit
être documentée comme hypothèse explicite, jamais laissée implicite dans le code.

### D-01 — Frontière AURA / Audiobook et déploiement

**Question :** où vit le domaine audiobook ?

| Option | Description | Recommandation |
|---|---|---|
| A | Service `audiobook-api` séparé, PostgreSQL dédié, AURA via `StoragePort` | ✅ **Recommandé** |
| B | Monolithe modulaire dans le dépôt actuel, schéma/tables séparés | Acceptable en transition |
| C | Étendre `api/main.py` et `public_ui.py` | ❌ Rejeté |

**Impact :** architecture, sécurité, exploitation, coût. **Bloque :** Lot 1.
**Recommandation :** A. Si B est choisi, interdire toute table partagée avec
AURA et tout accès direct au repository AURA depuis le module audiobook.

### D-02 — Modèle commercial du MVP

**Question :** que vend-on au lancement ?

| Option | Description | Recommandation |
|---|---|---|
| A | Catalogue gratuit + abonnement + achats à l'unité + previews | ✅ **Recommandé** |
| B | Abonnement uniquement | Plus simple, moins de flexibilité |
| C | Achat à l'unité uniquement | Pas de revenu récurrent |
| D | Crédits / jetons | Complexité supplémentaire |

**Impact :** modèle d'entitlement, prix, facturation, UX. **Bloque :** Lot 3,
mais le modèle d'accès doit être prêt dès le Lot 2.

### D-03 — Identité et authentification

**Question :** comment les auditeurs se connectent-ils ?

| Option | Description | Recommandation |
|---|---|---|
| A | Google OIDC uniquement (MVP) | ✅ **Recommandé** pour continuité |
| B | Google + magic link e-mail | Recommandé ensuite |
| C | E-mail + mot de passe | Coût sécurité et support |

**Impact :** compte, vérification e-mail, récupération, RGPD. **Bloque :** Lot 1.
**Recommandation :** A au lancement, B en Lot 2/4. Ne pas réutiliser `users`
d'AURA.

### D-04 — Prestataire de paiement, devises et fiscalité

**Question :** qui encaisse et gère la TVA ?

| Option | Description | Recommandation |
|---|---|---|
| A | Stripe + Stripe Tax, EUR, UE | ✅ **Recommandé** si disponible |
| B | Mollie/Adyen + moteur fiscal | Selon pays |
| C | Merchant of Record (Paddle, Lemon Squeezy) | Simplifie la TVA, coût plus élevé |

**Impact :** webhooks, factures, remboursements, conformité. **Bloque :** Lot 3.
**Recommandation :** A pour le contrôle, C si la fiscalité internationale est un
frein. Limiter pays/devises du MVP.

### D-05 — Contenus personnels importés

**Question :** autorise-t-on l'import de fichiers personnels au lancement ?

| Option | Description | Recommandation |
|---|---|---|
| A | Oui, privés, quota, scan, jamais publiables | ✅ **Recommandé** si politique légale validée |
| B | Plus tard (Lot 4) | Réduit le risque initial |
| C | Non | Perd la différenciation hybride |

**Impact :** stockage, copyright, modération, privacy, coût. **Bloque :** Lot 1
ou Lot 4 selon la réponse.
**Recommandation :** A avec quota et politique claire ; sinon B.

### D-06 — Hors ligne et DRM

**Question :** peut-on télécharger, et avec quelle protection ?

| Option | Description | Recommandation |
|---|---|---|
| A | Téléchargement avec grant/lease lié à l'appareil, sans DRM fort | ✅ **Recommandé** pour le MVP |
| B | Pas de hors ligne au lancement | Plus sûr, moins utile |
| C | DRM (Widevine/FairPlay/CENC) | Coût et complexité élevés |

**Impact :** sécurité du contenu, UX, coût. **Bloque :** Lot 4.
**Recommandation :** A, en documentant la limite : sans DRM, un fichier
téléchargé peut être copié ; le lease contrôle l'accès légitime, pas la copie.

### D-07 — Territoires et restrictions de droits

**Question :** diffusion mondiale ou restreinte dès le lancement ?

| Option | Description | Recommandation |
|---|---|---|
| A | Mondial au lancement, modèle prêt pour les restrictions | ✅ **Recommandé** |
| B | Restrictions par territoire dès le lancement | Si les contrats l'exigent |
| C | Aucune gestion de territoire | ❌ Rejeté |

**Impact :** complexité des droits, cache, géolocalisation, UX. **Bloque :** Lot 2.
**Recommandation :** A, avec le modèle `RightsWindow` prêt ; activer les
restrictions dès qu'un contrat l'exige.

### D-08 — Reprise du portail existant et sort de `/m/{slug}`

**Question :** que fait-on du prototype ?

| Option | Description | Recommandation |
|---|---|---|
| A | Geler, migrer les identités/progressions, retirer `/m/` payant | ✅ **Recommandé** |
| B | Reconstruire le catalogue manuellement | Plus propre, plus long |
| C | Garder le prototype en production | ❌ Rejeté pour le payant |

**Impact :** migration, support, sécurité. **Bloque :** Lot 1.
**Recommandation :** A. Les slugs existants deviennent des previews ou sont
redirigés ; aucun contenu payant ne reste accessible sans décision d'accès.

### D-09 — Base de données et migrations

**Question :** quel stockage pour le domaine audiobook ?

| Option | Description | Recommandation |
|---|---|---|
| A | PostgreSQL dédié (base ou schéma), migrations versionnées | ✅ **Recommandé** |
| B | PostgreSQL partagé avec AURA, tables séparées | Acceptable |
| C | Parité SQLite/PostgreSQL comme AURA | ❌ Coût excessif pour le commerce |

**Impact :** transactions, contraintes, tests, exploitation. **Bloque :** Lot 1.
**Recommandation :** A. Le domaine audiobook ne doit pas dépendre du backend
SQLite de développement d'AURA.

### D-10 — Suppression de compte, rétention et obligations légales

**Question :** que conserve-t-on après suppression ?

| Élément | Recommandation | À valider |
|---|---|---|
| Compte | Suppression logique + anonymisation après grâce (30 j) | Durée exacte |
| Imports personnels | Suppression des octets | Délai |
| Factures / paiements / grand livre | Conservation légale | Durée (ex. 10 ans) |
| Événements d'écoute | Anonymisation ou suppression | Durée |
| Audit de sécurité | Conservation distincte | Durée |
| Sauvegardes | Purge selon cycle | Durée |

**Impact :** RGPD, comptabilité, litiges. **Bloque :** Lot 1 et Lot 3.
**Recommandation :** faire valider par un conseil juridique ; rendre les durées
configurables et auditées, sans jamais supprimer une écriture financière.

### D-11 — Limites d'appareils et de sessions

**Question :** combien d'appareils et d'écoutes simultanées ?

**Recommandation :** 3 appareils, 2 sessions simultanées, 1 lease de progression
actif. Paramètres configurables et auditables. **Bloque :** Lot 2.

### D-12 — Niveau de service et hébergement

**Question :** reste-t-on sur un VPS unique ?

**Recommandation :** conserver le VPS pour le pilote, mais exiger une sauvegarde
indépendante et un test de restauration avant toute ouverture payante. Un
deuxième nœud/read replica est un sujet Lot 5. **Bloque :** Lot 3 (ouverture
commerciale).

---

## 5. Matrice de traçabilité

| Exigence du brief | Domaine | Documents | Décisions |
|---|---|---|---|
| Identité, comptes, sessions, appareils | DOM-01 | 01, 02, 03, 04, 05 | D-03, D-10, D-11 |
| Catalogue, auteurs, narrateurs, éditions | DOM-02 | 01, 02, 03, 04 | D-08 |
| Bibliothèque, favoris, imports | DOM-03 | 01, 02, 03, 04 | D-05 |
| Fichiers, chapitres, intégrité | DOM-04 | 01, 02, 03, 04 | D-09 |
| Écoute, progression, synchronisation | DOM-05 | 01, 02, 03, 04, 06 | D-11 |
| Droits, licences, restrictions | DOM-06 | 01, 02, 03, 04 | D-07 |
| Abonnements, paiements, remboursements | DOM-07 | 01, 02, 03, 04, 06 | D-02, D-04, D-10 |
| Téléchargements, hors ligne | DOM-08 | 01, 02, 03, 04, 06 | D-06 |
| Recherche, classement, recommandations | DOM-09 | 01, 03, 07 | D-02 |
| Notifications | DOM-10 | 01, 03, 06 | D-04 |
| Administration, modération, audit | DOM-11 | 01, 03, 04, 05 | D-01, D-10 |
| Statistiques, analytique | DOM-12 | 01, 03, 07 | D-02 |
| 12 invariants du brief | transverse | 03 | Toutes |
| Scénarios de défaillance | transverse | 06, 07 | Toutes |
| Plan et risques | transverse | 08 | Toutes |

---

## 6. Ce qui doit être validé avant le Lot 1

1. **D-01** : frontière et déploiement.
2. **D-03** : identité.
3. **D-05** : contenus personnels (au moins la décision de principe).
4. **D-08** : reprise du portail et sort de `/m/{slug}`.
5. **D-09** : base de données.
6. **D-10** : rétention/suppression (au moins les principes).
7. **D-12** : sauvegarde/restauration avant toute ouverture payante.
8. **Threat model** : menaces, surfaces, secrets, webhooks, imports.
9. **Inventaire de migration** : volumes et qualité réels.

Avant le Lot 3, ajouter :

10. **D-02** : modèle commercial.
11. **D-04** : prestataire, devises, fiscalité.
12. **D-06** : hors ligne/DRM (si le Lot 4 est planifié).
13. **D-07** : territoires.

---

## 7. Décisions déjà prises dans ce dossier (hypothèses de travail)

Ces choix sont **proposés** et doivent être confirmés ou infirmés :

| Hypothèse | Statut |
|---|---|
| AURA reste la couche de stockage/diffusion, pas le backend commercial | Proposé |
| Les auditeurs sont un domaine séparé des opérateurs AURA | Proposé |
| Le slug public n'est jamais un droit d'accès | **Ferme** (sécurité) |
| La progression est un journal d'événements + projection | **Ferme** (technique) |
| Le paiement confirmé est la seule source d'entitlement payant | **Ferme** (métier) |
| Un import personnel n'est jamais public | **Ferme** (sécurité/produit) |
| Les décisions d'accès sont auditables | **Ferme** (sécurité) |
| Aucune publication sans droits et actif prêt | **Ferme** (métier) |
| Les montants sont en unités mineures | **Ferme** (technique) |
| Les événements et l'audit sont append-only | **Ferme** (technique) |

---

## 8. Gate de validation

**État actuel :** recommandations de conception **acceptées** (D-01 à D-12, options recommandées) ; **Lots 1 et 2 implémentés et testés** dans `audiobook/` (schéma PostgreSQL/migrations, domaine, services, API, 31 tests). Lot 1 : catalogue gratuit, bibliothèque, accès audité, écoute multi-appareils/conflits, admin de base. Lot 2 : droits/territoires/contrats, entitlements manuels/révocation, résolveur d'accès renforcé, historique/stats personnels de base, tableau de bord des refus. L'acceptation des décisions de conception n'équivaut pas à une autorisation de déploiement commercial.

**Décisions de conception :**

- [x] D-01 tranchée — service séparé, AURA via `StoragePort`
- [x] D-02 tranchée (principe MVP) — gratuit + abonnement + achat + previews
- [x] D-03 tranchée — Google OIDC (MVP), identité auditeur séparée
- [x] D-04 tranchée (principe, avant Lot 3) — Stripe + Stripe Tax, EUR/UE (MVP)
- [x] D-05 tranchée — imports personnels privés, quota, jamais publics
- [x] D-06 tranchée (avant Lot 4) — leases/offline sans DRM fort au MVP
- [x] D-07 tranchée (avant Lot 2) — mondial au lancement, modèle de restrictions prêt
- [x] D-08 tranchée — geler/migrer le prototype, retirer `/m/` payant
- [x] D-09 tranchée — PostgreSQL dédié/schéma dédié, migrations versionnées
- [x] D-10 tranchée (principes validés) — rétention/suppression configurable, écritures financières immuables
- [x] D-11 tranchée — 3 appareils, 2 sessions, 1 bail (paramétrable)
- [x] D-12 tranchée — VPS pilote, sauvegarde indépendante + restauration testée avant ouverture payante

**Conditions restantes avant déploiement/ouverture :**

- [ ] Threat model revu
- [ ] Inventaire de migration mesuré (portail/progressions/slugs)
- [ ] Revue juridique planifiée (droits, RGPD, CGV, TVA, contenu importé)
- [ ] Prestataire de paiement testé en sandbox (avant Lot 3)
- [ ] Sauvegarde indépendante et test de restauration validés (avant ouverture payante)
- [ ] Identité de service AURA dédiée et configuration production
- [ ] Retrait effectif de l'accès public payant via `/m/{slug}` (D-08)
- [ ] Budget/équipe confirmés

**Prochaine tranche :** compléter le Lot 1 (intégration AURA réelle, politique D-11 globale, retrait `/m/` payant/migration, durcissement auth/SSO admin) puis Lot 2 (droits/territoires avancés, lecture enrichie, limites configurables). Aucun paiement, aucun offline fort, aucun import public avant leurs lots/gates.

---

## 9. Ce que cette revue ne prouve pas

- Elle ne prouve pas la conformité juridique.
- Elle ne prouve pas la sécurité de l'implémentation future.
- Elle ne prouve pas la tenue en charge.
- Elle ne prouve pas la qualité du catalogue existant.
- Elle ne remplace pas un test de restauration réel.
- Elle ne décide pas du modèle commercial.

Ces éléments sont des **conditions de sortie**, pas des détails.
