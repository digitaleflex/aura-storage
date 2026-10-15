# Pacte d'autonomie — agent AURA (2026-10-15, accepté par l'opérateur)

## Voie 1 — Autonome, sans demander

Lecture, audit, code, tests offline (`AURA_API_DB=:memory:`, S3 fictif),
documentation, commits locaux, commentaires GitHub en lecture seule,
`git diff --check`, vérifications non destructives.

## Voie 2 — Autonome dès ressources fournies

Parité PostgreSQL sur base **jetable** (`AURA_TEST_PG_DSN` fourni par
l'opérateur), smoke tests S3 pilote : une autorisation de principe suffit,
sans validation de chaque commande. Jamais la base ni les buckets réels.

## Voie 3 — Feu vert explicite requis, toujours

Push, merge, écriture base/S3 réels, Docker/services/hôte, SSH/réseau/DNS/
pare-feu/certificats, redémarrages, secrets (affichage, rotation, commit),
fermeture d'issues, déploiements.

## Garde-fous permanents

- Aucune donnée originale importée avant HTTPS + auth + SSE-S3 + persistance
  + restauration indépendante prouvée (critères AGENTS.md inchangés).
- Toute écriture hors `:memory:`/fictif est annoncée avant exécution.
- En cas de doute sur le caractère destructif : on s'arrête et on demande.
