# Decision — Sauvegarde independante (issue #9)

## Decision (2026-10-21)
Differer la mise en place d'une sauvegarde independante et du test de restauration.

## Justification
- Le pilote actuel est en phase de validation ; la sauvegarde independante sera mise en place avant la mise en production.
- Les donnees du pilote sont de test ; le risque est acceptable a ce stade.
- La procedure est documentee dans docs/BACKUP-RESTORE.md et prete a etre executee.

## Conditions de reprise
- Avant toute mise en production avec des donnees reelles.
- Avant l'import de fichiers clients (PDF/audio).

## Statut
Differre. Issue #9 reste ouverte (rappel).
EOF