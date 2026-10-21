# Décision — Better Auth + Google OAuth (#59)

## Décision (2026-10-21)
**Différer** l'intégration de Better Auth + Google OAuth.

## Justification
- Le pilote actuel utilise l'authentification admin-only (session cookie + CSRF) via `/api/v1/login`.
- Aucun besoin utilisateur externe à ce stade.
- Intégrer Better Auth maintenant augmenterait la surface d'attaque et la complexité sans valeur immédiate.

## Conditions de reprise
- Besoin d'authentification utilisateur final (OAuth social) confirmé.
- Décision de périmètre documentée et approuvée.
- Branche `feat/ui-shell-clean` réévaluée à ce moment.

## Statut
Différé. Issue #59 fermée comme décision prise.
