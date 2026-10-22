import { useEffect, useState } from "react";
import { prettyJson, parseCsv, readTextHead } from "../lib/textPreview";
import type { TextFlavor } from "../lib/preview";

/** The first 256 KiB are enough to recognise a file; the rest is a download. */
export const TEXT_PREVIEW_BYTES = 256 * 1024;

type State =
  | { phase: "loading" }
  | { phase: "ready"; text: string; truncated: boolean }
  | { phase: "error" };

/**
 * Text, CSV or JSON, rendered as escaped text. If the browser cannot read the
 * storage URL directly (CORS), the file is shown in a sandboxed frame instead:
 * it is served as text/plain, which a browser never runs.
 */
export function TextPreview({
  url,
  flavor,
  name,
}: {
  url: string;
  flavor: TextFlavor;
  name: string;
}) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ phase: "loading" });
    readTextHead(url, TEXT_PREVIEW_BYTES, controller.signal).then(
      ({ text, truncated }) => setState({ phase: "ready", text, truncated }),
      () => {
        if (!controller.signal.aborted) setState({ phase: "error" });
      },
    );
    return () => controller.abort();
  }, [url]);

  if (state.phase === "loading") {
    return (
      <p className="muted" role="status">
        Lecture du début du fichier…
      </p>
    );
  }
  if (state.phase === "error") {
    return (
      <iframe
        className="preview-frame"
        src={url}
        sandbox=""
        title={`Aperçu texte de ${name}`}
        referrerPolicy="no-referrer"
      />
    );
  }

  const notice = state.truncated ? (
    <p role="status" className="alert preview-warn">
      Seul le début du fichier est affiché (256 Kio). Téléchargez-le pour le lire en entier.
    </p>
  ) : null;

  if (flavor === "csv") {
    const table = parseCsv(state.text);
    const [head, ...body] = table.rows;
    return (
      <>
        {notice}
        {table.clipped ? (
          <p role="status" className="muted">
            Tableau réduit à {table.rows.length} lignes et 30 colonnes au plus.
          </p>
        ) : null}
        <div className="preview-table-wrap">
          <table className="table preview-table">
            {head ? (
              <thead>
                <tr>
                  {head.map((cell, i) => (
                    <th key={i}>{cell}</th>
                  ))}
                </tr>
              </thead>
            ) : null}
            <tbody>
              {body.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  }

  // A truncated JSON document is not parseable: show it as received.
  const shown = flavor === "json" && !state.truncated ? (prettyJson(state.text) ?? state.text) : state.text;
  return (
    <>
      {notice}
      <pre className="preview-text" tabIndex={0} aria-label={`Contenu de ${name}`}>
        {shown}
      </pre>
    </>
  );
}
