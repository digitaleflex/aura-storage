## Contexte
`web/src/pages/ObjectsPage.tsx` (2 900 lignes), `web/src/pages/AdminPage.tsx` (1 600) et `api/main.py` (1 500) concentrent la logique. Chaque changement touche un fichier géant, les revues et les conflits de merge coûtent cher.

## Proposition
- API : `APIRouter` par domaine (`routes/auth.py`, `objects.py`, `folders.py`, `admin.py`), `main.py` ne fait plus que l'assemblage et les middlewares.
- Front : extraire `ObjectsPage` en composants (`FolderTree`, `ObjectTable`, `UploadPanel`, `TransferQueue`, `DeleteDialog`) et hooks (`useObjects`, `useTransfers`).
- Refactor **sans changement de comportement** : la suite Playwright (56 tests) et pytest sont le filet.

## Critères
- [ ] Aucun fichier > 600 lignes.
- [ ] Suites inchangées et vertes.
