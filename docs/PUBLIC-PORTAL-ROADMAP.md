# Roadmap — Portail public & Audiobook

> **Date :** 2026-11-24 · **Périmètre :** `PUBLIC_DOMAIN` (vitrine, catalogue, lecteur, profil), liens publics (`/s/`, `/f/`, `/m/`, `/p/`, HLS, sous-titres) et service `audiobook/`.
> **Source :** inventaire du code et des docs (preuves `fichier:ligne` dans chaque issue) + comparatif Spotify/Audible 2026.
> **Statut :** proposition de séquencement. Les 14 fiches sont publiées dans [le dépôt GitHub](https://github.com/digitaleflex/aura-storage/issues?q=label%3Aroadmap).

---

## 1. Étoile polaire

**Une bibliothèque audio personnelle, calme et sûre : on retrouve sa place en un geste, on ne perd jamais ses données, et l'interface s'efface devant le contenu.**

Trois conséquences concrètes :

1. **Confiance d'abord** — aucune page personnelle ne doit être servie depuis un cache public, aucune session ne doit laisser de traces après coup.
2. **Le lecteur est le produit** — accessibilité clavier et lecteur d'écran au même niveau que la qualité audio.
3. **L'intelligence existe déjà dans le code** — le service `audiobook` sait recommander ; le travail est de le brancher, pas de le réécrire.

---

## 2. Ce qui existe déjà (et qu'on ne refait pas)

Le portail est déjà plus riche qu'il n'y paraît : recherche et filtres, fiche livre avec extrait MP3 et métadonnées sociales, lecteur avec file d'attente, ±15 s, vitesse 0,5–3×, **minuteur de sommeil**, reprise automatique, Media Session et AirPlay, **signets** (50 max), favoris, reprise « autre appareil », **PWA avec téléchargement hors-ligne**, 3 vues de catalogue, profil public, OAuth Google + PKCE, robots/sitemap/CSP.

Les chantiers ci-dessous ciblent donc les **gaps réels**, pas des fonctionnalités déjà présentes.

---

## 3. Thèmes et fiches

### 🛡️ Thème Sécurité / Confidentialité — P0

| Issue | Sujet | Pourquoi |
|---|---|---|
| [#293](https://github.com/digitaleflex/aura-storage/issues/293) | Fiche livre personnalisée servie avec `Cache-Control: public` | HTML avec CSRF et favori potentiellement resservi à un autre auditeur |
| [#294](https://github.com/digitaleflex/aura-storage/issues/294) | Cache du service worker non purgé hors logout | Positions, favoris et `data-csrf` restent accessibles après suppression de compte |
| [#295](https://github.com/digitaleflex/aura-storage/issues/295) | Gate D-08 : `/m/<slug>` non révocable | Capability publique donnant le livre entier — bloquant avant contenu payant |
| [#296](https://github.com/digitaleflex/aura-storage/issues/296) | HLS/sous-titres sans limiteur, compteurs en mémoire | Contournement par plusieurs workers et par les routes média |

### ♿ Thème Accessibilité — P1

| Issue | Sujet |
|---|---|
| [#297](https://github.com/digitaleflex/aura-storage/issues/297) | Lecteur : `dialog`/focus trap, `aria-valuetext`, piste `<track>` VTT, touche Space, modales `window.prompt` |
| [#298](https://github.com/digitaleflex/aura-storage/issues/298) | Lien « aller au contenu » et `aria-current` sur les pages publiques |

### ⚡ Thème Performance — P1

| Issue | Sujet |
|---|---|
| [#299](https://github.com/digitaleflex/aura-storage/issues/299) | Catalogue paginé côté serveur et chapitres chargés à la demande |

### 🧠 Thème Intelligence / Recommandations — P1

| Issue | Sujet |
|---|---|
| [#300](https://github.com/digitaleflex/aura-storage/issues/300) | Brancher préférences + scoring + `reasons` du service `audiobook` sur l'étagère « Pour vous » |
| [#301](https://github.com/digitaleflex/aura-storage/issues/301) | Rendre le service audiobook testé, exposé et documenté |

### 🎧 Thème Produit / Écoute — P2

| Issue | Sujet |
|---|---|
| [#302](https://github.com/digitaleflex/aura-storage/issues/302) | Playlists privées |
| [#303](https://github.com/digitaleflex/aura-storage/issues/303) | Statistiques auditeur (Wrapped léger) |
| [#304](https://github.com/digitaleflex/aura-storage/issues/304) | Récap spoiler-free et enchaînement next-in-series |
| [#305](https://github.com/digitaleflex/aura-storage/issues/305) | Recherche en langage naturel / découverte conversationnelle |

### 📚 Thème Documentation — P2

| Issue | Sujet |
|---|---|
| [#306](https://github.com/digitaleflex/aura-storage/issues/306) | Mettre `PUBLIC-PORTAL.md` / `PUBLIC-PORTAL-UI.md` en phase avec le code |

---

## 4. Séquencement

| Phase | Objectif | Issues | Gate de sortie |
|---|---|---|---|
| **Phase 0 — Confiance** | Arrêter les fuites et les accès non voulus | #293, #294, #295, #296 | Tests HTTP sur les en-têtes de cache, purge du SW, slug révoqué, limiteur HLS |
| **Phase 1 — Qualité perçue** | Accessibilité et temps de rendu | #297, #298, #299 | Audit axe sans violation bloquante ; mesure avant/après sur 500 titres |
| **Phase 2 — Intelligence** | Consommer ce qui existe déjà | #300, #301 | Recommandations actives avec feature flag, tests du scoring, service exposé |
| **Phase 3 — Attachement** | Fonctions qui donnent envie de revenir | #302–#305 | Parcours complets testés de bout en bout |
| **Phase 4 — Vérité documentaire** | Doc alignée | #306 | Doc revue et liée aux issues |

**Règle de passage** : une phase n'est dite terminée que si ses issues sont fermées **avec preuve exécutée** (test, log daté ou mesure). Aucune fonctionnalité n'est comptée « livrée » sur la seule base d'un code présent.

---

## 5. Métriques de succès

| Mesure | Cible |
|---|---|
| Pages personnelles servies avec un cache public | **0** |
| Données personnelles récupérables après logout hors `POST /logout` | **0** |
| Violations axe bloquantes sur le lecteur | **0** |
| Temps de rendu du catalogue (500 titres) | Mesuré avant, puis en baisse |
| Part des auditeurs ayant au moins une reco « Pour vous » jouée | À instrumenter en phase 2 |
| Commandes HLS/sous-titres sans limiteur | **0** |

---

## 6. Hors périmètre (décisions déjà prises)

- **Jam / Blend / listening activity social** : trop lourd pour un stockage privé.
- **Character Guide / Interactive Story / Visual Explorer** : expérimentations éditoriales coûteuses.
- **Immersion Reading / Page Sync** : nécessite un partenariat eBook.
- **Paiement Stripe / abonnements (Lots 3-5 audiobook)** : reste conditionné à la levée du gate D-08 (#295) et à la restauration testée.

---

## 7. Sources

- `docs/PUBLIC-PORTAL.md`, `docs/PUBLIC-PORTAL-UI.md`
- `docs/audiobook/README.md`, `docs/audiobook/11-lot2-implementation.md`
- `api/public_ui.py`, `api/public_book.py`, `api/portal_assets/*`, `api/main.py`
- Annonces officielles Spotify Newsroom et Audible Newsroom (2026) pour le comparatif fonctionnel.
