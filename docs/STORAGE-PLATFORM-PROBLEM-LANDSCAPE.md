# Panorama des problèmes des plateformes de stockage et des réponses possibles pour AURA

**Date de recherche :** 14 octobre 2026  
**Statut :** étude d'architecture et registre de risques. Ce document ne prouve pas que les fonctions décrites sont déjà implémentées dans AURA.  
**Périmètre :** stockage objet et fichiers privé, transfert massif, API de stockage partagée par plusieurs applications, catalogue, sécurité, exploitation et récupération.

## 1. Synthèse exécutive

Les plateformes de fichiers et de stockage objet ont largement résolu les problèmes fondamentaux : transfert HTTP/S3, multipart, reprise par morceaux, checksums, versioning, chiffrement, quotas, synchronisation, réplication et sauvegarde. Ces mécanismes sont disponibles sous différentes formes dans les API S3, les clients de synchronisation et les produits de stockage de fichiers.

Le problème restant n'est généralement pas l'absence d'un algorithme. C'est **l'intégration correcte, les garanties réelles du backend, les paramètres adaptés à la charge, les erreurs partielles et les compromis entre sécurité, coût, performances et facilité d'utilisation**.

AURA ne doit donc pas chercher à réinventer S3, un protocole de reprise ou la cryptographie. Elle doit assembler des mécanismes éprouvés, vérifier leur compatibilité avec la version précise de SeaweedFS choisie, et tester les cas d'échec que les interfaces simples masquent.

### Décisions recommandées

1. API de contrôle + transfert direct HTTPS vers S3 avec URL présignée temporaire.
2. Autorisation stricte par application, environnement, tenant et objet; aucun accès public par défaut.
3. Intent d'upload durable, état explicite, validation serveur et commit idempotent.
4. PUT simple pour les petits fichiers; multipart/reprise pour les gros fichiers après tests de compatibilité.
5. Vérification d'intégrité avec des sommes de contrôle explicitement définies; ne pas assimiler un ETag multipart à SHA-256.
6. Chiffrement en transit, chiffrement au repos vérifié, sauvegarde indépendante et test de restauration.
7. File de tâches bornée, quotas, réessais contrôlés et mesures de performance avant tuning.
8. Compression, déduplication, chiffrement côté client, OCR et analyse antivirus avancée uniquement après étude de besoin et des effets secondaires.

## 2. Méthode et limites de la recherche

Cette étude s'appuie sur la documentation officielle AWS S3 relative au multipart et aux checksums, la documentation développeur/administrateur de Nextcloud sur le chunking et les limites des gros fichiers, la documentation OWASP sur les uploads et les recommandations CISA sur les sauvegardes face aux ransomwares, ainsi que des tickets et notes du projet SeaweedFS.

Les plateformes ont des modèles différents : Nextcloud est une plateforme de fichiers et de synchronisation; S3 est une API de stockage objet; SeaweedFS est un backend compatible S3; AURA vise une infrastructure de stockage privée partagée par des applications. Les comportements d'une plateforme ne doivent donc pas être transposés automatiquement à une autre.

Les sources publiques ne donnent pas un classement universel des problèmes « les plus fréquents » pour tous les fournisseurs. Le classement ci-dessous est une **synthèse qualitative des risques récurrents**, pas une statistique mondiale. Les fonctionnalités S3 décrites par AWS ne garantissent pas une compatibilité parfaite dans chaque implémentation S3-compatible. La version et la configuration d'AURA doivent être testées.

## 3. Carte des problèmes communs

Légende :
- **Solution éprouvée :** mécanisme connu disponible; il reste à l'intégrer et le tester.
- **Compromis :** plusieurs réponses valables, aucune n'étant optimale dans tous les cas.
- **Risque ouvert :** pas de solution universelle; AURA doit décider d'une politique ou mesurer le comportement.
- **À vérifier dans AURA :** ne pas déclarer résolu avant preuve sur le backend retenu.

| Domaine | Problème rencontré | Réponses existantes | Position AURA | État de connaissance |
|---|---|---|---|---|
| Réseau | Connexion lente, instable ou coupée | Multipart, reprise, retries, délais bornés | Reprendre par partie et ne retenter que l'échec | Solution éprouvée; compatibilité à tester |
| Gros fichiers | Timeout ou retransmission complète | Upload direct S3, multipart, streaming | Éviter le proxy de gros fichiers via FastAPI | Solution éprouvée |
| Lots massifs | Trop de requêtes simultanées, saturation | File bornée, concurrence limitée, batch manifests | Limites par application/tenant et limite globale | Compromis à mesurer |
| Intégrité | Octets corrompus ou checksum ambigu | CRC pour intégrité de transfert; SHA-256 pour empreinte durable; checksums par partie | Enregistrer algorithme et sémantique; vérifier avant disponibilité | Support exact à vérifier |
| Reprise | Client perdu, session expirée, état inconnu | ID de lot, ID multipart, persistance des parties et nouvelle URL après réautorisation | Intent durable et reprise idempotente | Solution connue; implémentation à concevoir |
| Double envoi | Réessai créant deux objets | Idempotency keys, IDs opaques, contraintes uniques | Idempotence de création, commit et import | Solution éprouvée |
| Isolation | Une application accède aux objets d'une autre | Identité de service, scopes, RBAC/ABAC, autorisation objet par objet | Isolation systématique dans API et catalogue | Exigence P0 |
| URL présignée | Fuite dans logs, historique ou télémétrie | TTL court, portée étroite, redaction, HTTPS | Traiter comme un secret porteur d'accès | Solution connue; risque d'exploitation persistant |
| Secrets S3 | Clé durable dans navigateur ou dépôt | Signature côté serveur, identités dédiées, rotation | Aucun credential S3 durable dans le frontend | Solution éprouvée |
| Fichier malveillant | Extension/MIME falsifié, document exploitable | Allowlist, détection type, quarantaine, scan isolé | Vérifier selon les types acceptés; scanner hors du chemin critique | Compromis/coût |
| Archives | Zip bomb, traversée de chemins, liens symboliques | Limites d'expansion/profondeur/entrées; sandbox | Ne pas extraire automatiquement par défaut | Solution partielle; politique nécessaire |
| Compression | CPU consommé sans gain | Compression sélective et benchmark | Conserver les octets originaux par défaut; zstd pour données compressibles | Compromis mesurable |
| Chiffrement | Vol de disque ou accès opérateur | TLS, SSE-S3/KMS, chiffrement client | TLS + SSE-S3 démontré; chiffrement client optionnel après étude de clés | Solution éprouvée avec coût opérationnel |
| Récupération des clés | Perte de clé rendant les données illisibles | Sauvegarde hors ligne, KMS, procédure de rotation | Clé et procédure de récupération testées avant données importantes | Risque critique si négligé |
| Suppression accidentelle | Suppression abusive ou malveillante | Soft delete, versioning, rétention, object lock si disponible | Soft delete + sauvegarde indépendante; immutabilité à évaluer | Compromis politique/coût |
| Ransomware | Données et sauvegardes accessibles au même compte | Copies hors ligne/isolées, immutabilité, identités distinctes, tests restore | Destination de backup séparée et compte séparé; restauration obligatoire | Solution connue, jamais garantie par le seul stockage |
| Durabilité | Disque ou VPS perdu | Réplication, multi-zone, sauvegarde séparée | Un VPS n'est pas HA; backup hors domaine de panne | Limite structurelle actuelle |
| Catalogue vs objet | Upload réussi mais commit DB échoué | Machine à états, outbox/reconciliation, tâches idempotentes | Objet pending jusqu'à vérification; réconciliation prudente | Pas de transaction atomique universelle |
| Recherche et métadonnées | Catalogue incohérent ou lent | Index, pagination, catalogue relationnel | PostgreSQL pour métadonnées; indexation progressive | Solution éprouvée; modèle à valider |
| Déduplication | Copies répétées consomment de l'espace | Déduplication par contenu ou par blocs | Pas de déduplication inter-tenant au départ | Compromis sécurité/confidentialité |
| Prévisualisation/OCR | Parseurs vulnérables, CPU/RAM élevés | Workers isolés, limites et files asynchrones | Différer jusqu'à besoin métier explicite | Compromis |
| Observabilité | Pannes invisibles ou logs sensibles | Metrics, traces, logs structurés et redaction | Mesurer débits, erreurs, capacité et backlog sans secrets | Solution éprouvée |
| Interopérabilité | Client S3 supposant un comportement non supporté | Tests de conformité, tests SDK, version pinning | Tester les opérations utilisées contre SeaweedFS exact | Risque ouvert tant que non testé |
| Coût/capacité | Disque plein, croissance imprévisible | Quotas, alertes, lifecycle, limites de lots | Refuser tôt les nouvelles écritures avant saturation | Solution connue; seuils à mesurer |
| Migration | Données d'un ancien serveur à importer | Import job, manifeste, checksums, reprise | Adapter FTPS/legacy uniquement au besoin; même pipeline de validation | Solution intégrable |
| Conformité/confidentialité | Documents envoyés à un service d'analyse externe | Traitement local, minimisation, politiques d'accès | Pas de scan externe sans accord explicite | Décision de gouvernance |

## 4. Problèmes souvent rencontrés par les plateformes similaires

### 4.1 Transfert massif et gros fichiers

**Symptômes :** uploads qui échouent à 90 %, timeouts proxy, fichier complet renvoyé après une coupure, serveur API à court de mémoire, réessais qui saturent le lien.

**Ce que les plateformes font déjà :**
- Nextcloud documente l'upload par chunks et les variantes permettant de cibler du stockage objet.
- S3 expose le multipart upload; chaque partie peut être envoyée séparément et une partie échouée peut être renvoyée sans retransmettre les autres.
- Les clients peuvent ajuster les chunks, les timeouts et la concurrence.

**Pourquoi cela ne suffit pas :** un chunk trop gros échoue derrière certains proxies ou sur une connexion faible; trop petit augmente le coût de requêtes; une concurrence trop forte surcharge le client, le VPS ou le réseau. Certains backends S3 n'implémentent pas toutes les extensions de checksum de la même manière.

**Choix AURA :** upload direct vers S3, PUT simple pour petits fichiers, multipart au-delà d'un seuil mesuré, file bornée, reprise par partie et test sous interruptions. Ne pas copier le fichier complet dans la RAM de FastAPI.

### 4.2 Intégrité et compatibilité S3

**Symptômes :** ETag pris à tort pour un hash de fichier, checksum absent après upload, SDK qui rejette une réponse ou ne peut pas vérifier la somme.

**Solutions existantes :** API de checksums S3, checksums de parties, checksum de l'objet entier selon l'algorithme et le mode. AWS explique explicitement que l'ETag d'un objet multipart n'est pas nécessairement le MD5 de l'objet entier.

**Point spécifique à surveiller :** des tickets publics SeaweedFS montrent que la compatibilité des checksums multipart a connu des écarts et des corrections. Un ticket fermé ne suffit pas à prouver que la version utilisée par AURA contient la correction ni que le client envoie les bons headers.

**Choix AURA :** épingler la version, écrire un test d'intégration avec le SDK choisi, vérifier les headers et métadonnées retournés, provoquer un checksum incorrect et vérifier que l'objet n'est pas marqué disponible. Si le backend ne fournit pas le checksum attendu, calculer un SHA-256 en streaming côté client de confiance ou dans un worker isolé et vérifier selon un protocole explicitement documenté; ne jamais prétendre que la vérification serveur a eu lieu si elle n'a pas eu lieu.

### 4.3 Autorisation multi-plateforme

**Symptômes :** accès inter-tenant par identifiant deviné, endpoint admin oublié, clé S3 partagée, URL signée transférée à une personne non prévue.

**Solutions existantes :** identité par application, moindre privilège, contrôle d'accès par ressource, URLs présignées temporaires et journalisation des décisions.

**Ce qui reste difficile :** vérifier que chaque route, tâche de fond, opération de suppression, export et job asynchrone applique le même scope. Les erreurs de logique d'autorisation sont propres à l'application et ne se résolvent pas par S3 seul.

**Choix AURA :** scopes de tenant/application dans toutes les entités et toutes les requêtes; tests négatifs entre applications; URLs signées comme secrets; identité de service différente par environnement.

### 4.4 Ransomware, suppression et récupération

**Symptômes :** sauvegarde accessible avec les mêmes identifiants que la production, clé de chiffrement perdue, restauration jamais testée, suppression propagée aux copies.

**Solutions existantes :** backups hors ligne ou isolés, chiffrement, versioning, immutabilité lorsque disponible, identités séparées, exercices de restauration. CISA recommande des sauvegardes hors ligne chiffrées et des tests réguliers de restauration.

**Ce qui n'a pas de solution magique :** la réplication seule peut répliquer une suppression ou une corruption. L'immutabilité aide, mais implique rétention, coûts et procédures de suppression. Une sauvegarde n'est pas prouvée tant qu'une restauration représentative n'a pas réussi.

**Choix AURA :** destination indépendante, compte/credentials séparés, backup du catalogue et des objets avec procédure cohérente, copie de clé de chiffrement protégée et restauration périodique. Un seul VPS reste un point de défaillance.

### 4.5 Compression, chiffrement client et déduplication

Ces trois techniques ne doivent pas être confondues :

- **Compression** réduit la taille de certains contenus mais consomme du CPU; elle aide peu sur les médias et archives déjà compressés.
- **Chiffrement côté client** peut réduire la confiance nécessaire envers l'opérateur de stockage, mais complique recherche, antivirus, previews, récupération et rotation des clés.
- **Déduplication** économise de l'espace mais peut créer des canaux d'information sur la présence d'un fichier et rendre la suppression/attribution plus complexe.

**Choix AURA :** compression sélective et optionnelle, chiffrement côté client différé jusqu'à conception de la récupération des clés, aucune déduplication globale inter-tenant dans la première version.

## 5. Ce qui est déjà résolu par l'industrie, et ce qui reste sans solution universelle

### Problèmes avec des mécanismes éprouvés

- Transfert sécurisé en transit : TLS/HTTPS.
- Upload par morceaux et reprise : multipart S3 ou protocole resumable.
- Détection de corruption : checksums.
- Autorisation : identités, permissions et URL signées limitées.
- Réduction de la taille : compression adaptée au contenu.
- Prévention de pertes : sauvegarde séparée et restauration testée.
- Gestion des gros lots : queue bornée, retry et idempotence.
- Protection de l'espace : quotas, alertes et lifecycle.

Ces mécanismes ne deviennent « résolus » pour AURA qu'après leur implémentation et leur validation.

### Problèmes qui n'ont pas de réponse universelle

1. **Taille idéale des parties et concurrence idéale :** dépend de la connexion, de la latence, du disque, du CPU, du client et du backend. Il faut benchmarker.
2. **Compression optimale :** dépend du type de données et du rapport CPU/octet économisé.
3. **Confidentialité maximale vs fonctionnalités serveur :** chiffrement client réduit les capacités de recherche et d'analyse serveur.
4. **Déduplication vs confidentialité :** les économies d'espace peuvent introduire des fuites de présence ou complexifier les droits.
5. **Durabilité vs coût et latence :** plusieurs copies et régions coûtent plus cher; une seule machine n'est pas hautement disponible.
6. **Immutabilité vs suppression réglementaire et gestion du cycle de vie :** la rétention doit être conçue et gouvernée.
7. **Analyse antimalware complète :** aucun scanner ne garantit qu'un fichier est inoffensif; l'analyse ajoute des coûts et expose elle-même une surface d'attaque.
8. **Compatibilité S3 :** le terme « compatible S3 » ne garantit pas chaque extension, checksum ou détail d'authentification. Tester les appels exacts.
9. **Récupération de clés :** la protection contre la perte de clé et la protection contre l'accès abusif sont des objectifs en tension; une procédure de récupération contrôlée est nécessaire.
10. **Sécurité absolue :** aucune plateforme ne peut garantir qu'un stockage sera inviolable. L'objectif est de réduire le risque, limiter l'impact et prouver la récupération.

## 6. Ce que nous ne devons pas inventer pour AURA

- Ne pas créer un protocole maison de transfert si S3 multipart répond au besoin.
- Ne pas concevoir notre propre algorithme cryptographique.
- Ne pas introduire une queue distribuée ou des microservices avant que les limites d'un service simple soient mesurées.
- Ne pas mettre un antivirus, OCR ou un convertisseur dans le chemin synchrone de l'upload.
- Ne pas compresser les PDF/images/vidéos par défaut.
- Ne pas utiliser l'ETag comme checksum universel.
- Ne pas lancer des centaines de transferts parallèles sans limite serveur.
- Ne pas déployer des fonctionnalités « S3-compatible » sans tests sur la version SeaweedFS épinglée.
- Ne pas importer des documents importants avant TLS, contrôle d'accès, chiffrement vérifié et restauration indépendante.

## 7. Matrice de priorité AURA

| Priorité | Travail | Preuve attendue |
|---|---|---|
| P0 | Isolation tenant/application et autorisation de toutes les routes | Tests négatifs démontrant le refus inter-tenant |
| P0 | Authentification machine-à-machine et rotation/révocation | Tests de credentials invalides, révoqués et hors scope |
| P0 | Upload-intent, objet pending, commit idempotent | Tests d'upload incomplet, double commit, objet manquant |
| P0 | TLS, SSE-S3 et sauvegarde de la clé | Réponse d'encryption vérifiée et procédure de récupération testée |
| P0 | Backup séparé et restore | Rapport d'une restauration réelle, avec intégrité vérifiée |
| P1 | Upload en masse par manifeste et file bornée | Tests de lot partiellement échoué, retry et cancellation |
| P1 | Multipart et reprise par partie | Tests d'interruption et compatibilité sur la version pinée |
| P1 | Quotas, alertes de capacité, contrôle de concurrence | Tests de limite atteinte sans saturer le VPS |
| P1 | Logs structurés sans URLs signées ni secrets | Tests/inspection des logs de tous les chemins |
| P1 | Quarantaine et politique de types de fichiers | Tests de fichiers invalides et d'archives hostiles |
| P2 | Compression sélective | Benchmark par type montrant un gain net |
| P2 | Chiffrement client optionnel | Modèle de clés, récupération et compatibilité validés |
| P2 | Déduplication par tenant | Threat model, preuve de non-fuite et sémantique de suppression |
| P2 | Réplication/HA multi-nœuds | Architecture, coût et exercices de panne; hors pilote mono-VPS |

## 8. Plan de recherche et de validation restant

1. Inventorier la version SeaweedFS et les SDK/clients réellement épinglés dans le dépôt.
2. Construire une suite de compatibilité couvrant PUT, multipart, abort, HEAD, checksums, SSE-S3, Range et URLs présignées.
3. Tester les mêmes cas avec un ensemble de fichiers synthétiques sans données personnelles.
4. Comparer les performances single PUT/multipart, tailles de partie et concurrence, sous plusieurs profils de réseau.
5. Simuler coupure réseau, expiration d'URL, panne PostgreSQL, panne S3 et disque presque plein.
6. Exécuter des tests d'autorisation inter-tenant sur chaque endpoint et job de fond.
7. Vérifier le processus complet backup + clé + restore; documenter RPO/RTO réalistes après mesure.
8. Transformer chaque échec confirmé en issue avec un test reproductible et un critère de fermeture.
9. Ne promouvoir aucune option expérimentale en production sur la seule base de documentation externe.

## 9. Sources techniques consultées

- AWS — [Uploading and copying objects using multipart upload](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html) : transfert par parties, reprise et finalisation.
- AWS — [Checking object integrity for data uploads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html) : checksums complets/composites et sémantique des ETags multipart.
- Nextcloud — [Chunked file upload](https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/chunking.html) : uploads découpés et contraintes de chunking.
- Nextcloud — [Uploading big files](https://docs.nextcloud.com/server/stable/admin_manual/configuration_files/big_file_upload_configuration.html) : limites serveur, espace temporaire et intégration S3 multipart.
- Nextcloud — [Troubleshooting sync connection closed](https://docs.nextcloud.com/server/stable/admin_manual/desktop/troubleshooting.html) : chunk size, timeouts et erreurs de transfert.
- OWASP — [File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) : validation et défense contre les uploads hostiles.
- CISA — [StopRansomware Guide](https://www.cisa.gov/stopransomware/ransomware-guide) : sauvegardes hors ligne, chiffrement et exercices de récupération.
- SeaweedFS — [S3 API compatibility](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API) : comportement S3 à valider.
- SeaweedFS — [Issue 11401: multipart SHA-256 metadata behavior](https://github.com/seaweedfs/seaweedfs/issues/11401) : exemple d'écart de compatibilité corrigé; vérifier le correctif et le comportement dans la version épinglée d'AURA.
- tus — [Resumable Upload Protocol](https://tus.io/protocols/resumable-upload) : alternative de protocole de reprise, uniquement si AURA ajoute une passerelle compatible.

## Conclusion

Le différenciateur d'AURA ne sera pas de prétendre avoir inventé de nouveaux algorithmes. Il sera de proposer une intégration prévisible et vérifiable : isolation correcte, transferts qui reprennent, intégrité démontrée, clés récupérables, limites de ressources, logs sûrs et restauration testée.

La vraie liste des « problèmes non résolus » d'AURA ne peut être établie qu'en exécutant des tests sur le code, le backend et l'environnement réels. Cette étude fournit le registre initial et les expériences à mener; elle ne remplace pas l'audit ni les tests.
