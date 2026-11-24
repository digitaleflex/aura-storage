# Proposition de projet — AURA Culture

**Portail unique pour lire, écouter, apprendre, publier et échanger**

- **Date :** 24 novembre 2026
- **Statut :** proposition à arbitrer
- **Objectif :** étendre les activités liées au livre sans multiplier les sites, les comptes et les interfaces.

## 1. Résumé exécutif

AURA peut évoluer d'une plateforme de stockage et de partage vers une **médiathèque culturelle ouverte**, dont le portail public deviendrait le point d'entrée unique.

La recommandation principale est de **ne pas empiler Calibre-Web, Kavita, Komga, WordPress et un réseau social comme des sites indépendants**. Ces outils peuvent rester des services spécialisés en arrière-plan, mais le visiteur doit disposer :

- d'une seule adresse ;
- d'une seule recherche ;
- d'un seul compte ;
- de collections transversales ;
- d'une information claire sur les droits et les conditions d'accès ;
- d'une expérience cohérente sur ordinateur et mobile.

Le projet peut se résumer ainsi :

> **AURA Culture est le portail de découverte et d'accès aux ressources culturelles et éducatives d'AURA. Il réunit livres, audio, articles, cours et créations, tout en laissant à chaque contenu ses règles de droits et d'accès.**

L'extension doit être progressive : consolider le portail actuel, puis enrichir les usages, et seulement ensuite ajouter des formats ou des fonctions avancées.

**MVP recommandé :** consolider l'audio et la consultation PDF, les droits, la progression et les collections derrière une recherche et un compte unifiés. La presse, les créations, la communauté, l'OPDS, l'IA et la monétisation viennent ensuite, après validation des accès, des contenus, des coûts et de l'exploitation.

## 2. Diagnostic et principes directeurs

### État réel du dépôt AURA

Analyse statique du dépôt au 24 novembre 2026. Les fonctionnalités ci-dessous sont présentes dans le code ; leur acceptance de production n'est pas présumée. Les nombreuses modifications locales non commitées doivent être revues et testées avant d'être considérées comme livrées.

| Couche | Ce qui existe | Limite à connaître |
|---|---|---|
| **AURA Storage** | Stockage S3/SeaweedFS, uploads, transferts, intégrité, partage, packs, révisions, administration, aperçus image/PDF/audio/vidéo, HLS 720p et sous-titres | Sauvegarde/restauration implémentées avec E2E local documenté, mais restauration indépendante hors site, reboot réel et acceptance production restent à valider ; le worker d'import actuel est encore un stub |
| **Portail public historique** | Catalogue et extrait anonymes ; compte public pour favoris/progression ; lecteur avancé, PWA, hors ligne et statistiques administrateur | Écoute complète et hors ligne sont premium par défaut dans le working tree, via un gate manuel local et non un paiement ; recherche filtrée en mémoire, progression simple en `last-write-wins`, profil privé et non social |
| **Service `audiobook/`** | Catalogue éditorial, droits, territoires, entitlements, décisions d'accès auditables, progression versionnée, appareils, recommandations et export JSON partiel | Pas de frontend public ni route de production ; identités distinctes ; administration encore liée à un token bootstrap ; l'export exclut progression, historique, entitlements et décisions d'accès |
| **Formats et usages absents** | — | Lecteur EPUB, modèle de presse, communauté, dépôts de créations publiques, OPDS, IA générative et paiement ne sont pas implémentés |

Repères : [README](../README.md), [portail public](PUBLIC-PORTAL.md), [roadmap du portail](PUBLIC-PORTAL-ROADMAP.md), [frontière audiobook](audiobook/README.md), [état du lot 2 audiobook](audiobook/11-lot2-implementation.md) et [plan d'intégration](engineering/PLAN-INTEGRATIONS-ET-REFONTE.md).

**Conséquence pour le projet :** il ne s'agit pas de créer un portail à partir de zéro, mais de consolider trois couches complémentaires derrière une expérience unique. Le compte unique, la recherche transversale et la communauté sont des objectifs, pas des fonctionnalités déjà acquises. La PWA et le hors ligne de base existent déjà ; leur consolidation et leur adaptation aux droits restent nécessaires.

Le cache audio hors ligne peut survivre à la déconnexion et à la suppression du compte. Aucun bail de contenu local ni mécanisme de révocation de cette copie n'est actuellement implémenté.

### Chantiers prioritaires avant l'extension

Le premier volet média a été corrigé ; voir [le compte rendu du Lot 0](LOT0-MEDIA-ACCESS.md).

- **Corrigé :** `GET /a/{token}` est routé par Traefik sur les domaines applicatif et public, avec fallback nginx.
- **Corrigé :** HLS et WebVTT appliquent désormais la même authentification, le même contrôle premium et la même liste de slugs restreints que `/m/{slug}`.
- **Corrigé :** la durée par défaut d'un grant passe à 15 minutes et l'URL S3 émise ne peut pas dépasser la durée restante du grant.
- **Limite résiduelle :** une URL S3 déjà émise reste valide jusqu'à son expiration ; les fichiers téléchargés ou mis en cache restent accessibles.
- **À faire :** valider une restauration indépendante hors site et la persistance après redémarrage réel du VPS.
- **À faire :** remplacer le worker d'import stub par un traitement effectif des lots.
- **À faire :** aligner les identités, les catalogues et les rôles sans réutiliser les sessions administrateur comme comptes publics.
- **À faire :** valider séparément l'intégration de l'adaptateur audiobook avec `/a/{token}`.

### Analyse de la piste Calibre-Web + Plesk

Plesk était une piste générique dans la discussion initiale ; il ne fait pas partie de l'infrastructure AURA retenue. Le couple **Calibre-Web Automated + règles de proxy Docker de Plesk** reste une base possible pour une bibliothèque de livres sur un autre environnement :

- exposer le conteneur uniquement sur `127.0.0.1` réduit l'exposition directe ;
- Plesk centralise le domaine, HTTPS et le routage ;
- les volumes séparent configuration, ingestion et bibliothèque ;
- Calibre-Web apporte déjà recherche, notices, lecteur et téléchargement.

Il faut cependant corriger ou préciser plusieurs points avant une ouverture publique :

- `crocodilestick/calibre-web-automated` correspond à une implémentation communautaire ; vérifier sa provenance et ne pas confondre Calibre, le logiciel de bureau, avec les projets de diffusion web.
- Le tag `latest` nuit à la reproductibilité. Il faut figer une version testée ou une empreinte d'image et prévoir les mises à jour.
- `PUID=1000` et `PGID=1000` doivent correspondre au propriétaire réel des répertoires montés.
- Le chemin `/var/www/bibliotheque` doit réellement se trouver sur la partition de 1 To, et non sur le disque système.
- Les identifiants par défaut doivent être changés avant toute exposition ; l'administration doit rester protégée.
- Une bibliothèque ouverte ne suffit pas à créer un portail culturel unifié : recherche, identité, collections et communauté restent à concevoir.
- Les sources citées ne placent pas automatiquement tous leurs contenus dans le domaine public. Chaque fichier, chaque édition et chaque couverture doivent être vérifiés.
- Un miroir complet peut représenter un téléchargement massif : il faut étudier son volume, les conditions de redistribution et la bande passante avant de lancer l'import.
- Des sauvegardes hors du VPS, une supervision et une procédure de retrait sont indispensables.

**Décision recommandée :** conserver Calibre-Web Automated comme outil optionnel de bibliothèque ou d'ingestion, mais faire d'AURA le portail visible. Calibre-Web, Kavita et Komga ne figurent pas dans le dépôt : ce sont des options externes à évaluer, pas des briques déjà intégrées. Cette approche évite de remplacer un outil complet par plusieurs interfaces concurrentes.

### Ce qui doit guider le projet

1. **Un portail, pas une collection de sites.** Les routes peuvent être séparées, mais l'identité visuelle, la navigation et le compte restent communs.
2. **Les droits avant le volume.** Mieux vaut quelques centaines de ressources vérifiées que des milliers de fichiers importés sans preuve de diffusion.
3. **Les notices peuvent être publiques ; les fichiers ne le sont pas nécessairement.** Une notice visible peut exiger un compte ou une autorisation pour la lecture, l'écoute ou le téléchargement.
4. **Le stockage privé reste isolé.** Aucun document du coffre-fort AURA ne doit apparaître dans le catalogue public par défaut.
5. **La simplicité avant l'IA.** Une recherche plein texte, des filtres et des collections curatées apportent déjà beaucoup de valeur.
6. **L'accessibilité fait partie du MVP.** Navigation clavier, contraste, lecteur utilisable au clavier, transcriptions et alternatives textuelles ne sont pas des options de fin de projet.

## 3. Le portail proposé

### Nom de travail

**AURA Culture**, avec la signature :

> Lire, écouter, apprendre, créer et partager.

Ce nom de travail pourra être ajusté pour respecter l'identité de marque définie dans le dépôt.

### Les six espaces du portail

| Espace | Contenu et usages | Accès depuis le portail |
|---|---|---|
| **Médiathèque** | Livres EPUB/PDF, audiobooks, textes courts | Recherche, lecture, écoute, téléchargement autorisé |
| **Collections** | Sélections thématiques, parcours, listes de lecture | Pages publiques et listes personnelles |
| **Revue** | Articles, entretiens, critiques, dossiers | Lecture web, flux RSS, abonnement newsletter |
| **Savoir** | Supports de cours, tutoriels, conférences | Consultation, progression, ressources téléchargeables |
| **Cercle** | Clubs de lecture, événements, échanges modérés | Inscription, calendrier, contributions |
| **Atelier** | Créations personnelles et dépôts de contributeurs | Brouillon privé, validation, publication |

Tous ces espaces utilisent le même en-tête, la même recherche et le même profil. Un livre peut appartenir à une collection, inspirer un article, alimenter un club et être recommandé avec son audiobook.

**Périmètre pédagogique du MVP :** l'espace Savoir commence par des ressources documentaires et des parcours éditoriaux ordonnés. Les exercices, évaluations et parcours de formation complètent la progression. Au MVP, « progression » signifie dernière ressource ouverte, position de lecture et statut consulté/terminé ; il ne s'agit pas encore d'un LMS.

## 4. Parcours utilisateurs

### Visiteur anonyme

1. Recherche une œuvre ou découvre une collection.
2. Consulte une notice avec langue, format, source, licence et accessibilité.
3. Lit un extrait ou écoute un aperçu selon les autorisations.
4. Comprend clairement ce qui nécessite un compte.

### Lecteur ou auditeur

1. Crée un compte ou se connecte.
2. Enregistre des favoris, une liste de lecture et sa progression.
3. Accède aux ressources autorisées, y compris sur mobile.
4. Reprend sa lecture ou son écoute depuis un autre appareil.

### Bibliothécaire ou curateur

1. Importe des ressources dans une zone d'attente.
2. Vérifie la provenance, la licence, les métadonnées et les fichiers.
3. Publie dans le catalogue et crée une collection.
4. Corrige une notice ou retire une ressource si nécessaire.

### Créateur ou membre de la communauté

1. Dépose un texte, un audio ou une couverture.
2. Déclare ses droits et accepte les règles de publication.
3. Suit la validation par un modérateur.
4. Publie dans l'Atelier sans exposer ses brouillons.

## 5. Architecture cible

```text
Visiteurs
   |
   | HTTPS — un seul edge public
   v
Traefik + nginx — infrastructure custom AURA
   |
   +--> Portail AURA Culture
   |      |-- pages de découverte
   |      |-- lecteurs web
   |      `-- compte et collections
   |
   +--> API de portail / BFF
   |      |-- recherche et catalogue unifiés
   |      |-- orchestration des accès
   |      `-- médias protégés
   |
   +--> Service métier audiobook
   |      |-- droits et territoires
   |      |-- entitlements
   |      `-- progression et appareils
   |
   +--> Services d'arrière-plan
          |-- import et validation
          |-- extraction de métadonnées
          |-- transcription et indexation
          |-- tâches programmées
          |-- sauvegardes
          `-- adaptateurs vers outils spécialisés si nécessaire
                     |
                     v
              Métadonnées + stockage objet/local
```

### Décisions techniques recommandées

- **Conserver l'edge HTTPS custom.** Le déploiement AURA utilise Traefik et nginx. Plesk n'est pas utilisé et ne doit pas être ajouté au chemin public ; toute configuration Plesk relève d'un environnement externe distinct.
- **Conserver une origine applicative unique pour le visiteur.** Par exemple : `/livres`, `/audio`, `/articles`, `/collections` et `/opds`. En interne, préserver des préfixes distincts pour AURA Storage et le service culturel/audiobook, car leurs API utilisent aujourd'hui des routes similaires.
- **Séparer métadonnées et fichiers.** La base contient les notices et les droits ; les fichiers restent dans le stockage objet ou local.
- **Utiliser des files de travail pour les opérations longues.** Imports, extraction de couvertures, transcription et maintenance ne doivent pas bloquer les requêtes web.
- **Prévoir des adaptateurs, pas des dépendances rigides.** Calibre-Web Automated peut servir à l'ingestion et à la gestion de la bibliothèque. Kavita ou Komga ne sont à intégrer que si une capacité précise le justifie.
- **Ne pas dupliquer les interfaces.** Si un service externe possède déjà un lecteur ou un flux OPDS utile, l'intégrer comme composant ; sinon, utiliser le portail AURA.

**Source de vérité cible :** le portail AURA Culture présente le catalogue unifié et orchestre l'expérience ; le service `audiobook/` reste autoritatif pour les droits, territoires, entitlements et progression audio ; AURA Storage stocke et diffuse les fichiers après décision d'accès. Une couche d'identité doit relier progressivement les comptes publics et les auditeurs, sans fusionner les rôles administrateur.

Si Calibre-Web reste utilisé, il conserve sa bibliothèque technique et son interface d'administration privée ; un connecteur synchronise les ressources validées vers le portail. Les comptes Calibre-Web ne deviennent pas les comptes publics, et deux systèmes ne doivent jamais décider séparément de la visibilité d'un même fichier.

## 6. Modèle de contenu unifié

Le catalogue doit distinguer au moins les notions suivantes :

| Objet | Rôle |
|---|---|
| **Œuvre** | Regroupe les éditions, traductions et formats d'un même contenu |
| **Ressource** | Livre, audiobook, article, cours, vidéo ou création |
| **Fichier** | Format, langue, taille, empreinte de contrôle et emplacement de stockage |
| **Source** | Origine du fichier, URL, date d'import et identifiant externe |
| **Droits** | Licence, territoire, attribution, preuve et restrictions éventuelles |
| **Publication** | État, visibilité et conditions d'accès de la ressource |
| **Collection** | Sélection curatoriale ordonnée et présentée au public |
| **Droit d'accès** | Autorisation effective d'un utilisateur pour une action donnée |

Une même œuvre peut donc être disponible en lecture et en écoute, avec des droits différents. Le moteur d'autorisation doit vérifier séparément les actions `view`, `stream`, `download` et `share`.

## 7. Fonctionnalités par ordre de priorité

Le tableau ci-dessous est la référence unique de priorisation. Le MVP correspond aux lots 0 à 2 ; la V1 aux lots 1 à 4, selon les dépendances.

| Fonctionnalité | Version | Lot | Dépendance principale |
|---|---|---|---|
| Portail, recherche transversale, filtres et notices | MVP | 1 | Catalogue et règles de publication |
| Droits, visibilité et autorisations `view`/`stream`/`download`/`share` | MVP | 0 puis 1 | Modèle d'accès existant |
| Navigation anonyme et lecteurs accessibles | MVP | 0 puis 1 | Hébergement sécurisé des médias |
| Compte, listes personnelles et progression simple | MVP | 1 | Authentification et profil |
| Tableau de bord curateur | MVP | 1 | Rôles et permissions |
| Import manuel, quarantaine et vérification des droits | MVP | 2 | Stockage et file de travail |
| Connecteurs limités et déduplication | V1 | 2 | Procédure d'import validée |
| Indexation des transcriptions | V1 | 2 | Transcription et droits d'indexation |
| Revue, articles et podcasts | V1 | 3 | Modèle de ressource unifié |
| Clubs de lecture et collections contributives | V1 | 3 | Comptes et modération |
| Atelier de créations avec modération éditoriale | V1 | 3 | Déclaration de droits et quarantaine |
| OPDS et adaptation des modes hors ligne aux droits ; consolidation de la PWA existante | V1 | 4 | Lecteurs et autorisations stabilisés |
| Recommandations par règles | V1 | 4 | Catalogue et statistiques minimales |
| Interface multilingue | V1 | 4 | Contenus et métadonnées traduisibles |
| Cours structurés et exercices | V2 | Lot distinct | Modèle pédagogique et accessibilité |
| Liens vers des vidéos externes | V2 | Lot distinct | Vérification des droits et des liens |
| Recherche sémantique et assistant de lecture | V2 | Lot distinct | Corpus autorisé, confidentialité et budget |
| Dons, adhésion ou financement transparent | V2 | Lot distinct | Gouvernance et obligations comptables |
| API publique documentée et partenariats | V2 | Lot distinct | Contrat d'API et limites d'usage |

### À exclure au départ

- Un réseau social complet.
- L'hébergement de vidéos HD sur le même volume de 1 To.
- Les dépôts anonymes sans validation.
- La promesse que tout le catalogue sera téléchargeable.
- L'utilisation de contenus pour entraîner un modèle sans analyse juridique et autorisation appropriée.

## 8. Sources et politique de droits

Les sources citées dans la discussion sont des pistes, pas un blanc-seing juridique.

| Source | Utilisation envisagée | Vérification nécessaire |
|---|---|---|
| Project Gutenberg | Romans et textes du domaine public | Statut par pays, mention de la source et conditions de redistribution |
| Wikisource | Textes et transcriptions libres | Licence de l'édition exacte, attribution et conditions de partage |
| OpenStax | Manuels universitaires | Licence de chaque ouvrage, attribution et éventuelles restrictions |
| Érudit | Articles et publications académiques | Autorisation de diffusion propre à chaque document |
| Framabook et publications libres | Culture numérique, logiciel libre | Licence de l'édition et autorisation de redistribution |
| Créations personnelles | Œuvres originales des contributeurs | Déclaration de droits et accord de publication |

À appliquer systématiquement :

1. Enregistrer la preuve de licence ou de domaine public.
2. Conserver l'attribution exigée.
3. Distinguer le statut juridique du texte, de l'édition, de la couverture et de l'audio.
4. Prévoir un mécanisme de signalement et de retrait.
5. Ne pas suggérer d'affiliation officielle avec une source externe.
6. Respecter les conditions techniques des sources : fréquence d'accès, robots, authentification et redistribution.

## 9. Sécurité et exploitation

- Aucun accès direct aux conteneurs ou au stockage depuis Internet.
- Authentification forte pour les comptes et séparation des rôles curateur/modérateur/administrateur.
- URL de média à durée limitée et révocable lorsque le fichier n'est pas public.
- Limitations de débit sur la recherche, les imports et les téléchargements.
- Quarantine et analyse des fichiers déposés.
- Isolation du coffre-fort AURA et du catalogue public.
- Sauvegardes testées, idéalement hors du VPS ; un seul disque de 1 To ne constitue pas une sauvegarde.
- Journalisation sans mots de passe, jetons ou données sensibles.
- Procédure documentée pour signalement, correction, retrait et restauration.
- Procédure de réclamation pour contenu contrefaisant ou illicite, avec personne responsable, traçabilité et délai de traitement.
- Politique de confidentialité et gestion des comptes : base légale, finalités, durée de conservation, export et suppression des données ; appliquer le RGPD ou la réglementation locale pertinente.
- Consentement explicite pour les statistiques non essentielles et minimisation des données personnelles.
- Règles spécifiques pour les mineurs si le portail leur est destiné : âge autorisé, participation encadrée et limites de publication.
- Définition d'objectifs de reprise après incident et de perte de données maximale acceptable, puis tests de restauration.

### Accessibilité et protection des médias

- Cible d'accessibilité : **WCAG 2.1 niveau AA**.
- Recette au clavier, avec lecteur d'écran et sur mobile avant chaque version importante.
- Couvertures décrites, transcriptions pour l'audio et alternatives aux médias visuels.
- Distinguer contrôle d'accès et protection contre la copie : un EPUB, un PDF ou un fichier audio autorisé au téléchargement reste techniquement copiable. Ne pas promettre de DRM sans dispositif adapté.

## 10. Stockage : ordres de grandeur

Un disque de 1 To convient bien à une grande bibliothèque de livres numériques. Il l'est beaucoup moins pour une vidéothèque.

| Contenu | Estimation indicative | Conséquence |
|---|---|---|
| 100 000 livres à 1,5 Mo | Environ 150 Go | Réaliste, hors copies et marge |
| 1 000 heures d'audio à 100 Mo/h | Environ 100 Go | Réaliste si les transcodages sont maîtrisés |
| 200 heures de vidéo à 1 Go/h | Environ 200 Go | Possible, mais coûteux en bande passante |
| 200 heures de vidéo HD à 4 Go/h | Environ 800 Go | Peu prudent sur un VPS unique |

Il faut réserver de l'espace pour les fichiers temporaires, les versions, les index et la croissance. Pour la vidéo, commencer par des liens externes ou des diffusions spécialisées.

La capacité disque ne suffit pas à valider l'hébergement. Avant d'ajouter de l'audio ou de la vidéo, mesurer sur le VPS :

- CPU et mémoire pendant la lecture simultanée ;
- entrées/sorties disque pendant les imports et les sauvegardes ;
- bande passante sortante et pics de trafic ;
- temps de réponse à travers Traefik et nginx ;
- durée et coût d'une restauration complète hors site.

Un test de charge avec un petit lot représentatif doit précéder toute promesse de capacité.

## 11. Feuille de route proposée

Les durées sont indicatives et supposent un développeur principal disponible. Le travail éditorial et de vérification des droits peut devenir le facteur limitant.

- **MVP, lots 0 à 2 :** environ 9 à 14 semaines de développement, avec le catalogue pilote préparé en parallèle.
- **V1, lot 3 inclus :** environ 14 à 22 semaines, auxquelles s'ajoute la charge continue de modération.
- **Lot 4 et V2 :** à budgéter séparément après mesure des usages.

### Lot 0 — Consolider

**Charge indicative :** 2 à 3 semaines.

**Objectif :** rendre le portail actuel fiable avant de l'étendre.

- Revoir, tester et intégrer les modifications locales non commitées.
- Router correctement les accès par autorisation, protéger HLS et les sous-titres, et documenter les limites de révocation.
- Valider sauvegarde, restauration et persistance après redémarrage.
- Tester les parcours anonymes et connectés.
- Inventorier les comptes, progressions, packs et objets à migrer.
- Définir les conventions de notice, de licence et de collection.
- Aligner les documents de statut avec le code.

**Critère de sortie :** les tests démontrent l'absence d'accès non autorisé, la restauration est prouvée et les règles de publication sont écrites.

### Lot 1 — Découvrir

**Charge indicative :** 4 à 6 semaines.

**Objectif :** offrir une expérience unifiée autour du catalogue existant.

- Accueil éditorial et recherche transversale sur l'audio et les documents PDF.
- Filtres et fiches de ressources avec droits et disponibilité.
- Branchement du frontend sur le service audiobook pour les droits et la progression.
- Collections publiques et listes personnelles.
- Compte public et rapprochement progressif des identités auditeur.
- Tableau de bord curateur minimal.

**Critère de sortie :** un visiteur trouve, consulte et enregistre une ressource audio ou PDF depuis une seule interface. La lecture EPUB complète n'est pas incluse dans ce lot.

### Lot 2 — Importer et publier

**Charge indicative :** 3 à 5 semaines, hors préparation éditoriale du lot pilote.

**Objectif :** alimenter le portail de manière répétable et traçable.

- Traitement réel des lots d'import, en remplacement du worker stub actuel.
- File d'import et zone d'attente.
- Formulaire de vérification des droits et provenance.
- Déduplication et contrôle des fichiers.
- Publication, correction et retrait.
- Premier connecteur limité à une source juridiquement et techniquement maîtrisée.

**Critère de sortie :** un lot pilote de 100 à 300 ressources peut être importé, vérifié et publié avec sa provenance.

### Lot 3 — Animer

**Charge indicative :** 5 à 8 semaines, plus une charge récurrente de modération.

**Objectif :** transformer le catalogue en lieu de vie.

- Revue et articles.
- Clubs de lecture et agenda.
- Commentaires ou avis modérés.
- Dépôt de créations dans l'Atelier.
- Partage de collections.

**Critère de sortie :** un membre peut contribuer sans exposer de contenu privé ni contourner la modération.

### Lot 4 — Enrichir et automatiser

**Charge indicative :** 4 à 8 semaines par groupe de fonctionnalités retenu.

**Objectif :** ajouter de la variété sans fragiliser la plateforme.

- OPDS et adaptation des modes hors ligne aux droits ; consolidation de la PWA installable existante.
- Mise en avant des recommandations déterministes déjà présentes dans le service audiobook.
- Consommation des événements et statistiques d'usage unifiées.
- Nouveaux connecteurs après validation du premier.
- Préparation, sans engagement, des options vidéo et modèle économique.

**Critère de sortie :** chaque fonction avancée démontre un usage mesurable et reste exploitable avec les ressources du VPS.

## 12. Organisation du projet

### Équipe minimale

- **Développement :** portail, API, intégrations et lecteurs.
- **Contenus et droits :** sélection, notices, licences et modération.
- **Produit/UX :** parcours, accessibilité et priorisation.
- **Exploitation :** déploiement, sauvegardes, supervision et sécurité.

Une même personne peut cumuler plusieurs rôles, mais la curation ne doit pas être traitée comme un simple lot d'import technique.

### Livrables

1. Une charte éditoriale et une politique de droits.
2. Un portail unifié et son catalogue pilote.
3. Une procédure d'import et de publication.
4. Un espace curateur et un processus de modération.
5. Une documentation d'exploitation et de restauration.
6. Une feuille de route mesurable pour la Revue, le Cercle et l'Atelier.

## 13. Indicateurs de réussite

Suivre des indicateurs utiles, sans surveillance invasive. Les statistiques non essentielles nécessitent un consentement ; les événements doivent être minimisés, pseudonymisés lorsque c'est pertinent et conservés pendant une durée définie :

- ressources publiées avec provenance complète ;
- part du catalogue consultable en français ;
- recherches abouties et recherches sans résultat ;
- taux d'ouverture des notices ;
- lectures, écoutes et téléchargements autorisés ;
- reprise de progression sur un second appareil ;
- délai entre dépôt et validation ;
- contenus retirés et délai de traitement des signalements ;
- temps de réponse du portail et taux d'échec des imports ;
- coût de stockage et de bande passante par type de contenu.

## 14. Décisions à prendre avant le développement

1. **Identité :** définir comment relier comptes publics, auditeurs et comptes créateurs sans fusionner les rôles privilégiés.
2. **Public ou communauté ?** Définir ce qui reste anonyme et ce qui exige un compte.
3. **Héberger ou référencer ?** Choisir les formats réellement stockés sur le VPS et ceux accessibles par lien.
4. **Priorité des espaces :** Médiathèque et Revue d'abord, ou Médiathèque et Cercle d'abord ?
5. **Contenus du pilote :** sélectionner les sources, les langues et le volume initial.
6. **Gouvernance :** identifier qui valide les droits et qui modère les contributions.
7. **Budget d'exploitation :** inclure sauvegardes hors site, bande passante et maintenance.

## 15. Recommandation finale

Construire d'abord **une médiathèque unifiée, crédible et bien organisée**, puis ajouter la Revue, le Cercle et l'Atelier comme des espaces du même portail.

Le bon ordre est :

> **Sécuriser → unifier → documenter les droits → automatiser l'import → enrichir les usages → ajouter l'IA ou la monétisation si nécessaire.**

Cette approche limite la duplication technique, protège les contenus et donne à AURA une identité propre sans dépendre d'une multiplication d'applications disjointes.
