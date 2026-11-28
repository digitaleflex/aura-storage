# Feuille de route — identité AURA, variante « modulaire »

Objectif : faire évoluer la direction **A — Halo Vault** (déjà appliquée) vers une version modulaire inspirée des principes de Dashlane et Pure Storage — monogramme à concept, géométrie décomposable, jeu « révéler / cacher » — **sans copier aucun logo tiers**.

Références : [`BRAND-IDENTITY.md`](BRAND-IDENTITY.md) (décision A, palette, règles d'usage), [`web/public/brand/gallery.html`](../web/public/brand/gallery.html) (comparaison visuelle).

## Principes directeurs

1. **Inspiration de principes, pas de formes.** On emprunte la logique (monogramme à concept, modules réutilisables, retenue), jamais un tracé, une couleur signature ou une typographie d'une autre marque.
2. **Le `A` reste la voûte.** Toute variante doit conserver la lecture « AURA + coffre » et la traverse lime comme accent.
3. **Une seule source de couleur par support.** Page S3 (bleu/lime) et interface (ambre) sont deux palettes distinctes : trancher avant d'étendre la marque (phase 0).
4. **Lisibilité avant décor.** Validé à 16 px en favicon, 24 px en monogramme, en monochrome et sur fond clair comme sombre.
5. **Accessibilité.** Contraste ≥ 4,5:1 pour tout texte ; la marque reste décorative (`role="img"` avec libellé) et ne porte jamais d'information seule.

## État actuel

| Élément | Statut |
| --- | --- |
| Direction A appliquée à `VaultMark.tsx`, `favicon.svg`, `vault-mark-mono.svg`, page S3 | ✅ Fait |
| Directions B/C documentées et comparables | ✅ Fait |
| Guide d'identité | ✅ Fait |
| Variante modulaire | ✅ Phase 1 livrée — 🔄 validation phase 2 |
| Décision palette interface vs page S3 | ✅ Bleu + lime (option 1) retenue le 2026-11-24 |
| Wordmark converti en chemins (police embed) | ⬜ À faire (phase 4) |
| Régénération des captures visuelles e2e | ⬜ À faire (phase 5, dépend de l'environnement) |

## Phases

### Phase 0 — Cadrage — ✅ terminée (2026-11-24)

**Décision : option 1 — bleu `#2e7cf6` + lime `#c5f441` conservés sur toute la marque.** Cohérence avec la page S3 et avec le monogramme déjà appliqué ; l'ambre reste la couleur d'action de l'interface, sans être employée dans la marque.

- Options écartées : ambre `#f0bd5b` + bleu `#8db3ff`, et deux variantes contextuelles.
- **Critère d'acceptation rempli** : palette unique, documentée dans `BRAND-IDENTITY.md`.

### Phase 1 — Exploration de la variante modulaire — ✅ livrée (2026-11-24)

Trois pistes dessinées en SVG, dans `web/public/brand/` :

| Piste | Idée | Ce que ça emprunte |
| --- | --- | --- |
| **A1 — Dash** | La traverse lime se décompose en 3 tirets séparés, évoquant les couches de fichiers empilées. | Dashlane : monogramme modulaire ; Pure Storage : métaphore du stockage. |
| **A2 — Reveal** | Le `A` se construit par révélation progressive des couches (à utiliser en état de chargement/transfert). | Dashlane : « révéler / cacher » ; Skiff : surfaces qui apparaissent/disparaissent. |
| **A3 — System** | Le monogramme devient une famille : icônes dérivées (fichier, dossier, partage, coffre) sur la même grille. | Modex : géométrie modulaire ; Astio : langage systémique. |

- **Livrables archivés** : `alternatives/aura-mark-dash.svg`, `alternatives/aura-mark-reveal.svg` (state statique + animation CSS de démonstration), `alternatives/aura-icons-system.svg`, mise à jour de `gallery.html`.
- **Critère d'acceptation** : chaque piste est lisible en 24 px et reconnaissable comme un `A` ; aucune ne reprend un tracé de marque existante.

### Phase 2 — Validation technique — 🔄 en cours (contrôle statique fait, rendu à faire)

Contrôle statique effectué le 2026-11-24 :

- Les 10 SVG du dossier `web/public/brand/` et `web/public/favicon.svg` sontXML-valides.
- Toutes les couleurs employées appartiennent à la palette déclarée (`#060d1a`, `#10203a`, `#1a2f52`, `#2e7cf6`, `#c5f441`, `#dbe4f3`).
- A2 contient `@media (prefers-reduced-motion: reduce)` : l'animation se désactive et l'état statique reste lisible.
- Aucun tracé de marque tiers n'est repris : les trois variantes dérivent du `A` existant.
- Risque identifié pour A1 : à 24 px, les écarts entre tirets font ~0,8 px et peuvent se fondre. Le favicon reste le dessin simplifié existant, donc A1 n'a pas à passer à 16 px.

Reste à faire : rendu visuel réel et contraste mesuré (voir dépendance d'environnement en phase 5).

- Rendu à 16 / 24 / 32 / 64 px, sur fond sombre et clair.
- Version monochrome (`currentColor`) et version impression (noir sur blanc).
- Contraste des couleurs d'accent vérifié sur les deux fonds.
- Test de non-copie : comparaison visuelle avec les références citées ; aucun élément distinctif repris.
- **Livrable** : tableau de validation dans `BRAND-IDENTITY.md` + galerie mise à jour.
- **Critère d'acceptation** : aucun cas de lisibilité ou de contraste en échec.

### Phase 3 — Choix

- Comparer A (actuel), A1, A2, A3 dans la galerie.
- Pointer une seule variante retenue ; archiver les autres comme `alternatives/` sans les supprimer.
- **Livrable** : décision écrite dans `BRAND-IDENTITY.md`.
- **Critère d'acceptation** : un seul gagnant, avec une raison formulée en une phrase.

### Phase 4 — Intégration (après choix uniquement)

- `web/src/components/VaultMark.tsx` : nouveau tracé si retenu ; conserver `useId()` pour les définitions SVG.
- `web/public/favicon.svg` et favicon data-URI de `landing/index.template.html`.
- `web/public/brand/vault-mark-mono.svg`, `aura-lockup-halo.svg`.
- Convertir `AURA` / `VAULT` du wordmark en chemins pour supprimer la dépendance à la police système.
- Si piste A2 retenue : composant d'animation léger (CSS/SVG), sans JavaScript, `prefers-reduced-motion` respecté.
- **Critère d'acceptation** : `npx tsc --noEmit`, `npx eslint`, build Vite OK ; aucune régression fonctionnelle.

### Phase 5 — Tests et environnement

- Régénérer `web/e2e/**/*-snapshots/` (marque visible dans login, admin, fichiers, transferts, mobile).
- Relancer les tests d'accessibilité automatisés (`@axe-core/playwright`).
- **Dépendance** : le Chromium Playwright de cet environnement ne démarre pas (`libatk-1.0.so.0` absent). Cette phase doit se faire dans un environnement avec les bibliothèques navigateur installées, ou après `npx playwright install --with-deps`.
- **Critère d'acceptation** : suite e2e verte avec les nouvelles captures ; aucun écart d'accessibilité.

### Phase 6 — Livraison et nettoyage

- Décider si `web/public/brand/gallery.html` reste livré (page de revue interne) ou est déplacé sous `docs/`.
- Mettre à jour `README.md` si un lien de marque y est ajouté.
- Archiver les propositions non retenues sous `web/public/brand/alternatives/`.
- **Critère d'acceptation** : dépôt propre, documentation à jour, une seule marque active.

## Récapitulatif

| Phase | Livrable principal | Décision / dépendance |
| --- | --- | --- |
| 0 — Cadrage | Palette arrêtée | **Bloque les phases 1–4** |
| 1 — Exploration | 3 variantes SVG + galerie | — |
| 2 — Validation | Tableau lisibilité/contraste | — |
| 3 — Choix | Variante retenue | **Bloque la phase 4** |
| 4 — Intégration | Code et assets mis à jour | — |
| 5 — Tests | Captures et e2e vertes | Dépend de l'environnement navigateur |
| 6 — Livraison | Doc et dépôt nets | — |

## Risques et mitigations

| Risque | Mitigation |
| --- | --- |
| La variante modulaire devient trop complexe à 16 px | Garde-fou de la phase 2 : test systématique à 16 px, simplification obligatoire si échec. |
| Mélange des palettes ambre et bleu/lime | Phase 0 : décision écrite avant tout dessin. |
| Reproduire involontairement un logo de référence | Test de non-copie en phase 2 ; partir du `A` existant, jamais d'un calque. |
| Animation inaccessible ou coûteuse | CSS uniquement, pas de JavaScript, `prefers-reduced-motion`, état statique équivalent. |
| Captures visuelles non régénérées | Phase 5 explicite ; documenté comme dépendance d'environnement. |

## Prochaine action

Phases 0 et 1 terminées. Prochaine action : terminer la **phase 2** (rendu visuel et contraste des trois variantes dans un navigateur), puis soumettre le **choix de la phase 3** (A / A1 / A2 / A3) avant toute intégration.
