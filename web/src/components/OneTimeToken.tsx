import { useState } from "react";

/**
 * Shows a machine-identity token exactly once. The token is never readable
 * again from the API (only its fingerprint is stored), so this panel is the
 * single opportunity to copy it.
 */
export function OneTimeToken({
  token,
  onDismiss,
}: {
  token: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="token-panel" role="alert" aria-labelledby="token-title">
      <h3 id="token-title">Jeton affiché une seule fois</h3>
      <p className="muted">
        Copiez-le maintenant et conservez-le en lieu sûr. AURA n'en stocke que
        l'empreinte : il ne pourra plus être réaffiché.
      </p>
      <code className="token-value">{token}</code>
      <div className="token-actions">
        <button type="button" className="btn btn-small" onClick={() => void copy()}>
          {copied ? "Copié ✓" : "Copier"}
        </button>
        <button type="button" className="btn btn-small" onClick={onDismiss}>
          J'ai copié le jeton
        </button>
      </div>
    </div>
  );
}
