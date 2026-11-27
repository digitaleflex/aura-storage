# Runbooks preuves multipart (#316, #317)

## #316 — Reclaim disque après abort multipart

### Objectif
Mesurer la libération disque attribuable après abort de N parties.

### Procédure (stack jetable)
1. Démarrer stack jetable propre; noter `df`, `volume.list`, taille data dir.
2. Créer upload multipart, uploader N parties, noter taille.
3. Abort via API, vérifier nettoyage catalogue/API.
4. Exécuter `weed shell`: `lock; volume.vacuum -garbageThreshold=0.0001; unlock` (ou selon version).
5. Attendre fenêtre de stabilisation; mesurer `df`/volumes avant/après.
6. Répéter 3 fois; consigner timestamps, commandes, octets attribuables.
7. Si reclaim non attribuable: confirmer mitigation (plafond sessions, alertes capacité, vacuum périodique).

### Livrable
Log daté dans `docs/verification-log-YYYY-MM-DD-multipart-abort-reclaim.md`, mise à jour `ETAT-DES-FONCTIONNALITES.md`.

## #317 — Complétion réelle ~10 000 parties

### Objectif
Uploader ~10 000 parties (~48.8 GiB), compléter, vérifier HEAD/Range/SHA-256.

### Procédure
1. Stack jetable saine, ressources disque/RAM/CPU monitorées.
2. Multipart enabled, limites adaptées temporairement au test.
3. Générer fichier test, découper en 10 000 parts (5 MiB min sauf dernière).
4. Upload avec progression soutenue; enregistrer erreurs/retries.
5. Complete multipart; vérifier objet lisible.
6. Vérifier HEAD, GET Range début/milieu/fin, SHA-256 complet.
7. Documenter résultat et décider maintien/levée plafond 5 000 parts.

### Livrable
Log daté, décision de plafond, mise à jour docs état.
