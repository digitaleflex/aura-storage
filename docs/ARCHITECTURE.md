# AURA Storage Architecture

AURA is an independent storage data plane. Its first deployment is a single VPS; this is not high availability.

## Target topology

```mermaid
flowchart TB
    %% AURA Storage — target architecture, initial single-node MVP
    classDef client fill:#102A56,stroke:#38BDF8,color:#FFFFFF,stroke-width:2px
    classDef proxy fill:#312E81,stroke:#A78BFA,color:#FFFFFF,stroke-width:2px
    classDef api fill:#082F49,stroke:#22D3EE,color:#FFFFFF,stroke-width:2px
    classDef storage fill:#064E3B,stroke:#34D399,color:#FFFFFF,stroke-width:2px
    classDef ops fill:#3B0764,stroke:#C084FC,color:#FFFFFF,stroke-width:2px
    classDef backup fill:#713F12,stroke:#FACC15,color:#FFFFFF,stroke-width:2px
    classDef future fill:#431407,stroke:#FB923C,color:#FFFFFF,stroke-width:2px

    subgraph CLIENTS["Clients et applications"]
      OPERATOR["Administrateur / clients S3<br/>AWS CLI · rclone · Cyberduck"]
      APPS["Applications clientes<br/>OpenBooks · autres services"]
      USERS["Utilisateurs autorisés<br/>via leurs applications"]
    end

    subgraph AURA["AURA-001 · VPS de stockage"]
      direction TB
      HOST["Ubuntu Server LTS<br/>Docker Engine + Docker Compose"]
      TRAEFIK["Traefik<br/>Reverse proxy · HTTPS · Let's Encrypt<br/>Dashboard protégé"]
      MGMT["AURA Management API<br/>Catalogue · dossiers · métadonnées<br/>Imports · opérations autorisées"]
      S3["SeaweedFS Filer + S3 API<br/>API de données privée"]
      MASTER["SeaweedFS Master<br/>topologie et métadonnées"]
      VOLUME["SeaweedFS Volume server<br/>contenu des objets"]
      DISK[("Volumes persistants<br/>données et métadonnées")]
      HOST --> TRAEFIK
      HOST --> MGMT
      HOST --> S3
      TRAEFIK -->|"routes privées"| MGMT
      TRAEFIK -->|"route S3 HTTPS"| S3
      MGMT -->|"API interne / SDK"| S3
      S3 --> MASTER
      S3 --> VOLUME
      MASTER --> VOLUME
      VOLUME --> DISK
    end

    subgraph OPERATIONS["Sécurité et exploitation"]
      SSH["SSH par clés<br/>accès restreint"]
      MON["Surveillance<br/>santé · disque · trafic · journaux"]
      SECRETS["Secrets hors Git<br/>identités S3 par application"]
    end

    subgraph RECOVERY["Protection des données"]
      BACKUP[("Sauvegarde indépendante<br/>autre VPS / compte / fournisseur")]
      RESTORE["Restauration testée<br/>intégrité vérifiée"]
    end

    subgraph FUTURE["Intégrations ultérieures"]
      AXIOM["Axiom<br/>supervision via API authentifiée"]
      AURA2["AURA-002<br/>capacité supplémentaire"]
    end

    OPERATOR -->|"SSH sécurisé"| SSH
    OPERATOR -->|"HTTPS / S3"| TRAEFIK
    APPS -->|"HTTPS / API S3<br/>clés limitées ou URL signées"| TRAEFIK
    USERS -->|"accès autorisé"| APPS
    SECRETS -. "authentification" .-> S3
    MON -. "contrôles locaux" .-> HOST
    DISK -->|"sauvegarde cohérente planifiée"| BACKUP
    BACKUP --> RESTORE
    MGMT -. "API authentifiée, plus tard" .-> AXIOM
    AURA -. "extension future" .-> AURA2

    class OPERATOR,APPS,USERS client
    class TRAEFIK proxy
    class MGMT,S3 api
    class HOST,MASTER,VOLUME,DISK storage
    class SSH,MON,SECRETS ops
    class BACKUP,RESTORE backup
    class AXIOM,AURA2 future
```

## Components and responsibilities

- **Docker Engine + Compose:** reproducible service lifecycle on AURA-001.
- **Traefik:** public HTTPS edge, routing and automatic certificate management. Protect its dashboard with authentication and network restrictions; never expose it as an unauthenticated public admin interface.
- **SeaweedFS Filer + S3 API:** object data interface, namespace and metadata services. Internal service ports must not be exposed publicly.
- **AURA Management API:** a separate application API for cataloguing objects, browsing logical folders, recording import jobs, and authorising management operations. It is not implemented by this diagram alone; define and test its contract before deployment.
- **Persistent volumes:** durable data and metadata on the host filesystem, with capacity verified after provisioning.
- **Independent backup:** a different failure domain, with a tested restore process.
- **Axiom:** later integration through a restricted, authenticated management API. Normal S3 traffic must not depend on Axiom.

## Two API surfaces

1. **S3 data API:** applications and approved tools upload, list, download and delete objects according to credentials/policy.
2. **AURA Management API:** authenticated catalogue/search, logical folder views, object metadata, import-job status, and controlled actions. Keep it separate from unrestricted storage administration.

For folder mapping, do not assume an object store has physical directories. Define logical folder prefixes and metadata, then keep stable object keys/IDs in the catalogue. Ensure listing and deletion operations are permission-checked and auditable.

## Deployment and security requirements

- Install Docker on the provisioned Ubuntu LTS server, then deploy Traefik and the storage stack with reviewed Compose configuration.
- Only required public ports should be open (normally 80/443 for HTTP challenge/redirect and HTTPS, plus SSH restricted as practical).
- Keep SeaweedFS master, volume, filer and administrative ports private.
- Store secrets outside Git; use separate least-privilege S3 identities per application.
- Validate SeaweedFS flags, S3 policy syntax, health checks, TLS routing, upload/download, large objects, Range requests and persistence against the exact pinned release.
- Do not load important content until an independent backup and a successful restore test are verified.

## Limitation

One VPS remains a single point of failure. Add nodes only after the single-node setup, monitoring, backups and restore process are reliable.
