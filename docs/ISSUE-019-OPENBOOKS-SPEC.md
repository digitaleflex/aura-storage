# Spécification — Intégration OpenBooks (ISSUE-019)

**Statut :** spécification uniquement (P3, futur).  
**Source :** `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE-DIAGRAM.md`, `docs/DECISIONS.md`.

## Contexte

OpenBooks est une plateforme externe de catalogue/droits. L'intégration OpenBooks
permettrait à AURA de s'interconnecter avec OpenBooks pour la gestion de
catalogue et de droits d'accès.

## Principe

- L'intégration est **futur** et **non implémentée**.
- Elle **ne doit jamais conditionner l'accès normal aux données** AURA.
- Les données AURA restent indépendantes : OpenBooks est une surcouche
  optionnelle pour le catalogage et la gestion des droits.

## Périmètre fonctionnel (à définir)

| Fonction | Description |
|----------|-------------|
| Synchronisation de catalogue | Référencer les objets AURA dans le catalogue OpenBooks |
| Gestion des droits | Mapper les capacités AURA (`objects:read`/`write`/etc.) sur les droits OpenBooks |
| Authentification fédérée | Utiliser les identités OpenBooks pour accéder à AURA (futur) |

## Architecture

```
OpenBooks  ↔  AURA API (intégration optionnelle)  →  AURA Storage (SeaweedFS)
```

L'intégration se ferait via des adaptateurs côté AURA qui traduisent les
appels OpenBooks en appels API AURA.

## Sécurité

- Aucun credential OpenBooks stocké en clair dans AURA
- L'intégration ne peut pas escalader les privilèges AURA
- Les opérations OpenBooks sont journalisées dans l'audit log AURA

## Statut

Non implémenté. À réaliser après les gates P0-P1 et selon les besoins métier.

## Fichiers concernés

- `docs/ARCHITECTURE.md` — mention existante
- `docs/DECISIONS.md` — décision d'intégration future
