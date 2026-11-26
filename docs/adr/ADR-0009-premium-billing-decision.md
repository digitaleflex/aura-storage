# ADR-0009 — Modèle premium et facturation (#323)

- Statut: Proposé (décision produit/juridique requise)
- Date: 2026-11-26
- Issue: #323

## État actuel

Contrôle premium par `AURA_PREMIUM_EMAILS` (allow-list manuelle). Pas de facturation.

## Principes de sécurité

- AURA ne stocke jamais de données carte; déléguer à Stripe/équivalent.
- AURA reçoit uniquement des entitlements/grants courts signés.
- Droits d’accès dans le service audiobook; AURA applique les grants.
- Revue juridique/fiscale avant activation.

## Décisions à prendre

- Modèle: abonnement, achat unitaire, ou hybride.
- Périmètre premium: download, offline, HD, catalogue complet, etc.
- Source de vérité des entitlements et TTL des grants.
- Gestion remboursements/résiliation/chargeback.
