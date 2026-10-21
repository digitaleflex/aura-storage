#!/usr/bin/env bash
# Applies docs/engineering/ISSUES-REVIEW-2026-10-18.md to GitHub.
#   bash scripts/apply-issues-review.sh            # dry run: prints the gh calls
#   bash scripts/apply-issues-review.sh --apply    # performs them
# Requires `gh auth login` with write access to the repository. Read the review
# first: it closes issues and opens new ones.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"
REPO="${AURA_REPO:-digitaleflex/aura-storage}"
NEW="docs/engineering/issues-2026-10-18"
REVIEW="docs/engineering/ISSUES-REVIEW-2026-10-18.md"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

run() {
  if ((APPLY)); then "$@"; else { printf 'DRY:'; printf ' %q' "$@"; printf '\n'; } >&2; fi
}
api() { run gh api -X "$1" "repos/$REPO/$2" "${@:3}"; }
comment() { api POST "issues/$1/comments" -f body="$2" >/dev/null; }
close() { # $1=issue $2=reason (completed|not_planned)
  api PATCH "issues/$1" -f state=closed -f state_reason="$2" >/dev/null
}
label() { local n="$1"; shift; local a=(); for l in "$@"; do a+=(-f "labels[]=$l"); done; api POST "issues/$n/labels" "${a[@]}" >/dev/null; }

echo "== labels"
for spec in "P0:b60205" "P1:d93f0b" "P2:fbca04" "status:code-done:0e8a16" \
            "status:needs-pilot-proof:5319e7" "status:blocked:000000"; do
  name="${spec%:*}"; color="${spec##*:}"
  api POST labels -f name="$name" -f color="$color" >/dev/null 2>&1 || true
done

echo "== milestones"
declare -A MS
for title in "M-Sécurité code" "M-Sauvegarde" "M-Pilote VPS" "M-Transfer Engine" "M-Console"; do
  if ((APPLY)); then
    MS[$title]="$(gh api "repos/$REPO/milestones?state=open&per_page=100" --jq ".[] | select(.title==\"$title\") | .number")"
    [[ -n "${MS[$title]}" ]] || MS[$title]="$(gh api -X POST "repos/$REPO/milestones" -f title="$title" --jq .number)"
  else
    MS[$title]="<$title>"; echo "DRY: create milestone '$title' if missing"
  fi
done
milestone() { api PATCH "issues/$1" -F milestone="${MS[$2]}" >/dev/null; }

echo "== new issues"
new_issue() { # $1=file $2=title $3=milestone, rest=labels
  local file="$1" title="$2" ms="$3"; shift 3
  local a=(); for l in "$@"; do a+=(-f "labels[]=$l"); done
  api POST issues -f title="$title" -F body=@"$NEW/$file" -F milestone="${MS[$ms]}" "${a[@]}" >/dev/null
}
new_issue N1-sse-at-rest.md "[P0][Security] SSE-S3 n'était pas appliqué aux uploads : chiffrer, refuser le clair, rechiffrer l'existant" "M-Sécurité code" P0 security bug status:code-done status:needs-pilot-proof
new_issue N2-security-hardening.md "[P0][Security] Sessions hachées, login à temps constant, CSP/HSTS, dashboard filtré, audit persistant" "M-Sécurité code" P0 security status:code-done status:needs-pilot-proof
new_issue N3-ci.md "[P1][CI] Build + typage + Playwright du front, image API, suite complète sur PostgreSQL" "M-Sécurité code" P1 testing status:code-done
new_issue N4-image-delivery.md "[P1][Ops] Livraison par images versionnées (GHCR) et retour arrière en une commande" "M-Pilote VPS" P1 operations
new_issue N5-async-integrity.md "[P1][Reliability] Vérification d'intégrité asynchrone au lieu de relire l'objet dans la requête" "M-Transfer Engine" P1 backend performance
new_issue N6-monitoring.md "[P1][Ops] Supervision : métriques Prometheus, alertes disque, âge de la dernière sauvegarde" "M-Sauvegarde" P1 operations
new_issue N7-least-privilege-s3.md "[P1][Security] Identités S3 à moindre privilège pour l'API et la sauvegarde" "M-Sécurité code" P1 security
new_issue N8-split-large-files.md "[P2][Maintenance] Découper ObjectsPage.tsx et api/main.py" "M-Console" P2 maintenance
new_issue N9-license.md "[P2][Decision] Choisir une licence" "M-Pilote VPS" P2 question

REF="Revue du 2026-10-18 : \`$REVIEW\`."
echo "== close: code criteria met, pilot proof moves to #10"
for n in 18 19 35 36 37 38; do
  label "$n" status:code-done status:needs-pilot-proof
  comment "$n" "Critères code remplis (voir commentaires précédents). La preuve pilote restante est suivie comme case dans #10. $REF"
  close "$n" completed
done
comment 63 "Livré : file bornée, progression par fichier, annulation, relance ciblée (\`web/src/lib/transfer.ts\`, \`web/e2e/upload-queue.spec.ts\`, \`web/e2e/transfer-engine.spec.ts\`). La section « État actuel » n'est plus vraie. $REF"
close 63 completed

echo "== duplicates"
dup() { label "$1" duplicate; comment "$1" "Doublon de #$2 ($3). $REF"; close "$1" not_planned; }
dup 22 35 "rôles, sessions, audit couverts par #35/#36/#38 ; l'identité S3 minimale est reprise dans une nouvelle issue"
dup 23 10 "recette UI sur le pilote = recette pilote unique"
dup 84 72 "multipart + reprise ; l'ordonnanceur borné est reporté dans #72"
dup 89 90 "une seule release gate"

echo "== updates (comment with the proposed change; edit the body by hand)"
upd() { comment "$1" "Mise à jour proposée — $2 $REF"; }
upd 8 "SSE-S3 n'est appliqué que si la requête le demande (constat local SeaweedFS 4.48). Preuve attendue : smoke test **et** upload via l'app avec \`ServerSideEncryption=AES256\` ; rechiffrement de l'existant. Voir la nouvelle issue SSE."
upd 9 "Implémentation sur \`feat/offsite-backup\` : pg_dump + audit + rclone crypt hors site, restore-check non destructif, restauration complète testée en local (\`docs/verification-log-2026-10-18-backup-restore.md\`). Reste : fournisseur, première sauvegarde et restauration réelles, planification, alerte."
upd 10 "Devient la recette pilote unique : ajouter une case par preuve pilote due de #18 #19 #21 #35–#40 #63 #64 et des nouvelles issues sécurité."
upd 21 "Hôte réel \`app.aura-storage.eurinhash.com\`. Routage et HTTPS livrés ; HSTS/CSP sur \`fix/security-hardening\`. Reste la preuve pilote."
upd 40 "Retirer ce qui est livré par M07. Reste : limiteurs en mémoire (perdus au redémarrage, non partagés), métriques et alertes (nouvelle issue supervision)."
upd 42 "Transformer en épopée : liens vers #72, #82–#88 ; retirer les cases déjà livrées."
upd 58 "AdminPage.tsx et 3 specs Playwright admin existent : lister ce qui manque au lieu de « aucune interface »."
upd 82 "\`docs/engineering/82-transfer-engine-audit.md\` existe : cocher ce qui est couvert ou fermer."
upd 83 "États, commit idempotent et commits concurrents sont livrés et testés. Recentrer sur : intégrité asynchrone (nouvelle issue), timeout ambigu, panne PostgreSQL."
upd 20 "#62 est fermée : cocher."

echo "== milestones on existing issues"
for n in 4 5 6 7 8 10 11; do milestone "$n" "M-Pilote VPS"; done
milestone 9 "M-Sauvegarde"; milestone 40 "M-Sauvegarde"; milestone 41 "M-Sécurité code"
for n in 42 72 82 83 85 86 87 88 90; do milestone "$n" "M-Transfer Engine"; done
for n in 20 21 58 59 64 65 66; do milestone "$n" "M-Console"; done

((APPLY)) || echo "Dry run only. Re-run with --apply to perform these calls."
