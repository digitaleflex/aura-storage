## Contexte
`POST /objects/{id}/commit` relit l'objet entier depuis S3 pour calculer le SHA-256 **dans la requête HTTP**, jusqu'à `AURA_MAX_OBJECT_BYTES` (5 Gio). L'API tourne avec un seul worker uvicorn : quelques gros commits simultanés occupent le pool de threads, et un client qui coupe pendant le hachage obtient un résultat ambigu.

## Proposition
- `commit` vérifie la présence et la taille (`HEAD`), passe l'objet à `verifying` et répond **202** avec l'état.
- Un worker (même image, commande différente) prend les objets `verifying` depuis une file PostgreSQL (`SELECT … FOR UPDATE SKIP LOCKED`), hache en flux, passe à `available` ou `failed`.
- Le client suit l'état (polling `GET /objects/{id}` ; le front a déjà un état « validating »).
- Option à évaluer : faire calculer le checksum par S3 à l'envoi (`x-amz-checksum-sha256` signé dans l'URL) si SeaweedFS 4.48 le vérifie réellement — gate de compatibilité avant de s'y fier.

## Critères
- [ ] Temps de réponse du commit indépendant de la taille.
- [ ] Reprise après crash du worker (objet resté `verifying` repris).
- [ ] Aucun objet `available` sans SHA-256 vérifié.
- [ ] Tests : commit concurrent, worker tué en cours, objet modifié entre HEAD et hachage.

## Liens
Recentre #83 ; à coordonner avec #72 (multipart).
