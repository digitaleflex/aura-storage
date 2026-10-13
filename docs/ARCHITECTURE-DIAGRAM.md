# AURA Storage — Architecture Diagram

This color-coded Mermaid diagram describes the intended initial single-node MVP. It is a target architecture, not a claim that the VPS has already been provisioned or that all services have been tested.

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

## Color legend

- **Blue:** clients and applications.
- **Purple:** Traefik reverse proxy and operations/security controls.
- **Cyan:** APIs.
- **Green:** storage engine and persistent data.
- **Yellow:** independent backup and restore.
- **Orange:** future integrations and expansion.

Traefik handles HTTPS routing and certificate automation. Its dashboard must be protected. SeaweedFS internal ports remain private. The AURA Management API is a separate planned component for catalogue, logical folders, metadata and import jobs; its implementation and contract still need to be built and tested. A single VPS is not high availability.
