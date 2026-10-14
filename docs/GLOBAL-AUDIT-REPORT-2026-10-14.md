# Rapport final — Mission globale AURA VPS & Storage

> Date : 2026-10-14. Périmètre : VPS InterServer AURA + dépôt `digitaleflex/aura-storage`.
> Méthode : inventaire lecture seule, corrections locales autorisées uniquement, aucun
> changement hôte. Ce document ne contient aucun secret (ni clé privée, ni jeton,
> ni mot de passe, ni valeur `.env`, ni clé SSE-S3).
>
> **Addendum post-publication (2026-10-14)** : la branche `docs/mission-globale-rapport`
> portant ce rapport a été poussée avec succès vers `origin`. Les droits d'écriture
> de la clé dédiée sont donc **confirmés pour `digitaleflex/aura-storage`** et le
> risque R8 est marqué RÉSOLU ci-dessous. Portée strictement limitée : cela ne prouve
> ni les droits sur d'autres dépôts, ni la protection des branches, ni la capacité à
> fusionner une PR.

## 1. Résumé exécutif

Inventaire lecture seule terminé, 2 corrections locales appliquées et commitées, aucun
changement hôte. Faits marquants : **le reboot en attente est résolu** (kernel live
`7.0.0-38-generic`, plus de marqueur), **l'accès lecture GitHub est rétabli** (clé
dédiée re-câblée au dépôt, fetch OK), **aucun composant AURA n'est déployé** (Docker
absent, pas de `.env`, pas de données). Blocages persistants : login SSH par clé non
configuré (`authorized_keys` absent), pare-feu et config SSH effective illisibles sans
sudo interactif, DNS `S3_DOMAIN` ne résout pas, droits d'écriture GitHub inconnus
(aucun push testé, par règle), PR #1 non consultable en détail. Les 14 gates restent
majoritairement NON TESTÉs ; aucun import de données originales n'a eu lieu et reste
interdit.

## 2. État réel de l'hôte

- OS : Ubuntu 26.04.1 LTS (`resolute`), kernel live **7.0.0-38-generic** — le reboot
  attendu par `docs/SERVER-PROFILE.md` a eu lieu (uptime 59 min, 6 users). Le fait
  historique contradictoire est résolu en faveur du nouveau kernel.
- CPU 2, RAM 5,3 Gio (4,4 dispo), swap 1 Gio inutilisé. Racine `/dev/sda4` ext4
  2,9 To (2,8 To libres, 1 % inodes) — capacité toujours à réconcilier avec le panel
  InterServer avant usage.
- Outils : git/ssh/python3/ss/systemctl présents ; **docker, aws, shellcheck, gh
  absents**. `ufw`/`nft` présents mais état illisible (cf. §3).
- Écoute réseau : seul TCP/22 (v4+v6) + DNS stub localhost. Rien d'autre n'écoute.
- Traces AURA : `/srv/aura-storage` inexistant, `.env`/`s3.json` absents, Docker
  absent → **rien de déployé, rien à casser**.

## 3. État réel de la sécurité SSH et réseau

- `ssh.service` disabled mais **active via `ssh.socket`** (socket activation, conforme
  au runbook). Session courante `aura-admin` (sudo, non-docker).
- `~/.ssh` en 0700, clé GitHub 0600 — permissions saines. **`~/.ssh/authorized_keys`
  inexistant** : aucun login par clé configuré pour `aura-admin` ; la session actuelle
  repose sur mot de passe/console. Gate 3 = ÉCHEC à ce stade.
- Config SSH effective (`sshd -T`) et `ufw status` : **BLOQUÉS** — `sudo -n` exige une
  authentification interactive. Aucune modification tentée. Règle rappelée : ne jamais
  désactiver le mot de passe SSH avant clé testée en 2e session + secours confirmé.
- Console de secours : non vérifiable sans accès panel — à confirmer par l'humain.
- DNS : `s3.aura.eurinhash.com` **ne résout pas** ; `github.com` OK.

## 4. État GitHub et branches

- Clé `~/.ssh/id_ed25519_github_aura` existe (0600) ; `ssh -T` répond
  `Hi digitaleflex/aura-storage!` — identité de type **deploy key au niveau du dépôt**.
- Lecture rétablie par correctif local : `core.sshCommand` du dépôt pointe vers la clé
  dédiée (`git fetch origin` OK). Écriture : **CONFIRMÉE le 2026-10-14** par le push
  réussi de `docs/mission-globale-rapport` (voir addendum). Portée : ce dépôt
  uniquement, pas les autres dépôts.
- Branches : `feat/secure-storage-pilot` = `origin/feat` @79ef615 ; `origin/main`
  @ab228ef — **feat non fusionnée, 26 commits d'écart**. PR #1 détectée
  (`head`=79ef615) mais détails inaccessibles (pas de `gh`, pas de token).
- Correctifs Missions 2/2A + CI : branche `chore/mission-2-safe-fixes`
  (`6c1b70d`, `f52a917`), non publiée au moment de l'inventaire.

## 5. Architecture AURA réelle

- **Dans le code** : `docker-compose.yml` (Traefik 3.4.3 + SeaweedFS 4.48
  master/volume/filer-S3), scripts `bootstrap/generate-config/deploy/host-preflight/
  healthcheck`, 2 smoke tests S3, CI syntaxe+config, `.env.example`, `s3.json.example`
  (identité bootstrap Admin unique).
- **Configurés mais non démarrés** : aucun (pas de `.env`, pas de Docker).
- **Seulement documentés** : Management API, PostgreSQL, OpenBooks/Axiom,
  backup/restore, VPN — propositions, rien d'exécutable.
- Réseaux/principes Compose inchangés et sains sur le papier (seuls 80/443 publiés,
  réseau storage interne).

## 6. Registre priorisé des risques

| ID | Sév. | Constat (preuve) | Impact / Proba | Correction / Prérequis | Auto ? | Validation | Autorisation |
|---|---|---|---|---|---|---|---|
| R1 | P0 | Pas de login SSH par clé (`~/.ssh` sans `authorized_keys`) | Perte d'accès si durcissement ; Moyenne | Installer pubkey depuis poste de confiance, tester en 2e session / console secours dispo | Non | Login clé en 2e session | **Oui** |
| R2 | P0 | Firewall/config SSH effectifs inconnus (`sudo -n` refusé) | Lock-out ou exposition ; Moyenne | Inspection avec sudo interactif, revue avant toute règle / console secours | Non | `ufw status verbose`, `sshd -T` | **Oui** |
| R3 | P0 | Aucun backup, aucune restauration testée | Perte de données dès import ; Certaine si import | Destination indépendante + restore isolé / après déploiement validé | Partiel (doc) | Restore avec hashes OK | **Oui** |
| R4 | P0 | Clé SSE-S3 : stockage hors-ligne non vérifiable ; perte = objets irrécupérables | Perte définitive ; Faible si procédure suivie | Procédure `.env` 0600 + copie offline / à la création du `.env` | Non | Smoke SSE-S3 + preuve de recouvrement clé | **Oui** |
| R5 | P1 | Docker non installé, support Ubuntu 26.04 à confirmer | Pilote bloqué ; Certain | Installation doc officielle / reboot+SSH OK d'abord | Non | `docker --version`, persistance reboot | **Oui** |
| R6 | P1 | DNS S3 sans résolution, pas de TLS | Pilote bloqué ; Certain | Enregistrement A + HTTP-01 / ports 80-443 vers Traefik | Non | Certificat valide externe | **Oui** |
| R7 | P1 | Identité bootstrap S3 unique `Admin` | Privilèges excessifs en routine ; Moyenne | Identités least-privilege par app après smoke test | Oui (après déploiement) | Refus d'accès non autorisé | Non (config locale) |
| R8 | P1 — **RÉSOLU 2026-10-14** | Droits push GitHub inconnus ; commits non publiés | Dérive local/distant ; Moyenne | Tester push ou confirmer droits deploy key / accord humain | Non | ~~Branche visible sur origin~~ → push `docs/mission-globale-rapport` réussi, écriture confirmée sur ce dépôt uniquement | **Oui** |
| R9 | P2 | Healthchecks SeaweedFS non prouvés (`wget` supposé) | Faux négatifs ; Moyenne | Inspection image 4.48 / Docker dispo | Partiel | `compose ps` healthy | **Oui** (modif Compose) |
| R10 | P2 | Pas de limites ressources/logs dans Compose | Épuisement hôte ; Faible | `cpus/mem_limit`, rotation logs / calibration 2CPU-5Go | Partiel | `docker stats`, logs bornés | **Oui** |
| R11 | P2 | Socket Docker monté sur Traefik ; groupe docker = root effectif | Élévation ; Faible | Moindre privilège, `sudo docker` / décision d'accès | Non | Revue accès daemon | **Oui** |
| R12 | P3 | Doublon OPERATIONS, pas de LICENSE, proposals en attente | Dette doc ; — | Arbitrage éditorial + choix licence / décision humaine | Oui (brouillon) | Docs fusionnées, licence posée | **Oui** |

Hypothèses non présentées comme vulnérabilités : compromission via tentatives SSH
(bruit de fond normal), chiffrement effectif 4.48 (non prouvé tant que le smoke test
n'a pas tourné).

## 7. Corrections réalisées

1. **C0 — Câblage lecture GitHub** : `core.sshCommand` local → clé dédiée +
   `BatchMode`. Test : `git fetch origin` OK. Config locale uniquement, aucun secret.
2. **C1 — CI : branchement du test anti-régression** : +4 lignes dans
   `validate-storage-config.yml` (syntaxe des 2 scripts S3 + étape
   `Run offline regression tests`). Commit `f52a917`.
3. **C2 (Mission 2, rappel)** : fix P0 `tests/s3-smoke-test.sh` + test
   `tests/test-s3-smoke-validation.sh` + `AGENTS.md`. Commit `6c1b70d`.

## 8. Fichiers modifiés

- `.github/workflows/validate-storage-config.yml` (+4 l., `f52a917`).
- `tests/s3-smoke-test.sh`, `tests/test-s3-smoke-validation.sh`, `AGENTS.md` (`6c1b70d`).
- `.git/config` : `core.sshCommand` (correction d'accès locale, non versionnée).
- Le présent rapport : `docs/GLOBAL-AUDIT-REPORT-2026-10-14.md`.

## 9. Tests exécutés avec résultats réels

- Host : OS/kernel/uptime/ressources/disques/écoute — valeurs §2.
- `ssh -T` clé dédiée : authentifié. `git fetch`/`ls-remote` : lecture OK.
- `bash -n` 8 scripts/tests : OK. Régression stubbed : **5 passed, 0 failed**.
- YAML workflow : parse OK. `git diff --check` : propre. Scan secrets : aucun.

## 10. Gates AURA

| # | Gate | État |
|---|---|---|
| 1 | OS/kernel/capacité confirmés | **RÉUSSI** (capacité à réconcilier panel — partiel) |
| 2 | Console de secours / récupération | **NON TESTÉ** |
| 3 | SSH par clé en 2e session | **ÉCHEC** (`authorized_keys` absent) |
| 4 | Pare-feu et ports | **BLOQUÉ** (sudo interactif requis ; seul 22 écoute) |
| 5 | Docker/Compose supportés | **NON TESTÉ** (absent, autorisation requise) |
| 6 | Compose validé sans secrets | **NON TESTÉ** (pas de `.env` ; CI seulement) |
| 7 | DNS + TLS | **ÉCHEC** (S3_DOMAIN ne résout pas) |
| 8-9 | Démarrage/santé, isolation réseau | **NON TESTÉ** (rien déployé) |
| 10-11 | S3 réel SSE-S3 AES256, auth/refus | **NON TESTÉ** (interdit sans autorisation) |
| 12 | Persistance après redémarrage | **NON TESTÉ** |
| 13 | Backup indépendant + restore | **NON TESTÉ** |
| 14 | Aucune donnée originale importée | **RÉUSSI** (vérifié : rien déployé, rien importé) |

## 11. Actions non exécutées et raisons

Reboot (inutile : déjà effectif), sudo interactif, durcissement SSH, firewall, Docker,
WireGuard, DNS/TLS, déploiement, tests S3 réels, backup/restore, modif Compose,
rotation SSE-S3, import données — **toutes requièrent une autorisation humaine
explicite** et/ou des prérequis non remplis (gates 2-4 d'abord).

## 12. Risques résiduels

Accès console non confirmé, exposition réelle du firewall inconnue, DNS/TLS à zéro,
droits d'écriture GitHub inconnus jusqu'au push, PR #1 non revue en détail, support
Docker sur Ubuntu 26.04 non confirmé.

## 13. Décisions humaines nécessaires (liste courte)

1. Installer la clé SSH publique d'administration et tester le login en 2e session.
2. Autoriser une session avec sudo interactif pour lire `sshd -T`/`ufw` puis durcir.
3. Confirmer la console de secours et la capacité panel InterServer.
4. Confirmer les droits d'écriture de la deploy key, puis autoriser push et PR.
5. Choisir la licence du dépôt (recommandation : mention privée explicite ou
   Apache-2.0 si ouverture).
6. Autoriser dans l'ordre : Docker → DNS/TLS → déploiement → smoke tests →
   backup/restore.

## 14. Plan d'action suivant (priorisé)

P0 : clé SSH + inspection privilégiée + secours/capacité. P1 : push/PR, Docker,
DNS/TLS, smoke SSE-S3, identités least-privilege, backup/restore. P2 : healthchecks
prouvés, limites ressources/logs, revue accès Docker. P3 : fusion OPERATIONS, licence,
API/catalogue.

## 15. État final du dépôt

Branche de correctifs `chore/mission-2-safe-fixes` (`6c1b70d`, `f52a917`) ; le présent
rapport est publié via la branche `docs/mission-globale-rapport`. Texte de PR brouillon
(non ouverte, vers `feat/secure-storage-pilot`, jamais `main`) : titre `Safe fixes: S3
smoke validation + offline regression + CI wiring` ; corps = résumé §7, tests §9 (5/5),
risques = branche non publiée, CI distante non rejouée ; limites = validation locale
uniquement, aucun test production.

## 16. État final du VPS

**Aucun changement hôte effectué** : ni paquet, ni service, ni SSH, ni firewall, ni
réseau, ni reboot, ni fichier système. Seules écritures : config git locale du dépôt
et commits locaux.
