# Design system AURA Vault — v2.1 (brique « tokens », prompt 02)

Système réutilisable pour les pages existantes (`ObjectsPage`, `AdminPage`,
`LoginPage`) et leurs composants partagés. **Source unique : `styles.css`
(racine `:root`)**. La couche concurrente historique (`vault-tokens.css`,
palette vert/bleu d'une maquette S16 sans consommateurs) a été supprimée :
plus un seul jeu de variables.

## Principe de consommation

Les composants ne consomment **que des jetons nommés**, jamais de valeur
brute. Contrastes et états `sélection / avertissement` explicitement
corrigés (voir ci-dessous) : le diff de
prompt 02 est un changement de **vocabulaire** (tokens) et une harmonisation
sémantique, pas un redessin.

## Palette (verrouillée, contrastes vérifiés WCAG 2.1)

| Rôle | Jeton | Valeur | Contraste |
|---|---|---|---|
| Sidebar sombre | `--side` | `#10151d` | — |
| Texte sur sidebar | `--side-ink` | `#d5dbe3` | 13.1:1 |
| Texte secondaire sidebar | `--side-muted` | `#8e99a8` | 6.3:1 |
| Fond de l'espace de travail | `--steel-0` | `#f5f7fa` | — |
| Surface principale | `--steel-1` | `#ffffff` | — |
| Surface altérée (hover/object-level) | `--steel-2` / `--steel-3` | `#eef0f3` / `#e3e6eb` | — |
| Texte principal | `--ink` | `#172033` | 16.3:1 sur blanc |
| Texte secondaire | `--ink-2` / `--muted` / `--faint` | `#3d4654` / `#5b6472` / `#6b7480` | 9.5 / 6.0 / 4.7 |
| Accent DORÉ (seule couleur d'action) | `--signal` | `#9d660d` | 4.8:1 sur blanc |
| Accent : survol (foncé) | `--signal-2` | `#7a4d07` | > 4.8 |
| Accent : fond doux / bord | `--signal-soft` / `--signal-line` | `#fbf1e0` / `#e6c893` | — |
| Accent sur fond sombre (marques, focus latéral) | `--signal-bright` | `#e0a33a` | 8.3:1 |
| Succès | `--ok` / `--ok-bg` | `#1e6b44` / `#e6f3ec` | 5.7:1 |
| En cours | `--run` / `--run-bg` | `#2350ae` / `#e7eefb` | 6.4:1 |
| Avertissement | `--warn` / `--warn-bg` | `#8a6410` / `#f8f0dc` | 4.7:1 |
| Danger | `--danger` / `--danger-bg` | `#a8291f` / `#fbeae8` | 6.0:1 |
| Danger : survol fond plein | `--danger-strong` | `#8f2c22` | — |

> Note DA : la consigne demandait `#A96B13` ; à contrastes réels, ce doré ne
> passe pas 4.5:1 en texte blanc de bouton primaire (4.38:1). Adoption de la
> même teinte assombrie `#9d660d` (4.84:1). Le fond sombre `#10151d` et
> l'éclairage `#f5f7fa` ont été pris telles que fournis.

### Correction sémantique
- `.alert-warn` (bannière « Import interrompu ») consomme désormais
  `--warn/--warn-bg` ; elle utilisait l'**accent d'action** ambré,
  confondant « avertissement » et « action principale ». Aucun sélecteur
  e2e ne dépendait de l'ancien rendu (vérifié).

## Échelles ajoutées (toutes consommées par les sections partagées)

- **Espacements** `--space-1..8` (4→40 px). Les gabarits de page restent
  écrits librement ; les composants consomment l'échelle.
- **Contrôles** `--control-fs(-sm)`, `--control-pad-y/x(-sm)`,
  `--field-fs`, `--field-pad-y/x`, `--tap-target` (44px WCAG 2.5.8),
  `--tap-hit` (38 en-table). Boutons ET champs partagent ces primitives.
- **Bordures** `--bw` (1) / `--bw-strong` (2 : dashed drop, focus, ind.
  visuel fort).
- **Ombres** 4 élévations uniquement : `--shadow-1/2/3`, `--shadow-tray`,
  `--shadow-toast`. Aucune autre ombre autorisée.
- **Z-index** `--z-sticky(40)` > `--z-menu(50)` > `--z-drawer(55)` >
  `--z-toast(60)`.
- **Transitions** `--dur-fast(70)/--dur-std(110)/--dur-slow(160)` +
  `--ease-std/--ease-press`. Press < settle.
- **Typographie** `--fs-2xs..xl` (11→26 px), `--lh-tight/std`,
  `--track-tight`. Familles : `--font-ui` (IBM Plex Sans),
  `--font-mono` (anything you compare). Un seul poids de titre (600).

## Typographie (règle d'usage)

| Rôle | Token | Poids |
|---|---|---|
| Titre de page | `--fs-xl`, `--track-tight` | 600 |
| Titre section h2 | 16px (`--fs-lg`) | 600 |
| Titre fiche/drawer h2 | 17px (chiffre dur, local) | 600 |
| Corps | `--fs-md` | 400 |
| Méta | `--fs-sm`, `--muted` | 400 |
| En-têtes tableaux | `--fs-xs` | 500 |
| Mono | `.mono` 12.5px | 400 |

## Grammaire des composants partagés

- **Boutons** : `.btn` (base, surface + bord hairline) ; variantes
  `--primary` (accent plein), `--ghost` (tertiaire, transparent → hover),
  `--small` (tokens `*-sm`), `--danger` (plein, survol `--danger-strong`),
  `--danger-outline`, `--danger-text`, `--block`. États : hover (bord
  `--ink-2` + `--steel-2`), press (translateY 1px), disabled (45 %
  opacité/primary : steel + muted), focus-visible (outline 2px `--signal`,
  offset 2px — global), loading = `.spinner` courantColor.

- **Champs** : `.field` (label 13px medium, `--field-*`),
  `input/select` bord `--field-line`, focus global, invalid =
  `aria-invalid` → bord 2px danger (login). Placeholders `#8a94a1`.

- **Menus contextuels** : `.menu-panel` (`--shadow-2`, `--z-menu`),
  items 13px hover `--steel-2`, disabled `--faint`, danger séparé par un
  liseré (`--line`) — hairline avant première entrée destructive.

- **Modales** : `<dialog class="dialog">` natif, `::backdrop` sombre 45 %,
  `--shadow-3`, en-tête `--steel-2`. Drawer : `--z-drawer`, scrim dédié.

- **Notifications** : `.toasts` (`--z-toast`, top-bar sous ruban) ; le toast
  `.toast` bord gauche codé : `ok | info (accent) | error` + texte, jamais la
  couleur seule. Motion-safe (`prefers-reduced-motion`).

- **Badges/états** : `.chip-*` (fond doux + texte), `.status` (pastille +
  MOT — le mot obligatoire pour la barrière « not colour alone »).

- **Tables** : `.table` (admin), `.ledger` (grille fichiers), en-têtes
  `--fs-xs` accent `--muted` ; tri `.sort-head` + `.sort-head-active`.

## Icônes (convention)

SVG inline `stroke="currentColor"`, `fill="none"`, `stroke-width="1.8"`.
Tailles canoniques : **14** (méta, footer), **16** (petit footer), **18**
(nav/actions), **24** (viewBox par défaut). Toujours `aria-hidden="true"`.

## Ce qui est expressément écrit hors token (et pourquoi)

Gabarits de page (`--content-width`, `.content` padding), tailles de
composants très contextuels (17px drawer title, `--band-h`, `--side-w`)
restent des valeurs locales documentées : les tokeniser à ce stade
n'apporterait aucune réutilisation réelle.

## Historique
- **v2.1 (2026-10-21, prompt 02)** : palette cible (#10151d / #f5f7fa /
  #172033), accent doré AA `#9d660d`, alias `--graphite` alignés, échelles
  espacement/contrôles/ombres/z/durées/typo ajoutées et consommées par
  `.btn/.field/.menu/.toast/.dialog/.drawer/.tray/.drop-overlay/.topbar`,
  `.alert-warn` ramené au sémantique `--warn`, suppression de la couche
  concurrente `vault-tokens.css` (0 consommateur, import retiré de
  `main.tsx`).
- Composants non modifiés : grid ledger/page-ref (`vault-workspace`,
  `register`), drawer hash, upload tray, cascade, preview, master mode.

## v3 — additions of the 2026-10-22 design pass

Method: real screenshots (light, dark, mobile), reviewed one by one, then fixed.
Only existing tokens are used.

- **Vault overview** (`.overview`, `.overview-tile`, `.meter`): real catalogue
  figures only. Meter tone follows the capacity watermark (`--ok` → `--warn` at
  75 % of it → `--danger` at it).
- **File tiles** (`.file-tile-{pdf,audio,image,video,archive,doc}`): a family →
  token pair (`--danger`, `--run`, `--ok`, `--warn`, `--signal`, neutral), each
  with its `-bg`/soft background.
- **Status pills** (`.status-{ok,warn,error}`): dot + word on a tinted pill; never
  colour alone.
- **Top bar**: dark in both themes, so its text uses fixed light values
  (`#e8ecf2`, role `#b8c1cd`, buttons `#d5dbe4`), not the page ink.
- **Native controls follow the theme**: `color-scheme` is set on `:root` (and per
  `data-theme` / `prefers-color-scheme`), otherwise checkboxes and selects stay
  white in the dark theme.
- **Sticky bar and scrolling**: `html { scroll-padding-top }` keeps scrolled-to
  and focused elements below the bar (WCAG 2.4.11).
- **Administration panels**: `.admin-page .section` becomes a card; table headers
  are small caps; `.callout` is the one accent-bordered note style.
- **Tray**: floating (docked full width under 640 px), body scrolls (max 40 vh,
  32 vh on mobile) so it cannot cover the page's own buttons.
- **Motion**: dialogs and overview tiles animate briefly and are static under
  `prefers-reduced-motion`.
- **Field borders** `--field-line` ≥ 3:1 (light `#7b8594`, dark `#5d6e83`); the
  focus ring is a real 2 px outline, not only a halo.
