# AURA Storage — Architecture

Ce diagramme représente la cible initiale : un VPS autonome, Docker Compose, Traefik pour le reverse proxy et TLS, SeaweedFS pour le stockage objet et une API AURA pour les opérations de gestion.

```mermaid
flowchart TB
    subgraph CLIENTS["Clients et applications"]
        ADMIN["Administrateur<br/>SSH / client S3"]
        APPS["Applications<br/>OpenBooks · autres services"]
        USERS["Utilisateurs autorisés"]
    end

    subgraph AURA["AURA-001 · VPS de stockage"]
        HOST["Ubuntu Server LTS<br/>Docker Engine + Compose"]
        TRAEFIK["Traefik Proxy<br/>HTTPS · Let's Encrypt<br/>Dashboard protégé"]
        S3["SeaweedFS Filer + API S3<br/>réseau Docker privé"]
        DATA[("Volumes persistants<br/>fichiers + métadonnées")]
        HOST --> TRAEFIK
        TRAEFIK --> S3
        S3 --> DATA
    end

    subgraph MGMT["API et exploitation AURA"]
        API["AURA Management API<br/>inventaire · dossiers virtuels<br/>recherche · métadonnées"]
        AUTH["Authentification · autorisation<br/>audit · quotas"]
        MON["Surveillance<br/>état · capacité · trafic · journaux"]
    end

    subgraph RECOVERY["Protection des données"]
        BACKUP[("Sauvegarde indépendante<br/>autre VPS / fournisseur / NAS")]
        RESTORE["Restauration testée<br/>intégrité vérifiée"]
    end

    subgraph FUTURE["Intégrations futures"]
        AXIOM["Axiom<br/>API versionnée"]
        OPENBOOKS["OpenBooks<br/>catalogue et droits d'accès"]
        AURA2["AURA-002<br/>extension future"]
    end

    ADMIN -->|"SSH restreint"| HOST
    ADMIN -->|"Import / récupération"| TRAEFIK
    APPS -->|"HTTPS + API S3"| TRAEFIK
    USERS -->|"Via les applications"| APPS
    API -->|"Opérations contrôlées"| DATA
    API -.-> AUTH
    MON -.-> HOST
    DATA --> BACKUP
    BACKUP --> RESTORE
    AXIOM <-->|"Plus tard"| API
    OPENBOOKS <-->|"S3 + API de gestion"| API
    AURA --> AURA2
```

## Règles d'architecture

- **Traefik** : routage HTTP/HTTPS, certificats TLS automatisés, journaux et métriques. Son dashboard est une interface d'observation, pas une console de gestion des fichiers ; il doit rester protégé.
- **SeaweedFS** : stockage des objets et interface S3. Les ports internes et les interfaces d'administration ne sont pas publiés directement sur Internet.
- **API AURA** : couche à développer pour cartographier les objets, maintenir les métadonnées, exposer une arborescence logique, rechercher et appliquer les permissions. Elle ne doit pas dépendre de l'interface Traefik.
- **Volumes persistants** : les données survivent au remplacement des conteneurs. Ils ne remplacent pas une sauvegarde indépendante.
- **Sauvegarde** : destination distincte et restauration testée avant l'import des données importantes.
- **Périmètre MVP** : un VPS n'est pas de la haute disponibilité. La réplication multi-serveurs sera une évolution séparée.
- **Statut** : cible d'architecture ; configuration, commandes et politiques SeaweedFS doivent être testées avec les versions retenues avant production.
