# 03 — Catalogue des règles métier et registre des invariants

**Objectif :** rendre chaque règle explicite, testable et rattachée à une couche
d'application. Une règle non enforceable n'est pas une règle : c'est un souhait.

---

## 1. Conventions

Chaque règle porte un identifiant `BR-<DOMAINE>-<NN>`.

**Couches d'application :**

| Code | Couche | Exemple |
|---|---|---|
| `API` | Validation d'entrée, authentification, autorisation | Rejet 422/403/404 |
| `DOM` | Agrégat, machine à états, politique métier | Transition refusée |
| `DB` | Contrainte, index unique, transaction | `UNIQUE(listener_id, work_id)` |
| `TX` | Transaction + idempotence + outbox | Paiement + entitlement |
| `WKR` | Worker, retry, réconciliation | Webhook, scrub, purge |
| `AUD` | Journal d'audit immuable | Action administrative |
| `TST` | Test d'acceptation / propriété | Concurrence, doublons |

**Règle de lecture :** une règle peut être appliquée à plusieurs couches ; la
couche indiquée est la **garantie minimale**. Les tests correspondants sont dans
[`07-acceptance-tests.md`](07-acceptance-tests.md).

---

## 2. DOM-01 — Identité et auditeurs

| ID | Règle | Application |
|---|---|---|
| BR-USR-01 | L'identité d'un auditeur est `(provider, subject)` ; l'e-mail n'est jamais une clé d'identité. | `DB` unique `(provider, subject)` |
| BR-USR-02 | Un compte est `active`, `suspended`, `blocked`, `pending_deletion` ou `deleted`. Seul `active` peut acheter, écouter ou télécharger. | `DOM`, `API` |
| BR-USR-03 | Un compte `suspended` conserve ses données, sa bibliothèque et ses droits ; il peut consulter son compte et sa facturation, mais ne peut pas lancer de nouvelle écoute, achat ou téléchargement. | `DOM`, `API` |
| BR-USR-04 | Un compte `blocked` ne peut plus se connecter ; les sessions et leases sont révoqués. | `DOM`, `API` |
| BR-USR-05 | Un compte `pending_deletion` est en lecture seule ; aucune nouvelle donnée n'est créée, sauf les traces légales. | `DOM` |
| BR-USR-06 | La suppression d'un compte exige la résolution de l'abonnement actif, conserve les factures et écritures comptables selon la durée légale, anonymise les données personnelles et supprime les imports personnels. | `TX`, `WKR`, `AUD` |
| BR-USR-07 | Le changement d'e-mail exige une vérification, reste unique, notifie l'ancienne adresse et ne change pas l'identité fédérée. | `DOM`, `AUD` |
| BR-USR-08 | Un auditeur peut avoir plusieurs appareils (maximum configurable, recommandé 3) ; chaque appareil est identifiable et révocable. | `DB`, `DOM` |
| BR-USR-09 | La révocation d'un appareil invalide immédiatement ses sessions et empêche le renouvellement de ses leases hors ligne. | `TX`, `WKR` |
| BR-USR-10 | Les préférences (langue, vitesse, saut, téléchargement, notifications) sont séparées de l'identité et conservées lors des changements de profil. | `DB` |
| BR-USR-11 | Toute action sensible (changement d'e-mail, suppression, révocation d'appareil, impersonation) est auditée avec acteur, cible, avant/après et `request_id`. | `AUD` |
| BR-USR-12 | Un auditeur ne peut jamais lire les données privées d'un autre ; une ressource hors périmètre répond 404, pas 403. | `API`, `DB` |

---

## 3. DOM-02 — Catalogue éditorial

| ID | Règle | Application |
|---|---|---|
| BR-CAT-01 | Une œuvre a un identifiant stable ; son titre peut changer sans changer son identifiant. | `DOM` |
| BR-CAT-02 | Une œuvre peut avoir plusieurs auteurs, narrateurs, traducteurs et autres contributeurs, avec rôles et ordre. | `DB` |
| BR-CAT-03 | Une œuvre peut avoir plusieurs éditions (langue, éditeur, présentation) et une édition plusieurs enregistrements. | `DB` |
| BR-CAT-04 | Une édition contient des chapitres ordonnés et des pistes ordonnées ; les positions sont uniques. | `DB` |
| BR-CAT-05 | Les bornes d'un chapitre sont dans la durée de l'enregistrement ; les chapitres ne se chevauchent pas. | `DOM`, `DB` |
| BR-CAT-06 | Une édition ne peut être publiée que si : titre, langue, au moins un auteur, au moins un narrateur, description, catégorie, couverture, durée > 0, au moins une piste `ready`, et une fenêtre de droits active pour le canal visé. | `DOM` |
| BR-CAT-07 | Un fichier uploadé ne publie jamais automatiquement une édition ; la publication est un acte éditorial explicite. | `DOM`, `AUD` |
| BR-CAT-08 | Une édition non publiée n'apparaît ni dans la découverte, ni dans les recommandations, ni dans les résultats publics. | `API` |
| BR-CAT-09 | Une édition retirée disparaît de la découverte mais reste référencée dans les bibliothèques, l'historique et les droits acquis ; son état est affiché « indisponible ». | `DOM` |
| BR-CAT-10 | Une indisponibilité temporaire (actif manquant, maintenance, droits suspendus) ne supprime ni l'édition ni les références. | `DOM` |
| BR-CAT-11 | Un changement de métadonnées préserve les identifiants, les slugs et les références ; un slug retiré n'est jamais réattribué. | `DB`, `DOM` |
| BR-CAT-12 | Une collection éditoriale peut être supprimée sans supprimer les œuvres ou éditions qu'elle référence. | `DB` |
| BR-CAT-13 | L'ordre des items d'une collection est explicite et stable ; une collection publiée ne contient que des éditions publiées. | `DOM` |
| BR-CAT-14 | Une œuvre peut être signalée comme doublon potentiel, mais n'est jamais fusionnée automatiquement. | `DOM`, `AUD` |

---

## 4. DOM-03 — Bibliothèque personnelle

| ID | Règle | Application |
|---|---|---|
| BR-LIB-01 | Une entrée de bibliothèque appartient à un seul auditeur et référence une œuvre, avec une édition préférée optionnelle. | `DB` |
| BR-LIB-02 | Il existe au plus une entrée active par `(listener, work)` ; un ajout répété est idempotent. | `DB` unique partiel |
| BR-LIB-03 | Ajouter un livre à sa bibliothèque ne crée pas de droit d'écoute. | `DOM` |
| BR-LIB-04 | Retirer un livre de sa bibliothèque ne supprime ni l'œuvre, ni l'achat, ni l'entitlement, ni la progression. | `DOM` |
| BR-LIB-05 | Un favori est idempotent et personnel ; il ne modifie pas la bibliothèque. | `DB` |
| BR-LIB-06 | Une collection personnelle appartient à un seul auditeur ; un item ne peut y être présent qu'une fois. | `DB` |
| BR-LIB-07 | Supprimer une collection personnelle ne supprime aucune entrée de bibliothèque. | `DOM` |
| BR-LIB-08 | Une entrée dont l'édition est devenue indisponible reste visible avec un état explicite ; elle n'est pas supprimée. | `API` |
| BR-LIB-09 | Un import personnel est privé par défaut, accessible au seul propriétaire, et ne peut jamais être publié, partagé ou indexé. | `API`, `DB` |
| BR-LIB-10 | Supprimer un import personnel supprime ses octets et ses dérivés, mais pas les entrées de bibliothèque qui le référencent : celles-ci passent en état « supprimé ». | `TX`, `WKR` |
| BR-LIB-11 | Un import en double (même checksum) est signalé ; l'auditeur choisit explicitement de conserver, remplacer ou annuler. | `DOM` |
| BR-LIB-12 | Les métadonnées incomplètes sont tolérées pour un import personnel, jamais pour une publication catalogue. | `DOM` |

---

## 5. DOM-04 — Actifs audio

| ID | Règle | Application |
|---|---|---|
| BR-AST-01 | Chaque actif a un identifiant, un checksum SHA-256, une taille vérifiée et un type MIME contrôlé. | `DB`, `WKR` |
| BR-AST-02 | Un actif est rattaché à un enregistrement/édition (ou à un import personnel), jamais à un livre « en général ». | `DB` |
| BR-AST-03 | Seuls les formats autorisés sont acceptés (liste configurable : MP3, M4A/AAC, FLAC, WAV selon politique). | `API`, `WKR` |
| BR-AST-04 | La validation vérifie les octets (magic bytes), le conteneur, le codec, la durée, le débit et les métadonnées ; l'extension seule ne suffit pas. | `WKR` |
| BR-AST-05 | Un actif passe par `quarantined` et un scan antivirus avant de devenir `ready` ; un résultat infecté le bloque. | `WKR` |
| BR-AST-06 | Un actif `initiated`, `uploaded` ou `validating` n'est jamais lisible publiquement. | `API` |
| BR-AST-07 | Un actif `rejected`, `blocked` ou corrompu n'est jamais publié ni diffusé. | `DOM`, `API` |
| BR-AST-08 | Le remplacement crée une nouvelle version ; l'ancienne reste disponible jusqu'à la bascule atomique, puis pendant une grâce de rollback. | `TX`, `WKR` |
| BR-AST-09 | La bascule d'une piste vers un nouvel actif est atomique ; une panne avant/après ne laisse pas une piste à moitié remplacée. | `TX` |
| BR-AST-10 | Les actifs inutilisés sont identifiés après une grâce, mais ne sont purgés qu'après vérification des références et des obligations de conservation. | `WKR`, `AUD` |
| BR-AST-11 | Un dérivé (HLS, cover, sous-titre) hérite des droits et de la confidentialité de sa source. | `DOM` |
| BR-AST-12 | La clé de stockage est générée côté serveur ; aucun client ne choisit un bucket ou une clé. | `API` |

---

## 6. DOM-05 — Écoute et progression

| ID | Règle | Application |
|---|---|---|
| BR-PLY-01 | La progression est identifiée par `(listener, edition)`, pas par piste ; la piste et l'offset sont dérivés de la position globale. | `DB` |
| BR-PLY-02 | Chaque session d'écoute a un identifiant serveur, un appareil et une séquence cliente strictement croissante. | `DB`, `DOM` |
| BR-PLY-03 | Chaque événement d'écoute est append-only et idempotent par `event_id` ; un doublon est un no-op. | `DB`, `API` |
| BR-PLY-04 | Une position invalide (négative, NaN, > durée + tolérance) est rejetée et ne remplace jamais une position valide. | `API`, `DOM` |
| BR-PLY-05 | Une position ancienne reçue en retard est conservée comme historique mais ne remplace pas la progression d'une session active plus récente. | `DOM` |
| BR-PLY-06 | Un retour en arrière volontaire est un `seek` de la session active ; il est accepté et remplace la position, même si elle est inférieure. | `DOM` |
| BR-PLY-07 | Une session est `active` si elle détient le lease d'écoute ; un heartbeat absent pendant 2 minutes la rend `stale`. | `WKR`, `DOM` |
| BR-PLY-08 | Une nouvelle session peut prendre le lease si aucune session active n'a d'événement récent, ou après une action explicite de reprise. | `DOM` |
| BR-PLY-09 | Un événement d'une session non active renvoie l'état autoritatif (409) et ne modifie pas la progression ; le client propose « reprendre ici » ou « continuer ailleurs ». | `API` |
| BR-PLY-10 | Un livre est `completed` uniquement sur événement `ended` ou position ≥ durée − seuil (min 30 s, 2 %), jamais sur un simple heartbeat. | `DOM` |
| BR-PLY-11 | Un redémarrage crée un nouveau `listening_run` ; `completed_at` et l'historique ne sont pas effacés. | `DOM` |
| BR-PLY-12 | Les événements hors ligne sont synchronisés dans l'ordre `client_seq`, avec `occurred_at_client` ; un conflit est signalé, jamais écrasé silencieusement. | `API`, `DOM` |
| BR-PLY-13 | Les statistiques d'écoute sont calculées depuis les événements validés, pas depuis la projection de progression. | `WKR` |
| BR-PLY-14 | Une progression ne peut être enregistrée que pour une édition publiée et autorisée pour cet auditeur. | `API` |

---

## 7. DOM-06 — Droits et autorisations

| ID | Règle | Application |
|---|---|---|
| BR-ACC-01 | Une décision d'accès vérifie : compte actif, entitlement actif, droits de diffusion actifs, actif prêt, appareil autorisé et limites du plan. | `DOM` |
| BR-ACC-02 | La présence dans la bibliothèque n'est jamais une preuve de droit. | `DOM` |
| BR-ACC-03 | Un achat ne crée un entitlement qu'après confirmation du paiement. | `TX` |
| BR-ACC-04 | Un abonnement actif donne accès au périmètre de son plan pendant la période courante, et à rien d'autre. | `DOM` |
| BR-ACC-05 | Un abonnement expiré, annulé ou en `past_due` au-delà de la grâce ne donne plus accès aux nouveaux contenus ; les URLs en cours expirent à court terme. | `DOM`, `API` |
| BR-ACC-06 | Un remboursement révoque l'entitlement direct associé, sauf si une autre source maintient l'accès ; la politique de remboursement d'abonnement est explicite. | `TX`, `DOM` |
| BR-ACC-07 | Un contenu retiré pour droits ne peut plus être ni streamé ni téléchargé ; la bibliothèque et l'historique restent visibles. | `DOM` |
| BR-ACC-08 | Les restrictions territoriales et temporelles sont évaluées au moment de la décision, pas seulement à la publication. | `DOM` |
| BR-ACC-09 | Un import personnel utilise une politique `OwnerOnly` : propriétaire, compte actif, appareil autorisé, aucune exigence de droits catalogue. | `DOM` |
| BR-ACC-10 | Toute décision (`allow`/`deny`) est journalisée avec raison, sources, version de politique et expiration ; aucun secret ni URL n'y figure. | `AUD` |
| BR-ACC-11 | Une décision peut être mise en cache au maximum 60 secondes ; elle est invalidée sur changement d'entitlement, de droits, de statut de compte ou d'actif. | `DOM` |
| BR-ACC-12 | Aucun client ne peut déclarer un entitlement, un prix, un statut de paiement ou un rôle. | `API` |

---

## 8. DOM-07 — Abonnements et paiements

| ID | Règle | Application |
|---|---|---|
| BR-BIL-01 | Une offre et un prix sont versionnés ; un prix publié n'est pas modifié rétroactivement. | `DB`, `DOM` |
| BR-BIL-02 | Un abonnement a des périodes explicites ; le renouvellement crée une nouvelle période. | `DB` |
| BR-BIL-03 | Un paiement est rapproché d'une commande et d'une facture ; aucun paiement orphelin. | `DB` |
| BR-BIL-04 | Un paiement en attente ne donne aucun accès. | `DOM` |
| BR-BIL-05 | Un paiement confirmé n'est comptabilisé qu'une fois : `(provider, event_id)` et `(provider, payment_id)` uniques. | `DB`, `TX` |
| BR-BIL-06 | Un remboursement est un mouvement distinct, traçable, avec un plafond cumulé ≤ montant payé. | `DB`, `TX` |
| BR-BIL-07 | Une annulation d'abonnement prend effet à la fin de la période, sauf politique d'annulation immédiate explicitement confirmée. | `DOM` |
| BR-BIL-08 | Un échec de renouvellement déclenche `past_due`, une grâce configurable, des notifications, puis `expired`. | `WKR`, `DOM` |
| BR-BIL-09 | Un changement d'offre suit une politique de prorata ou de date d'effet explicite ; il ne crée jamais deux accès concurrents non voulus. | `DOM` |
| BR-BIL-10 | Les historiques financiers (commandes, paiements, factures, remboursements, grand livre) sont conservés et immuables. | `DB`, `AUD` |
| BR-BIL-11 | Le prestataire est la source de vérité du paiement ; une réconciliation périodique détecte les événements manquants ou perdus. | `WKR` |
| BR-BIL-12 | Un impayé, une contestation ou un `chargeback` révoque l'accès selon la politique et crée une écriture de grand livre. | `TX`, `DOM` |
| BR-BIL-13 | Les montants sont en unités mineures, la devise est explicite, la TVA est calculée par le prestataire ou le moteur fiscal. | `DOM` |
| BR-BIL-14 | Aucune donnée de carte bancaire ne transite ou n'est stockée par le backend. | `API` |

---

## 9. DOM-08 — Téléchargements et hors ligne

| ID | Règle | Application |
|---|---|---|
| BR-OFF-01 | Un téléchargement exige un entitlement actif, des droits actifs, un actif prêt et un appareil autorisé. | `DOM` |
| BR-OFF-02 | Chaque grant est lié à un appareil, une édition, une expiration et un nombre d'usages maximal. | `DB` |
| BR-OFF-03 | L'expiration d'un grant ne dépasse jamais celle de l'entitlement ou de la fenêtre de droits. | `DOM` |
| BR-OFF-04 | Un téléchargement incomplet ou dont le checksum ne correspond pas n'est jamais déclaré disponible. | `API`, `WKR` |
| BR-OFF-05 | Un lease hors ligne a une durée maximale (recommandé 30 jours) et doit être renouvelé par une nouvelle décision d'accès. | `DOM` |
| BR-OFF-06 | La suppression locale d'un contenu ne supprime pas le grant ni le contenu serveur. | `API` |
| BR-OFF-07 | La progression hors ligne est mise en file locale, synchronisée avec `event_id` et `client_seq`, et réconciliée selon BR-PLY-12. | `API` |
| BR-OFF-08 | Un appareil révoqué ne peut plus renouveler un lease ; le lease existant expire au plus tard à sa date de fin. | `DOM`, `WKR` |
| BR-OFF-09 | Un retrait de droits bloque le renouvellement ; sans DRM, le backend ne peut pas effacer un fichier déjà téléchargé et doit le documenter comme limite. | `DOM`, `WKR` |

---

## 10. DOM-09 — Découverte et recommandations

| ID | Règle | Application |
|---|---|---|
| BR-DSC-01 | La recherche couvre titre, auteur, narrateur, catégorie, langue et durée. | `API` |
| BR-DSC-02 | Seules les éditions publiées et disponibles sont présentées comme « immédiatement écoutables » ; une édition indisponible est marquée comme telle. | `API` |
| BR-DSC-03 | La popularité est calculée depuis des événements cohérents (écoutes réelles, complétions), pas depuis les clics ou les vues de page. | `WKR` |
| BR-DSC-04 | Les imports personnels et les données privées ne sont jamais indexés publiquement. | `API`, `DB` |
| BR-DSC-05 | Un classement éditorial payant est signalé comme tel ; un classement organique n'est pas secrètement modifié par la publicité. | `DOM` |
| BR-DSC-06 | Une recommandation exclut les contenus non publiés, retirés ou interdits dans le territoire de l'auditeur. | `API` |

---

## 11. DOM-10 — Notifications

| ID | Règle | Application |
|---|---|---|
| BR-NOT-01 | Une notification n'est émise qu'après confirmation de l'événement métier (paiement confirmé, téléchargement terminé, etc.). | `TX`, `WKR` |
| BR-NOT-02 | Les préférences par catégorie et canal sont respectées ; les notifications transactionnelles et de sécurité ne peuvent pas être désactivées. | `DOM` |
| BR-NOT-03 | Chaque notification a une clé de déduplication ; un événement rejoué ne produit pas de doublon. | `DB` |
| BR-NOT-04 | Les envois sont retentés avec backoff, puis placés en file morte avec alerte. | `WKR` |
| BR-NOT-05 | Les notifications non urgentes respectent les heures calmes et les limites de fréquence. | `WKR` |
| BR-NOT-06 | L'historique des notifications importantes est conservé et consultable par l'auditeur. | `DB` |

---

## 12. DOM-11 — Administration et modération

| ID | Règle | Application |
|---|---|---|
| BR-ADM-01 | Les rôles sont à privilège minimal et séparés : support, éditorial, droits, finance, modération, administrateur, auditeur. | `API` |
| BR-ADM-02 | Toute action sensible est attribuable à un acteur, horodatée, motivée et immuable dans l'audit. | `AUD` |
| BR-ADM-03 | Les actions à fort impact (remboursement au-delà d'un seuil, retrait de droits, suppression de compte, publication sensible) exigent une double validation. | `DOM`, `AUD` |
| BR-ADM-04 | Un administrateur n'a pas accès par défaut aux octets des imports personnels ; une procédure légale et auditée est nécessaire. | `API` |
| BR-ADM-05 | Aucune modification directe en base n'est autorisée en production ; les changements passent par des commandes admin. | `OPS` |
| BR-ADM-06 | Une décision de modération est motivée, notifiée et peut faire l'objet d'un recours. | `DOM` |
| BR-ADM-07 | Les journaux d'audit ne sont ni modifiés ni supprimés avant la fin de la rétention légale. | `DB`, `OPS` |
| BR-ADM-08 | Une impersonation de support est consentie, limitée dans le temps, en lecture seule par défaut et auditée. | `API`, `AUD` |

---

## 13. DOM-12 — Statistiques et analytique

| ID | Règle | Application |
|---|---|---|
| BR-ANA-01 | Les indicateurs sont calculés depuis des événements validés et des projections reconstructibles. | `WKR` |
| BR-ANA-02 | Chaque définition d'indicateur est versionnée et documentée (période, dénominateur, exclusions). | `DOC` |
| BR-ANA-03 | Les statistiques personnelles d'un auditeur ne sont visibles que par lui. | `API` |
| BR-ANA-04 | Les indicateurs commerciaux sont réconciliés avec le grand livre et les factures. | `WKR` |
| BR-ANA-05 | Les données analytiques sont pseudonymisées ; aucune PII n'est exposée dans les tableaux de bord. | `DB` |
| BR-ANA-06 | La popularité et les recommandations résistent aux manipulations (écoutes synthétiques, clics répétés). | `WKR` |

---

## 14. Registre des invariants

Un invariant est une propriété qui doit rester vraie après **toute** opération,
y compris les opérations concurrentes, les reprises et les pannes.

| ID | Invariant | Application | Comportement en cas de violation |
|---|---|---|---|
| **INV-01** | Un auditeur ne peut consulter que ses données privées. | `API` + `DB` (filtre propriétaire) | 404, audit de la tentative |
| **INV-02** | Une édition publiée a passé toutes les validations requises. | `DOM` + `TX` | Publication refusée avec blockers |
| **INV-03** | Un actif indisponible, rejeté ou bloqué ne peut pas être diffusé. | `API` + `DOM` | 409/503, aucune URL émise |
| **INV-04** | Un droit d'accès est valide au moment de l'autorisation. | `DOM` | Refus, raison `NO_ACTIVE_ENTITLEMENT` |
| **INV-05** | Un paiement ne peut être comptabilisé deux fois. | `DB` unique + `TX` | No-op idempotent, audit |
| **INV-06** | Une ancienne progression ne remplace pas une progression plus récente sans règle de résolution. | `DOM` + version | 409 avec état autoritatif |
| **INV-07** | Un import personnel ne devient jamais public par défaut. | `DB` + `API` | Publication impossible, 403 |
| **INV-08** | La suppression d'une référence ne supprime pas une ressource partagée. | `DOM` | Détachement, pas de cascade |
| **INV-09** | Un historique financier n'est pas modifié silencieusement. | `DB` append-only | Écriture refusée |
| **INV-10** | Une action administrative sensible est traçable. | `AUD` | Action refusée si audit indisponible |
| **INV-11** | Une publication ne précède pas la validation des droits de diffusion. | `DOM` + `TX` | Publication bloquée |
| **INV-12** | Un téléchargement ne contourne pas les restrictions d'accès. | `DOM` + `DB` | Grant refusé |
| **INV-13** | Il existe une seule progression autoritative par `(listener, edition)`, avec une version strictement croissante. | `DB` + `DOM` | Conflit 409, pas d'écrasement |
| **INV-14** | Les événements d'écoute sont append-only et idempotents. | `DB` + `API` | Doublon ignoré |
| **INV-15** | La complétion n'est pas déduite d'une position ancienne ou d'un heartbeat. | `DOM` | `completed_at` inchangé |
| **INV-16** | Toute décision d'accès est auditable avec sa raison et ses sources. | `AUD` | Refus si décision non traçable |
| **INV-17** | Un import personnel n'est lisible que par son propriétaire et ses appareils autorisés. | `API` + `DB` | 404 |
| **INV-18** | La suppression d'un compte ne détruit pas les obligations financières et fiscales. | `TX` + `WKR` | Suppression différée/refusée |
| **INV-19** | Un lease hors ligne n'excède jamais l'entitlement ou la fenêtre de droits. | `DOM` | Lease refusé/tronqué |
| **INV-20** | Aucune publication sans actif `ready` et métadonnées obligatoires. | `DOM` | Publication refusée |
| **INV-21** | Aucun client ne peut fournir un entitlement, un prix, un statut ou un rôle. | `API` | 422 |
| **INV-22** | Toute projection analytique est reconstructible depuis les événements. | `WKR` + `TST` | Rebuild et alerte |

### 14.1 Matrice de couverture

| Invariant | Règles liées | Domaine | Test principal |
|---|---|---|---|
| INV-01 | BR-USR-12, BR-LIB-09 | Identité / Bibliothèque | AT-SEC-01 |
| INV-02 | BR-CAT-06, BR-CAT-07 | Catalogue | AT-CAT-01 |
| INV-03 | BR-AST-06, BR-AST-07 | Actifs | AT-AST-01 |
| INV-04 | BR-ACC-01, BR-ACC-03 | Accès | AT-ACC-01 |
| INV-05 | BR-BIL-05 | Paiement | AT-BIL-02 |
| INV-06 | BR-PLY-05, BR-PLY-09 | Écoute | AT-PLY-01 |
| INV-07 | BR-LIB-09, BR-CAT-07 | Bibliothèque | AT-LIB-01 |
| INV-08 | BR-CAT-12, BR-LIB-07 | Catalogue / Bibliothèque | AT-LIB-02 |
| INV-09 | BR-BIL-06, BR-BIL-10 | Finance | AT-BIL-03 |
| INV-10 | BR-ADM-02, BR-USR-11 | Admin | AT-ADM-01 |
| INV-11 | BR-CAT-06, BR-ACC-07 | Catalogue / Droits | AT-ACC-02 |
| INV-12 | BR-OFF-01, BR-OFF-03 | Hors ligne | AT-OFF-01 |
| INV-13 | BR-PLY-01, BR-PLY-02 | Écoute | AT-PLY-02 |
| INV-14 | BR-PLY-03 | Écoute | AT-PLY-03 |
| INV-15 | BR-PLY-10 | Écoute | AT-PLY-04 |
| INV-16 | BR-ACC-10 | Accès | AT-ACC-03 |
| INV-17 | BR-LIB-09, BR-ACC-09 | Imports | AT-LIB-03 |
| INV-18 | BR-USR-06, BR-BIL-10 | Identité / Finance | AT-USR-01 |
| INV-19 | BR-OFF-03, BR-OFF-08 | Hors ligne | AT-OFF-02 |
| INV-20 | BR-CAT-06, BR-AST-07 | Publication | AT-CAT-02 |
| INV-21 | BR-ACC-12 | API | AT-SEC-02 |
| INV-22 | BR-ANA-01 | Analytique | AT-ANA-01 |

---

## 15. Règles volontairement configurables

Ces règles ne sont pas des invariants : elles doivent être des paramètres
versionnés, modifiables par un administrateur autorisé, avec audit.

| Paramètre | Valeur de départ proposée | Impact |
|---|---|---|
| Nombre maximal d'appareils | 3 | Sécurité/partage de compte |
| Sessions d'écoute simultanées | 2 | Confort/fraude |
| Seuil de complétion | `max(30 s, 2 %)` | Statistiques |
| Timeout de heartbeat | 120 s | Conflits de progression |
| Durée du lease hors ligne | 30 jours | Disponibilité hors ligne |
| Grâce d'abonnement | 3 jours | Recouvrement |
| TTL d'une URL de lecture | 5 minutes | Révocation |
| TTL d'une décision d'accès | 60 secondes | Fraîcheur |
| Nombre maximal de livres par collection | 500 | Limites |
| Quota d'imports personnels | à définir | Coût/abus |

Toute modification de ces paramètres est une action administrative auditée. Les
valeurs ci-dessus sont des propositions, pas des décisions validées.
