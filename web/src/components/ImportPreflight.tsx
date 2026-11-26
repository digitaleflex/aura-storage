import { useMemo } from "react";
import type { DuplicateReason, PreflightStatus } from "../lib/duplicateCheck";

export interface ImportPreflightItem {
  id: string;
  name: string;
  rel: string;
  size: number;
  root?: string;
  status: PreflightStatus;
  duplicateReason?: DuplicateReason;
  duplicateOf?: string;
}

interface ImportPreflightProps {
  items: ImportPreflightItem[];
  running: boolean;
  formatBytes: (bytes: number) => string;
  onRemove?: (id: string) => void;
}

const STATUS_LABEL: Record<PreflightStatus, string> = {
  queued: "En attente",
  checking: "Vérification",
  ready: "Vérifié",
  duplicate: "Doublon",
  error: "À revérifier",
};

function duplicateLabel(item: ImportPreflightItem): string {
  if (item.duplicateReason === "checksum") return "Doublon · empreinte identique";
  if (item.duplicateReason === "batch_checksum") return "Doublon dans le lot · empreinte identique";
  if (item.duplicateReason === "batch_name_size") return "Doublon dans le lot · nom + taille";
  return "Doublon · nom + taille identiques";
}

export function ImportPreflight({ items, running, formatBytes, onRemove }: ImportPreflightProps) {
  const groups = useMemo(() => {
    const byRoot = new Map<string, ImportPreflightItem[]>();
    for (const item of items) {
      const root = item.root || "Fichiers individuels";
      const group = byRoot.get(root) ?? [];
      group.push(item);
      byRoot.set(root, group);
    }
    return [...byRoot.entries()];
  }, [items]);

  const checked = items.filter((item) =>
    item.status === "ready" || item.status === "duplicate" || item.status === "error",
  ).length;
  const duplicates = items.filter((item) => item.status === "duplicate").length;
  const ready = items.filter((item) => item.status === "ready").length;
  const percent = items.length > 0 ? Math.round((checked / items.length) * 100) : 0;
  const indeterminate = running && checked === 0;
  const summary = running
    ? `Vérification en cours : ${checked} fichier sur ${items.length} traité, ${duplicates} doublon détecté.`
    : `Vérification terminée : ${ready} fichier prêt, ${duplicates} doublon détecté.`;

  if (items.length === 0) return null;

  return (
    <section
      className={`import-preflight${running ? " is-running" : ""}`}
      aria-labelledby="import-preflight-title"
      data-testid="import-preflight"
    >
      <div className="import-preflight-head">
        <div className="preflight-orbit" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="import-preflight-title">
          <h3 id="import-preflight-title">
            {running ? "Vérification en direct" : "Vérification terminée"}
          </h3>
          <p>
            {checked}/{items.length} fichier{items.length > 1 ? "s" : ""} traité
            {items.length > 1 ? "s" : ""} · rien n'est encore envoyé
          </p>
        </div>
        <div className="import-preflight-stats" aria-label="Résumé de la vérification">
          <span className="preflight-stat is-ready">
            <strong>{ready}</strong> prêt{ready > 1 ? "s" : ""}
          </span>
          <span className="preflight-stat is-duplicate">
            <strong>{duplicates}</strong> doublon{duplicates > 1 ? "s" : ""}
          </span>
        </div>
      </div>

      <div
        className={`preflight-progress${indeterminate ? " is-indeterminate" : ""}`}
        role="progressbar"
        aria-label="Progression de la vérification des doublons"
        aria-valuemin={0}
        aria-valuemax={items.length}
        aria-valuenow={indeterminate ? undefined : checked}
        aria-valuetext={indeterminate ? "Vérification en cours" : `${checked} sur ${items.length} fichiers vérifiés`}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <p className="visually-hidden" aria-live="polite" aria-atomic="true">
        {summary}
      </p>

      <div className="preflight-groups">
        {groups.map(([root, group]) => (
          <div className="preflight-group" key={root}>
            <div className="preflight-group-head">
              <span>{root}</span>
              <span>{group.length} fichier{group.length > 1 ? "s" : ""}</span>
            </div>
            <ul className="preflight-list">
              {group.map((item) => (
                <li
                  key={item.id}
                  className={`preflight-item is-${item.status}`}
                  data-testid="preflight-item"
                  data-status={item.status}
                >
                  <span className="preflight-status" aria-hidden="true">
                    {item.status === "checking" || item.status === "queued" ? (
                      <span className="preflight-spinner" />
                    ) : item.status === "ready" ? (
                      <span className="preflight-check">✓</span>
                    ) : item.status === "duplicate" ? (
                      <span className="preflight-copy">2×</span>
                    ) : (
                      <span className="preflight-alert">!</span>
                    )}
                  </span>
                  <span className="preflight-file">
                    <span className="preflight-name" title={item.rel}>{item.name}</span>
                    {item.rel !== item.name ? (
                      <span className="preflight-path">{item.rel}</span>
                    ) : null}
                  </span>
                  <span className="preflight-size">{formatBytes(item.size)}</span>
                  <span
                    className={`preflight-badge is-${item.status}`}
                    title={item.duplicateOf ? `Semblable à ${item.duplicateOf}` : undefined}
                  >
                    {item.status === "duplicate" ? duplicateLabel(item) : STATUS_LABEL[item.status]}
                  </span>
                  {onRemove ? (
                    <button
                      type="button"
                      className="preflight-remove"
                      aria-label={`Retirer ${item.rel}`}
                      onClick={() => onRemove(item.id)}
                    >
                      ×
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
