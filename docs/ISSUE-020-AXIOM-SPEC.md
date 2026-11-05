# Spécification — Intégration Axiom (ISSUE-020)

**Statut :** spécification uniquement (P3, futur).  
**Source :** `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE-DIAGRAM.md`.

## Contexte

Axiom est une plateforme de supervision/opérations via API versionnée. L'intégration
Axiom permettrait à AURA d'exposer des métriques et des événements d'exploitation
vers Axiom.

## Principe

- L'intégration est **futur** et **non implémentée**.
- Elle **ne doit jamais conditionner l'accès normal aux données** AURA.
- Axiom est une couche de supervision optionnelle, pas une dépendance critique.

## Périmètre fonctionnel (à définir)

| Fonction | Description |
|----------|-------------|
| Métriques | Exposer les métriques AURA (objets, stockage, transferts) vers Axiom |
| Événements | Envoyer les événements d'audit AURA vers Axiom |
| Supervision | Surveiller la santé de la stack AURA depuis Axiom |

## Architecture

```
AURA API  →  Axiom API (versionnée)  →  Axiom Platform (supervision/opérations)
```

L'intégration se ferait via des adaptateurs côté AURA qui envoient des
métriques et événements vers l'API Axiom.

## Sécurité

- Aucun credential Axiom stocké en clair dans AURA
- L'intégration est en lecture seule sur les données AURA (pas d'écriture)
- Les données sensibles (secrets, tokens, URLs présignées) ne sont jamais
  envoyées à Axiom

## Statut

Non implémenté. À réaliser après les gates P0-P1 et selon les besoins d'exploitation.

## Fichiers concernés

- `docs/ARCHITECTURE.md` — mention existante
- `docs/OBSERVABILITY.md` — métriques existantes
