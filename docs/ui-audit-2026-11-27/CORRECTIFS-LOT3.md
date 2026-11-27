# Correctifs lot 3 — portail public AURA

**Date :** 27 novembre 2026  
**Références :** [`AUDIT-UI-PORTAIL.md`](AUDIT-UI-PORTAIL.md), [`CORRECTIFS-LOT1.md`](CORRECTIFS-LOT1.md), [`CORRECTIFS-LOT2.md`](CORRECTIFS-LOT2.md)  
**Tests :** `101 passed`.

---

## 1. Ce qui a été corrigé

### Extrait audio : un seul langage de lecteur

- La fiche livre n’affiche plus le lecteur `<audio controls>` natif (chrome gris/bleu du navigateur).
- L’extrait utilise désormais les contrôles AURA : bouton lecture/pause rond en encre, temps courant, barre de progression bronze, durée totale.
- Le `<audio>` reste dans le DOM mais masqué ; `preview.js` gère lecture/pause, `timeupdate`, seek et fin d’extrait.
- Le bouton et la barre sont accessibles : `aria-label`, `aria-valuetext`, cibles de 40 px.
- Un fallback `<noscript>` conserve un lecteur natif si JavaScript est désactivé.
- Le blocage « Enregistrer sous… » est conservé (`controlsList="nodownload"`, `disablePictureInPicture`, clic droit bloqué).

Test fonctionnel : avec un WAV de 2 s, le bouton passe bien en pause, `currentTime` avance, la durée réelle remplace la durée estimée et le seek reflète la position.

### Libellés du lecteur

- « Off » → « Aucun » dans le minuteur de sommeil.
- « File » → « File d’attente ».
- « Premium » n’est plus une pastille encre qui ressemble à un bouton : c’est un badge contour discret dans la barre sombre.
- Le reste des libellés reste en français.

### Carrousels : état des flèches

- Les flèches précédent/suivant sont désactivées aux extrémités (`disabled`), avec opacité réduite et curseur par défaut.
- L’état est recalculé au chargement, au scroll, au redimensionnement et après un clic.
- Le seuil tient compte du `scroll-snap` (offset de 2 px) : au départ, « précédent » est bien désactivé.
- Vérifié au navigateur : au début `prev=true, next=false` ; à la fin `prev=false, next=true`.

### Échelle de rayons

Tokens ajoutés dans le thème du portail :

```css
--r-xs:4px; --r-sm:8px; --r-md:14px; --r-lg:22px;
--r-pill:999px; --r-cover:3px;
```

Application aux composants principaux :

- surfaces (hero, cartes, panneaux, recherche, aperçu, file, dialogues, récapitulatif) : `--r-md` 14 px ;
- contrôles (bouton Google, champs, selects, notes, boutons d’icône) : `--r-sm` 8 px ;
- pastilles et pilules : `--r-pill` 999 px ;
- jaquettes : `--r-cover` 3 px (exception « presque carré » documentée).

Les valeurs historiques 10/12/16 restent possibles dans les composants legacy non concernés, mais les surfaces et contrôles visibles passent à l’échelle 8/14.

---

## 2. Avant / après

| Point | Avant | Après |
|---|---|---|
| Extrait | `<audio controls>` natif | Contrôles AURA + `<noscript>` |
| Sommeil | « Off » | « Aucun » |
| File | « File » | « File d’attente » |
| Premium | Pastille encre type bouton | Badge contour |
| Flèches carrousel | Toujours actives | Désactivées aux extrémités |
| Rayons | 10/12/16/999 | 8/14/999 + jaquettes 3 |

**Captures après lot 3 :** [`evidence-after-lot3/`](evidence-after-lot3/) (8 écrans).

---

## 3. Ce qui reste ouvert

- **Palette des jaquettes** : quatre teintes pastel cohérentes et contrastées ; la variante « jaquettes profondes et sémantiques » reste une décision de direction.
- **Duplication de titre** : le titre reste sur la jaquette et sous la carte ; c’est un choix de composition.
- **Composants legacy** : quelques rayons 10/12/16 subsistent dans des panneaux secondaires non repris dans cette passe.
- **Revue indépendante après lot 3** : non refaite ; vérifications par rendu Chromium, tests Playwright ciblés et tests Python.

---

## 4. Vérification

```text
101 passed in 24,74s
```

Vérifications navigateur :

- extrait : lecture, pause, durée, seek, libellé du bouton ;
- carrousels : `disabled` au début et à la fin ;
- lecteur mobile : options visibles, « File d’attente », « Aucun », badge Premium ;
- accueil, filtres, fiche livre et profil : pas de régression de rayons ou de contraste.

Les 404 visibles dans les captures locales (`/extrait`, `/covers`, `/sw.js`, `/api/public/*`, `/m/x.mp3`) sont des artefacts du serveur statique d’audit, pas des défauts du portail.
