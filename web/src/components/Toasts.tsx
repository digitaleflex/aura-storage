import { useEffect, useState } from "react";

export interface Toast {
  id: number;
  kind: "ok" | "error" | "info";
  text: string;
  /** Optional action button (e.g. "Annuler" for undo). */
  action?: { label: string; onClick: () => void };
}

let nextToastId = 1;

export function makeToast(
  kind: Toast["kind"],
  text: string,
  action?: Toast["action"],
): Toast {
  nextToastId += 1;
  return { id: nextToastId, kind, text, action };
}

/** Toast stack (P1.2): feedback where the action happened, not pages away.
 * Info/ok auto-dismiss (~6 s); errors persist until dismissed. Respects
 * `prefers-reduced-motion` via CSS (no slide animation then). */
export function ToastStack({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div className="toasts" role="region" aria-label="Notifications" aria-live="polite" aria-atomic="false">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: (id: number) => void;
}) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setVisible(true));
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (toast.kind !== "error") {
      timer = setTimeout(() => onDismiss(toast.id), 6000);
    }
    return () => {
      cancelAnimationFrame(frame);
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [toast.id, toast.kind, onDismiss]);
  return (
    <div
      role={toast.kind === "error" ? "alert" : "status"}
      className={`toast toast-${toast.kind}${visible ? " toast-in" : ""}`}
    >
      <span className="toast-text">{toast.text}</span>
      {toast.action ? (
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={() => {
            toast.action!.onClick();
            onDismiss(toast.id);
          }}
        >
          {toast.action.label}
        </button>
      ) : null}
      <button
        type="button"
        className="btn btn-ghost btn-small"
        aria-label="Fermer la notification"
        onClick={() => onDismiss(toast.id)}
      >
        ×
      </button>
    </div>
  );
}
