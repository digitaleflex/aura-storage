# Pull Request — AURA Storage

## Résumé

**Issue :** ISSUE-XXX — [titre de l'issue]  
**Branche :** `feat/issue-XXX-…` → `main`  
**Priorité :** P0 / P1 / P2 / P3  
**Catégorie :** Backend / API / Frontend / UI / Infra / Sécurité / Docs

## Changements

- [ ] Description des fichiers modifiés
- [ ] Nouvelle fonctionnalité / correction de bug / documentation
- [ ] Tests ajoutés ou mis à jour

## Tests exécutés

| Test | Résultat |
|------|----------|
| `pytest tests/test_*.py` (offline) | ✅ / ❌ / ⚠️ |
| `npm run build` (web) | ✅ / ❌ / ⚠️ |
| `npx tsc --noEmit` (web) | ✅ / ❌ / ⚠️ |

## Vérifications

- [ ] Contrat OpenAPI respecté (`tests/test_openapi_contract.py`)
- [ ] Aucun secret committé (`.env`, clés, tokens)
- [ ] Matrice d'autorisation mise à jour si nouvelle route
- [ ] Documentation mise à jour (`docs/`)
- [ ] Breaking change : oui / non

## Notes pour le reviewer

[Éventuelles remarques, zones d'attention, décisions prises]

---

**Gate de production :** cette PR est-elle bloquante avant mise en production ?  
- [ ] Oui (P0) — nécessite validation manuelle sur le VPS (backup, SSH, pare-feu, persistence reboot)  
- [ ] Non (P1/P2/P3) — peut être mergée sans gate VPS
