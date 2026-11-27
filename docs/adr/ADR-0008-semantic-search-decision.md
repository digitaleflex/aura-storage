# ADR-0008 — Recherche sémantique / conversationnelle (#321)

- Statut: Proposé (décision produit requise)
- Date: 2026-11-26
- Issue: #321

## Contexte

`api/portal_search.py` fait de la traduction de motifs FR en filtres. Besoin éventuel: synonymes, goûts, conversation multi-tours.

## Options

| Option | Avantages | Risques | Données |
|---|---|---|---|
| A. Local enrichi (synonymes/tags/règles) | simple, privé, déterministe | pertinence limitée | reste local |
| B. Embeddings locaux/self-hosted | meilleure pertinence, privé | coût infra/maintenance | reste local |
| C. Service externe LLM/recherche | meilleure UX | fuite données, coût, dépendance | nécessite consentement/contrat |

## Recommandation initiale

Commencer par **A**, mesurer sur un jeu de requêtes représentatives, puis évaluer B. Ne pas envoyer de données privées à un tiers sans consentement explicite et revue.

## Critères d’acceptation à implémenter quand décidé

- Mesure avant/après pertinence.
- Repli sur recherche actuelle.
- Journalisation/audit des requêtes anonymisées.
