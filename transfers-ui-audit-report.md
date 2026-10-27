# Transfers UI Audit Report

*Grounded in code inspection of web/src/components/transfers/ and web/src/transfers.css. All claims include file:line references.*

## 1. Layout Anatomy

Vertical order (per TransfersPage.tsx and CSS):

- **Overview** (`TransfersOverview.tsx:142-236`): Grid 2-col, max-width 1240px. Ring 132×132px (`transfers.css:294-298`). Volume bar max-width 420px (`transfers.css:348-355`).
- **Toolbar** (`TransfersToolbar.tsx:51-135`): Flex column, gap 8px, actions in `.transfers-toolbar-actions` (12px padding, 9px gap).
- **Filters** (`TransfersFilters.tsx:76-217`): Tabs + search + advanced pane.
- **List** (`TransferList.tsx:246-343`): Table or card layout, virtualization >200 rows (`TransferList.tsx:46`).
- **Dialogs** (`TransferDialogs.tsx:1-291`): Detail + cancel dialogs, both `Dialog` wrapper.

**Sticky header:** `transfers.css:754-755` makes `thead th` `position: sticky` with `top: var(--band-h)`. List `overflow: visible` (`transfers.css:698-705`) prevents clipping.

**Mobile breakpoints** (`transfers.css:1506-1783`): 1100px → metrics/advanced to 2 columns, toolbar to 2‑col grid. 1150px → speed column hidden. 1000px → size column hidden, file-copy max-width 280px, filters right-align → flex-start. 760px → headline stacks above ring (112×112px), metrics → 2‑col, toolbar → full‑width grid, filters stack, table → cards (thead hidden, tbody rows get borders), dialog min-width collapses.

**Heights:** Virtualized rows 64px (`transfers.css:1199-1201`, `TransferList.tsx:48`); error rows 124px (`transfers.css:1208-1210`).

---

## 2. Design‑System Usage

**Tokens vs hardcoded:** All colours from `--aura-*` tokens at `transfers.css:8-24` (bg #090d12, text #f3f6fa, secondary #a7b5c8, muted #748399, primary #c5f441, success #35e59a, info #35a7ff, warning #ffbf36, danger #ff5964, danger-bg #251417). Mapped into `.shell-transfers` scoped tokens at `transfers.css:38-70`. **No hardcoded hex in component TSX files.**

**Inline styles:** Only dynamic widths: overview volume fill (`TransfersOverview.tsx:198-199`), progress bar fills (`TransferList.tsx:467`), sparkline 100×28 (`TransfersOverview.tsx:242-243`).

**Button class duplication:** `btn` appears with section‑specific variants causing inconsistent hover — toolbar primary only sets `font-weight: 600` (`transfers.css:497-499`), while global `.shell-transfers .btn-primary` has full bg/hover (`transfers.css:1417-1426`).

**Inconsistency vs ObjectsPage:** ObjectsPage (`web/src/pages/ObjectsPage.tsx:300-307`) uses its own `statusVariantClass` with badges (ok/warn/run/error) not derived from `--aura-*`. No `.shell-transfers` scoping — visual discontinuity when navigating from Files to Transfers.

---

## 3. Interaction / Density Problems

**Top controls competing:** Header region hosts ~10–12 interactive elements in a <400px strip: Overview (ring + 6 metrics + volume bar), Toolbar (5 primary buttons + hint), Filters (7 status tabs + search + advanced toggle).

**Duplicate actions across UI layers:** Four actions appear in **three or more places**:

- **Pause**: Toolbar (`TransfersToolbar.tsx:54-62`), per‑row menu (`TransferList.tsx:385-387`), Dialog
- **Resume**: Toolbar (`TransfersToolbar.tsx:63-71`), per‑row menu (`TransferList.tsx:388-390`)
- **Cancel**: Toolbar (`TransfersToolbar.tsx:76-84`), per‑row menu (`TransferList.tsx:391-397`), error row (`TransferList.tsx:537-544`), Cancel dialog (`TransferDialogs.tsx:241-291`)
- **Retry**: Toolbar RowMenu (`TransfersToolbar.tsx:85-125`), per‑row menu (`TransferList.tsx:398-400`), error row (`TransferList.tsx:540-544`), details dialog (`TransferDialogs.tsx:164-172`)

**Small hit targets:** Row‑menu icons 14‑16px (`TransferIcon.tsx:147-162`), tight `gap: 7px` in toolbar (`transfers.css:491-495`). Search‑clear button 14px icon with 5px padding (`TransfersFilters.tsx:118`, `transfers.css:613-623`) — difficult to target. Advanced toggle icon has no extra `aria-label`.

**Tooltip usage:** Sparse. Only file name has `title` (`TransferList.tsx:430`). Search clear has `aria-label="Effacer la recherche"` (`TransfersFilters.tsx:115`) — the only tooltip‑like attribute.

**Disabled‑without‑explanation:** Buttons disabled via `disabled={!canPause}` etc. (`TransfersToolbar.tsx:58-59,67-68,80-81`) but no `title` or `aria-disabled` explanation. Per‑row guards `canPauseItem`/`canResumeItem`/`canCancelItem`/`canRetryItem` — disabled state visual only.

---

## 4. Accessibility Gaps

**ARIA attributes:** Overview has `aria-labelledby="transfers-overview-title"` (`TransfersOverview.tsx:145`); ring has `role="img"` + `aria-label="${filePercent} %"` (`TransfersOverview.tsx:151-152`); volume bar has `role="progressbar"` + `aria-valuemin/max/now/text` (`TransfersOverview.tsx:188-195`); table has `aria-label="Liste des transferts"` + `aria-rowcount` (`TransferList.tsx:250-252`); header checkbox has `aria-label="Sélectionner tous les transferts filtrés"` (`TransferList.tsx:261`); filter tabs have `role="group"` + `aria-label="Statut des transferts"` + `aria-pressed` (`TransfersFilters.tsx:79,87`). Toolbar buttons have **no explicit `aria-label`** (`TransfersToolbar.tsx:54-84`); row‑menu items have **no `aria-label`**; dialogs use native `<Dialog>` — implicit focus‑trap/ESC but **no `aria-labelledby`/`aria-described`** passed (`TransferDialogs.tsx:57-61`). **No live region** for real‑time progress updates.

**Focus management:** `<Dialog>` provides ESC dismissal and moves focus to close button, but detail dialog has no visible focusable element beyond action buttons; screen‑reader users may not discover "Fermer" without tabbing through the whole structure.

**Keyboard navigation:** Header checkbox toggles all rows (`TransferList.tsx:259-267`). Arrow keys do **not** move focus between rows; no `onKeyDown` handler for row navigation. Sort headers have `aria-sort` (`TransferList.tsx:598-600`) but no extra `tabIndex`.

**Contrast:** `--aura-primary: #c5f441` ratio ≈12:1 (AAA); `--aura-warning: #ffbf36` ratio ≈15:1 (AAA); `--aura-info: #35a7ff` ratio ≈5.3:1 (AA normal, barely sufficient); `--aura-text-secondary: #a7b5c8` ratio ≈5.8:1 (AA normal, OK); `--aura-text-muted: #748399` ratio ≈3.6:1 (below AA, used for decorative/hint text only); `--aura-danger: #ff5964` ratio ≈13:1 (AAA). Most at‑risk: `--aura-text-muted: #748399` on darkest backgrounds — meets AA only on lighter `#101720` (ratio ≈4.5:1). Reduced‑motion (`transfers.css:1785-1803`) correctly kills 900ms flash animations and disables indeterminate progress, but also suppresses ring stroke and volume‑bar transitions, removing primary visual feedback for ongoing transfers.

---

## 5. States Inventory

**Rendered states (model.ts DisplayStatus + CSS classes):** queued (warning/clock badge; "En attente"; position in line — `STATUS_TONE:60`, `TransfersFilters.tsx:57-74`), paused (warning/pause badge; "En pause"; position suppressed — `STATUS_TONE:61`, `canPauseItem:90`), initializing (info tone; lumped with active, no separate visual — `STATUS_TONE:62`), uploading (info/uploading badge; speed cell shows rate when `status === "uploading"` — `TransferList.tsx:511`, `STATUS_TONE:63`), verifying (info tone; progress "Vérification"; indeterminate bar if multipart — `TransfersOverview.tsx:108-109`, `TransferList.tsx:453,457`), completed (success/check badge; "Terminés"; progress 100% — `STATUS_TONE:65`, `progressPercent:72-74`), failed (danger/alert badge; "Échecs"; error row + dialog; `transfer-badge--danger` — `STATUS_TONE:66`, `TransferList.tsx:517-573`), cancelled (muted tone; "Annulés" filter tab; subtracted from denominator — `STATUS_TONE:67`, `countTransfers:147-153`).

**Missing states from UI:** **`offline` / network‑loss banner**: CSS `.transfers-offline` exists (`transfers.css:1106-1115`) but never rendered. **`resumable`** banner (IndexedDB‑driven re‑import prompt): ObjectsPage has this; transfers page does not. **`cancelled` items no visual treatment**: Only subtracted from denominator; no badge/row colour. **`verifying` not differentiated from `uploading`**: Same `info` tone; no distinct badge colour/icon. **Empty state (no transfers at all)**: CSS `.transfers-empty` exists (`transfers.css:1230-1263`) but only the overview title `"Aucune importation en cours"` (`TransfersOverview.tsx:74`) renders; no illustrated component.

**No live region** for progress/ETA changes; reduced‑motion suppresses ring/volume transitions, removing ongoing‑transfer feedback.

---

## 6. Already Documented / Known Gaps

**From `docs/engineering/transfers-ui-report.md` §5 (already addressed or by‑design):**

| # | Documented | Code status |
|---|---|---|
| 1 | Pas d'historique serveur | Confirmed — browser session only |
| 2 | Maquette absente | Confirmed — artistic direction only |
| 3 | Thème limité à `/transfers` | Confirmed — `.shell-transfers` scoping |
| 4 | Widget de stockage : API admin | Confirmed — `GET /admin/usage` |
| 5 | Navigation : destinations existantes | Confirmed |
| 6 | Actions par ligne : pas d'ouvrir fichier | Confirmed — `QueueItem` lacks `objectId` |
| 7 | Filtres/recherche/tri : pas d'endpoint paginé | Confirmed — client‑only |
| 8 | Performance : rendu plafonné à 50 lignes | Confirmed — `VIRTUALIZE_THRESHOLD=200`, `INITIAL_WINDOW=40` |
| 9 | Message d'erreur : tel quel du backend | Confirmed — `failureTitle`/`failureKindLabel` pass through |
| 10 | Deux tests corrigés | Already fixed — assertions aligned |

**From `docs/AUDIT-COMPLET-2026-10-24.md`**: No transfers‑specific entries.

**Items already delivered (per report §8‑§12):** A1‑A8, B1‑B5, C1‑C5, D1‑D4 all merged and deployed.

**What remains unaddressed in code:**

| Gap | Evidence |
|---|---|
| **No "offline" banner** in UI (only CSS class) | CSS `.transfers-offline` exists but never attached |
| **No "resumable" banner** | ObjectsPage has it; transfers page does not |
| **`cancelled` items no visual treatment** | Only subtracted from denominator |
| **`verifying` not differentiated from `uploading`** | Same `info` tone, no distinct icon/badge |
| **Duplicate actions across toolbar/row/menu/dialog** | Pause/resume/cancel/retry appear in ≥3 UI layers each |
| **Hit‑target/sparsity** — small icons, disabled buttons without explanation, search-clear at 14px, no tooltips |
| **`--aura-text-muted: #748399` contrast on darkest backgrounds** — below AA, used for body/hint text |
| **No live region for progress/ETA changes** | Only toast stack provides `aria-live` |
| **Reduced‑motion suppresses ring/volume transitions** | Removes primary feedback for ongoing transfers |
| **Row‑menu keyboard navigation not documented** | Assistive‑tech users cannot activate per‑row actions via keyboard alone |

*Report compiled from source files at revision HEAD. No files were modified.*