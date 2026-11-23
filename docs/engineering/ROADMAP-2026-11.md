# Feuille de route AURA — à suivre (nov. 2026 →)

Date : 2026-11-23. Elle regroupe tout ce qui a été constaté et décidé : l'audit de
l'interface, l'audit du code, le portail public, les transferts, les intégrations
externes. Elle remplace les listes dispersées ; les documents détaillés restent
la référence de chaque lot (liens en fin de fichier).

**Principe : stabiliser avant d'ajouter.** Chaque phase prépare la suivante. Une
phase n'est « terminée » que lorsque sa condition de fin est vraie ET que la CI de
`main` est verte.

## Où l'on en est

| Fait | Preuve |
|---|---|
| CI de `main` réparée (collision de noms de tests, contrat OpenAPI, tests PostgreSQL, e2e) | PR 264, 266 |
| Page Fichiers : fonctions de dossiers restaurées, pastilles de famille de fichiers, synthèse compacte | PR 266, 267 |
| Portail public : filtres repliés, auteurs en liste déroulante, doublons supprimés | PR 268 |
| Transferts : plus de dépassement de largeur, compteur honnête, lignes nettes | PR 269 |
| Coque v3 (barre latérale flottante, recherche globale), audit des 14 écrans | PR 260, 261, 263 |
| Plan d'intégrations externes (clés, CORS, webhooks) rédigé | PR 265 |

## Phase 0 — Filet de qualité (en cours)
*Effort : S. Aucun changement de comportement.*

- Linter Python (ruff) et web (ESLint avec la règle des hooks, qui aurait attrapé le plantage de la page Partages), typage Python (mypy) en avertissement, `.editorconfig`.
- Couverture de tests mesurée (sans seuil au début), audit des dépendances, Dependabot.
- **Fin :** les règles « bloquantes » passent sur `main` ; les règles « avertissement » ont un compte de départ noté, qu'on réduit ensuite.

## Phase 1 — Dette structurelle
*Effort : L. Un morceau par PR, les tests existants servent de filet.*

1. `api/main.py` (5 388 lignes, 115 routes) → routeurs FastAPI par domaine : objets, dossiers, partages, révisions, administration, public. Un domaine par PR.
2. `ObjectsPage.tsx` (un composant de 4 606 lignes) → hooks (données, sélection, suppression en cascade) et composants. ≤ 400 lignes déplacées par PR (paquet N10 du backlog).
3. Parité SQLite / PostgreSQL : tests automatiques de parité (167 méthodes en double dans `db.py` et `db_pg.py`) avant toute idée de couche unique.
4. Gestion d'erreurs : remplacer les 33 `except … : pass` par une journalisation ciblée.
5. Portail public : sortir le HTML, le CSS et le JavaScript des chaînes Python (`api/public_ui.py`, 1 352 lignes) vers des modèles et des fichiers statiques.
- **Fin :** aucun fichier applicatif > 1 500 lignes ; aucune route avec SQL brut ; portail testable sans chaînes géantes.

## Phase 2 — Vitesse des transferts
*Effort : S à M. Démarre en parallèle de la phase 1 (peu de code).*

1. **Mesurer d'abord** (`docs/MEASURE-TRANSFER.md`) : ligne seule en câble, puis AURA, puis `mtr` vers le serveur. Noter le résultat.
2. Test « 1 flux contre 4 flux » dans la page Diagnostic réseau (durée de mesure plus longue que les 5 Mo actuels).
3. Selon la mesure : seuil multipart plus bas (par exemple 32 Mo), HTTP/3 dans Traefik, réglage BBR.
4. Décision serveur : l'emplacement du VPS et sa liaison. Si c'est la route ou la distance, étudier un nœud plus proche des utilisateurs.
- **Fin :** un débit de référence documenté et un objectif chiffré (par exemple « 100 Mo en moins de N secondes depuis telle ligne »).

## Phase 3 — Interface (suite)
*Effort : M à L. Les paquets V1–V9 et B1–B17 du backlog des agents nocturnes.*

1. Transferts : regrouper « En attente » dans une ligne repliable, historique en onglet séparé (la page reste très longue avec des centaines de fichiers).
2. Pages restées à l'ancien style (Corbeille, Paramètres, Aide, Diagnostic) : en-tête de page commun et cartes (note d'audit actuelle 4 à 5 sur 10).
3. Page Fichiers : panneau de détails à droite, actions de ligne au survol, dossiers en cartes.
4. Mobile : barre d'onglets en bas et bouton « Importer » flottant.
5. Identité : police des titres auto-hébergée.
6. Tests visuels exécutés en CI (aujourd'hui ignorés), pour attraper une régression d'apparence.
- **Fin :** chaque écran ≥ 7 sur 10 à l'audit, sans défilement horizontal à 360 px, 1280 px et 1920 px.

## Phase 4 — Portail public : attirer et fidéliser
*Effort : L. Dépend de la décision sur les droits (voir plus bas) et de la fin de la phase 1, point 5.*

1. **Attirer :** catalogue visible sans connexion, une page par livre (aperçu de partage et données structurées), extrait gratuit.
2. **Convertir :** connexion par e-mail (lien magique) en plus de Google ; choix de goûts à la première visite ; mode invité.
3. **Fidéliser :** « Ma liste », recommandations, statistiques d'écoute, alerte de nouveautés.
4. **Écoute avancée :** application installable avec téléchargement hors ligne, mode voiture, marque-pages, partage d'un passage.
5. **Mesurer :** tableau de suivi sans traceur tiers (livres les plus écoutés, abandon par chapitre, passage visite → connexion → écoute).
- **Fin :** un visiteur anonyme peut découvrir un livre et en écouter un extrait ; le tableau de suivi existe.

## Phase 5 — Intégrations externes
*Effort : L. Détail dans `PLAN-INTEGRATIONS-ET-REFONTE.md`. Dépend de la phase 1, point 1 (routeurs).*

1. Clés d'API en libre-service (secret affiché une fois, rotation, révocation, dernière utilisation).
2. API publique sur un domaine dédié, CORS limité aux sites de chaque clé, débit limité par clé. Le portail public a déjà un routeur dédié sur lequel s'appuyer.
3. Webhooks sortants signés, avec relances, protection contre les appels vers le réseau interne, journal et « Rejouer ».
4. Liens de dépôt (un tiers dépose un fichier sans compte) et URLs stables officielles.
5. Documentation, client TypeScript généré, exemples ; lecteur intégrable pour vos autres sites.
- **Fin :** un site externe de test envoie un fichier, le sert et reçoit un webhook, avec une clé limitée.

## Phase 6 — Exploitation et durcissement
*Effort : M. Peut commencer dès la phase 1 pour ses premiers points.*

1. Sauvegarde et restauration réellement testées de bout en bout (`docs/BACKUP-RESTORE.md`) : condition avant d'ouvrir largement.
2. Supervision : Netdata ou Prometheus et Grafana (SeaweedFS expose des métriques), alertes sur disque, débit et erreurs.
3. Politique de sécurité de contenu (CSP) sur le portail (après la phase 1, point 5) et revue de sécurité indépendante avant l'API publique.
4. Déploiement : vérifier automatiquement que la CI de `main` est verte avant de lancer le workflow ; journal des déploiements.
5. Export du journal d'audit ; usage et alertes par clé d'API.
- **Fin :** une restauration chronométrée réussie ; une alerte reçue lors d'un incident simulé.

## Ordre conseillé

```text
Phase 0 ──► Phase 1 ───────────────► Phase 4 ──► Phase 5
   │          ▲  (routeurs, portail)      ▲           ▲
   ├──► Phase 2 (mesures, en parallèle)   │           │
   ├──► Phase 3 (interface, en continu)───┘           │
   └──► Phase 6 (sauvegarde, supervision) ────────────┘
```

Les phases 2, 3 et 6 avancent en parallèle de la phase 1 ; les phases 4 et 5 attendent
les découpages de la phase 1.

## Règles de conduite (inchangées)

- Une PR par paquet, petite et relisible, avec test ; aucun test supprimé ni ignoré.
- Fusion seulement quand **toutes** les vérifications sont vertes : `unit-tests`, `e2e`, `config`, `api-postgres` et, une fois ajoutés, les contrôles de qualité.
- Aucun déploiement sans ordre explicite du propriétaire ; DNS et ouverture de ports : actions du propriétaire.
- Les agents nocturnes gardent les paquets d'interface ; les phases touchant `api/` se font en séances supervisées.

## Décisions à prendre par le propriétaire

| Décision | Débloque |
|---|---|
| Les livres peuvent-ils être écoutés librement, ou seulement par les membres ? Qui sont les visiteurs ? | Phase 4 |
| Où est le VPS, quelle est sa liaison ? Un nœud en Europe est-il acceptable ? | Phase 2 |
| Domaine de l'API publique (par exemple `api.<domaine>`) | Phase 5 |
| Service d'envoi d'e-mails pour les liens de connexion et les alertes | Phase 4 |
| Respect du RGPD pour les statistiques d'écoute (consentement, durée de conservation) | Phase 4 |

## À ne pas faire

- Tout réécrire d'un bloc : on découpe et on teste par étapes.
- Remplacer SeaweedFS ou changer de base de données sans mesure qui le justifie.
- Ouvrir l'API publique avant la revue de sécurité et la restauration testée.
- Ajouter des traceurs tiers sur le portail public.

## Documents liés

`PLAN-INTEGRATIONS-ET-REFONTE.md`, `UI-PLAN-PRO-2026-11.md`, `UI-AGENTS-BACKLOG.md`,
`../MEASURE-TRANSFER.md`, `../NETWORK-AND-THROUGHPUT-PLAN.md`,
`../BACKUP-RESTORE.md`, `../PUBLIC-PORTAL.md`.
