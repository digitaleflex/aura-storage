# Modèle de description de PR

Modèle réutilisable pour les PR d'AURA Storage. Sa structure est issue du PR M02
« espace Fichiers » (`feat/vault-integration`, PR #74). Remplacez les `<…>`,
gardez les sections utiles et **supprimez celles qui ne s'appliquent pas** : une
PR honnête sur ses limites vaut mieux qu'une PR complète en apparence.

Rappels : « implémenté » ≠ « validé sur le VPS ». Ne présentez jamais un test CI
ou `docker compose config` comme une preuve de production. Voir aussi
`docs/verification-log-template.md` et `AGENTS.md`.

## Titre

Convention : `type(portée): résumé à l'impératif (mission/issue)`

Exemples : `feat(api): filtrer les objets par état et période (M02)`,
`fix(web): ne pas retirer une ligne avant le succès réel du backend`.

## Contexte

<Problème observé, comportement actuel, et pourquoi cette PR. Une phrase par point.>

- Base : `<branche cible>`
- Tête : `<branche source>` (`<sha court>`)
- Périmètre : `<N fichiers, +X / −Y>`

## Changements

### Backend

<Routes et paramètres ajoutés/modifiés, validation, autorisation requise,
comportement par défaut. Indiquer ce qui est **volontairement non exposé**.>

### Frontend

<Écrans/composants touchés, états loading / empty / error / retry, actions et
leurs confirmations.>

### Docs

<`docs/openapi.yaml`, spécifications, `README`.>

## Contrat / compatibilité

<Le comportement sans paramètre est-il inchangé ? Y a-t-il une rupture ? Quels
champs sont exposés ou masqués ? Les autres fonctionnalités cohabitent-elles
sans régression ?>

## Tests et preuves

- Backend : `<commande>` → `<résultat réel>` (ex. « 190 passed, 2 skipped »)
- E2E : `<résultat réel>`
- Build / lint : `<résultat réel>`

## Tests NON exécutés (avec raison)

- `<test>` : `<raison>` (ex. « parité PostgreSQL : pas de `AURA_TEST_PG_DSN` jetable »)

## Limites / décisions à prendre

- `<limite honnête, ou « aucune »>`

## Checklist

- [ ] Aucun `.env`, clé, certificat, sauvegarde ou donnée utilisateur dans le diff
- [ ] Branche dédiée, aucun travail sur `main`
- [ ] Tests offline exécutés avec résultats réels (et tests non exécutés justifiés)
- [ ] `docs/openapi.yaml` synchronisé si des routes changent
- [ ] Gates critiques respectés le cas échéant (clé SSE-S3 ; pas d'import de
      PDF/audio originaux avant validation)
