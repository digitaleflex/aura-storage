# Incident SSH — accès root refusé (2026-10-14)

> **Type :** incident d'accès administratif  
> **Hôte :** VPS AURA / `vps3718250.trouble-free.net`  
> **État :** résolution signalée par l'opérateur ; validation indépendante non effectuée  
> **Portée :** documentation et durcissement à planifier — aucune commande de ce document n'est exécutée automatiquement.

## 1. Résumé

Le client SSH pouvait établir une connexion vers le port TCP 22 du VPS et reconnaissait la clé d'hôte enregistrée. L'authentification interactive du compte `root` échouait avec `Failed password`, alors que le compte `aura-admin` permettait d'ouvrir une session et d'utiliser `sudo`.

L'incident ne correspondait donc pas à une panne réseau ou à un service SSH inaccessible. Les contrôles ont indiqué que l'authentification par mot de passe était autorisée par la configuration effective et que le compte root possédait un mot de passe défini. Les journaux ont ensuite confirmé des échecs de vérification du mot de passe pour root.

L'opérateur a indiqué que l'accès était de nouveau fonctionnel à la fin de l'échange. La méthode exacte de résolution et un test de connexion final n'ont pas été collectés indépendamment ; ils ne sont donc pas présentés comme une preuve auditée.

## 2. Symptômes observés

- Connexion TCP/SSH au serveur réussie sur le port 22.
- Bannière serveur observée : `OpenSSH_10.2p1 Ubuntu-2ubuntu3.7`.
- La clé d'hôte présentée correspondait à celle déjà connue du client.
- Le profil client affichait `Private Key is empty` : aucune clé privée utilisable n'était configurée dans ce profil.
- Les tentatives de connexion par mot de passe à `root` se terminaient par `Authentication failed (password)`.
- La connexion à `aura-admin` fonctionnait.

## 3. Contrôles exécutés et résultats

### Identité et privilèges du compte d'administration

Commandes :

```bash
whoami
id
sudo -v
```

Résultat rapporté :

- utilisateur : `aura-admin`
- UID : `1000`
- groupes : `aura-admin`, `sudo` (GID 27), `users`

La sortie ne montrait pas d'erreur de `sudo -v`.

### Configuration SSH effective

Commande :

```bash
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|authenticationmethods|usepam)'
```

Résultat :

```text
usepam yes
permitrootlogin yes
pubkeyauthentication yes
passwordauthentication yes
authenticationmethods any
```

Interprétation : la configuration effective générale autorisait la connexion root par mot de passe. Ce résultat n'exclut pas à lui seul toutes les règles conditionnelles éventuelles liées à `Match`, mais aucune interdiction globale de root par mot de passe n'était visible dans cette sortie.

### État du mot de passe root

Commande :

```bash
sudo passwd -S root
```

Résultat rapporté :

```text
root P 2026-10-14 0 99999 7 -1
```

Interprétation : `P` indique qu'un mot de passe est défini et que le compte n'est pas marqué verrouillé par ce statut. Cela ne valide pas le mot de passe saisi par le client.

### Journaux d'authentification

Commande :

```bash
sudo journalctl -u ssh --since "30 minutes ago" --no-pager \
  | grep -Ei 'root|failed|invalid|authentication'
```

Les journaux contenaient notamment :

- `Failed password for root`
- `unix_chkpwd: password check failed for user (root)`
- `pam_unix(sshd:auth): authentication failure`

Des tentatives échouées pour d'autres comptes et depuis d'autres adresses sources étaient également visibles. Les extraits fournis ne démontraient pas une connexion réussie de ces sources.

## 4. Diagnostic

**Cause immédiate étayée :** le mot de passe présenté lors des tentatives de connexion root n'était pas accepté par PAM/Linux.

**Causes non établies :** le dossier ne permet pas de distinguer définitivement un mot de passe saisi incorrectement, un mot de passe client obsolète ou un autre problème lié au secret utilisé. La présence d'un mot de passe défini dans la base locale ne prouve pas que le client saisissait le bon.

La connectivité SSH, la reconnaissance de la clé d'hôte et la disponibilité du compte `aura-admin` ont permis de poursuivre le diagnostic sans perdre l'accès administratif.

## 5. Procédure de récupération utilisée comme remède proposé

La procédure proposée pendant le diagnostic était de définir un nouveau mot de passe root depuis la session `aura-admin` disposant de `sudo` :

```bash
sudo passwd root
```

Puis de tester depuis le poste d'administration :

```bash
ssh root@153.75.248.230
```

L'opérateur a ensuite confirmé que la situation était « bonne », mais n'a pas fourni de preuve de connexion finale ni précisé explicitement quelle action avait résolu le problème. **Considérer la résolution comme déclarée par l'opérateur, et non comme une validation technique auditée.**

Ne jamais inscrire de mot de passe, de clé privée, de jeton ou de secret dans ce document, un ticket GitHub, les journaux ou une conversation.

## 6. Actions de suivi recommandées

- [ ] Vérifier depuis un nouveau terminal que `aura-admin` se connecte par clé SSH.
- [ ] Garder une seconde session ouverte pendant les changements SSH.
- [ ] Confirmer l'accès de secours à la console fournisseur.
- [ ] Installer une clé publique SSH personnelle pour `aura-admin` et vérifier le mode `0600` du fichier `authorized_keys` ainsi que les permissions du répertoire `.ssh`.
- [ ] Vérifier les journaux SSH récents pour identifier d'éventuelles tentatives répétées.
- [ ] Examiner le pare-feu et limiter le port 22 aux sources de confiance lorsque c'est opérationnellement possible.
- [ ] Après confirmation de l'accès par clé et du mécanisme de secours, désactiver la connexion root directe et l'authentification par mot de passe selon la politique retenue.
- [ ] Tester les changements dans une seconde session avant de fermer la session existante.
- [ ] Consigner les preuves et mettre à jour l'issue GitHub #4 uniquement lorsque les critères d'acceptation sont effectivement satisfaits.

## 7. Principes de sécurité

1. Préférer l'administration via `aura-admin` et `sudo`, avec une clé SSH nominative.
2. Ne pas désactiver le dernier chemin d'accès fonctionnel avant d'avoir testé un chemin alternatif et la console de secours.
3. Ne pas interpréter `permitrootlogin yes` comme une raison de conserver durablement l'accès root par mot de passe.
4. Ne pas copier les mots de passe ou les clés privées dans les tickets, les journaux ou Git.
5. Toute modification de SSH ou du pare-feu doit être suivie d'un test réel et réversible.

## 8. Critère de clôture de l'incident

L'incident pourra être marqué **techniquement vérifié** lorsque :

- une nouvelle session administrative réussit ;
- l'accès par clé est démontré, si cette méthode est retenue ;
- le mécanisme de secours est confirmé ;
- la politique SSH finale est vérifiée avec `sshd -T` (et les règles conditionnelles pertinentes) ;
- les résultats sont consignés sans secrets.

**Lien de suivi :** issue [#4 — Sécuriser et valider l'accès administrateur au VPS](https://github.com/digitaleflex/aura-storage/issues/4).
