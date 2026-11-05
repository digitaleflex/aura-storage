# Spécification — Adaptateur FTPS (ISSUE-018)

**Statut :** spécification uniquement (P3, optionnel, isolé).  
**Source :** `docs/API-SPECIFICATION.md`, `docs/FILE-TRANSFER.md`.

## Contexte

L'adaptateur FTPS permettrait la migration/legacy de flux de fichiers via le
protocole FTP sur TLS (FTPS). Il est isolé du cœur AURA et ne doit pas
conditionner l'accès normal aux données.

## Périmètre fonctionnel

| Fonction | Description |
|----------|-------------|
| Serveur FTPS | Écoute sur un port dédié (ex: 21/990), accessible uniquement via le réseau privé |
| Authentification | Identités machine AURA (Bearer `aura_<id>_<secret>`) réutilisées comme identifiants FTPS |
| Opérations supportées | LIST, RETR (download), STOR (upload), MKD, RMD, CWD, PWD, DELE, QUIT |
| Contrôle d'accès | Scopes `objects:read`/`objects:write`/`objects:delete` de l'identité machine |
| Isolation | Chaque identité machine voit uniquement les objets de son espace |
| Audit | Toutes les commandes FTPS journalisées dans l'audit log AURA |

## Architecture

```
Client FTP legacy  →  FTPS Adapter (port 21/990)  →  AURA API (presigned S3 URLs)
                                                   →  SeaweedFS (bytes)
```

L'adaptateur FTPS ne stocke pas les bytes. Il traduit les commandes FTP en
appels API AURA (upload-intents, commit, download-intents) et utilise des URLs
présignées pour le transfert des octets.

## Sécurité

- TLS obligatoire (FTPS implicite sur 990 ou explicite AUTH TLS sur 21)
- Pas de stockage de mots de passe FTPS : réutilisation des tokens machine AURA
- Rate-limiting par IP cliente (même mécanisme que l'API M2M)
- Aucun credential S3 dans l'adaptateur

## Dépendances

- Bibliothèque serveur FTP/S (ex: `pyftpdlib` avec TLS)
- Intégration avec l'API AURA existante (routes upload-intent/commit/download-intent)

## Statut

Non implémenté. À réaliser après les gates P0-P1 (backup, SSH, persistance).

## Fichiers concernés

- `api/` — nouvel adaptateur FTPS (futur)
- `docs/FILE-TRANSFER.md` — documentation existante
- `docker-compose.yml` — nouveau service FTPS (futur)
