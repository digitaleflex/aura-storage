# Identité visuelle AURA — propositions

Statut : **direction A retenue et appliquée** (voir l'historique des validations). Les directions B et C restent documentées à titre de comparaison.

La feuille de route d'évolution vers la variante modulaire est dans [`BRAND-ROADMAP.md`](BRAND-ROADMAP.md).

Les fichiers sont dans [`web/public/brand/`](../web/public/brand/) :

| Fichier | Rôle |
| --- | --- |
| `aura-mark-halo.svg` | Direction A recommandée — monogramme seul |
| `aura-lockup-halo.svg` | Direction A — verrouillage horizontal (icône + wordmark) |
| `alternatives/aura-mark-sentinel.svg` | Direction B — bouclier et couches (archivée) |
| `alternatives/aura-mark-orbits.svg` | Direction C — orbites et noyau-coffre, sans fond (archivée) |
| `aura-mark-mono.svg` | Version monochrome (`currentColor`) |
| `aura-favicon.svg` | Favicon 32 px simplifié |
| `alternatives/aura-mark-dash.svg` | Phase 1 — A1 : traverse en trois tirets (archivée) |
| `alternatives/aura-mark-reveal.svg` | Phase 1 — A2 : révélation animée par couches (archivée) |
| `alternatives/aura-icons-system.svg` | Phase 1 — A3 : famille de quatre icônes (archivée) |
| `alternatives/` | Variantes non retenues, conservées pour comparaison |
| `gallery.html` | Page de comparaison visuelle à ouvrir dans un navigateur |

## Directions proposées

- **A — Halo Vault (recommandée).** Le `A` de AURA est construit comme une voûte de coffre, avec une barre lime qui joue le rôle de traverse et d'accent lumineux. Un arc bleu ouvert à droite figure l'aura. C'est la direction la plus lisible en petit format et la plus proche de la géométrie « couches empilées » déjà utilisée par `VaultMark.tsx`.
- **B — Sentinel.** Bouclier bleu, trois couches empilées à l'intérieur. Met l'accent sur la protection et le chiffrement plutôt que sur le stockage. Moins lisible à 16 px.
- **C — Orbits.** Anneaux brisés autour d'un coffre carré. Sans fond, donc utilisable en avatar ou filigrane, mais le lien avec le stockage est moins immédiat.

## Palette

La palette est reprise de la page d'entrée S3 (`landing/index.template.html`, lignes 39–56) : nuit `#060d1a`/`#10203a`, bleu électrique `#2e7cf6`, lime `#c5f441`, encre claire `#dbe4f3`. C'est la définition de couleurs la plus explicite du dépôt.

| Rôle | Hex | Usage |
| --- | --- | --- |
| Nuit profonde | `#060d1a` | Fond des tuiles, fond de page |
| Nuit | `#10203a` | Dégradé des tuiles, surfaces |
| Bordure | `#1a2f52` | Contours discrets, séparateurs |
| Bleu électrique | `#2e7cf6` | Halo, structure, accent principal |
| Lime | `#c5f441` | Accent d'action, point d'ouverture, traverse du `A` |
| Encre claire | `#dbe4f3` | Monogramme et texte sur fond sombre |

Contrastes : le texte clair `#dbe4f3` et le lime `#c5f441` dépassent 4,5:1 sur `#060d1a`/`#10203a`. Le bleu `#2e7cf6` sert d'élement graphique, pas de texte fin sur fond sombre.

**Décision (2026-11-24) :** conserver le bleu + lime sur toute la marque (option 1 de [`BRAND-ROADMAP.md`](BRAND-ROADMAP.md)). L'ambre reste réservé aux actions de l'interface.

**Point d'attention :** l'application elle-même a une palette d'accent ambre/or (`styles.css` : `--signal-bright: #e0a33a` ; `aura-vault-refresh.css` en thème sombre : `--signal: #d49a32`, `--signal-bright: #f0bd5b`), et l'ancien `VaultMark.tsx` utilisait `#E0A33A`. Le nouveau monogramme choisit donc délibérément la palette de la page S3 plutôt que l'ambre de l'interface. Si l'on veut une cohérence totale avec la barre latérale, une variante ambre peut être dérivée en remplaçant le lime `#c5f441` par `#f0bd5b` et le bleu `#2e7cf6` par `#8db3ff` (le bleu utilisé par `--run`).

## Règles d'usage

- **Zone de respiration** : laisser au moins la moitié de la hauteur du monogramme autour de la marque (soit ~32 px pour un monogramme de 64 px).
- **Taille minimale** : 24 px pour le monogramme, 120 px de large pour le verrouillage. Le favicon a son propre dessin simplifié, à partir de 16 px.
- **Fonds** : la tuile sombre est conçue pour les fonds clairs et sombres. La version monochrome s'adapte à `currentColor`. La direction C, sans fond, nécessite un fond minimum de 24 px de contraste.
- **Ne pas** recolorer le lime en bleu, étirer le monogramme, ajouter d'ombre portée, ni remplacer le `A` par une image ou une police différente sans redessiner la traverse.
- **Wordmark** : le SVG de verrouillage utilise une police système générique pour la démonstration. Pour une utilisation de production, convertir `AURA` et `VAULT` en chemins (`inkscape`/`fonttools`) afin de garantir le rendu sur tous les postes. La police de référence de l'application est `Plus Jakarta Sans`.

## Application

La direction A a été appliquée à :

1. `web/src/components/VaultMark.tsx` — monogramme dans la barre latérale, la connexion et les pages d'erreur ;
2. `web/public/favicon.svg` — favicon de l'application ;
3. `landing/index.template.html` — favicon encodé en data-URI et wordmark de la page publique S3 (refonte « deux chemins » : interface web / client S3, explication XML repliée) ;
4. `web/public/brand/vault-mark-mono.svg` — marque monochrome.

**À faire lors du prochain passage avec les dépendances navigateur disponibles :** régénérer les captures de tests visuels (`web/e2e/**/*-snapshots/`) — elles contiennent encore l'ancien monogramme. Le lanceur Chromium de cet environnement ne démarre pas (`libatk-1.0.so.0` absent), donc la régénération n'a pas pu être effectuée ici.
