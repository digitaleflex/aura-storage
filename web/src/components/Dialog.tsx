import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/**
 * Accessible modal built on the native <dialog> element: Escape closes it and
 * the page behind it is inert. Controlled by the `open` prop.
 */
export function Dialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      // showModal() focuses the first focusable element, which is the header's
      // "Fermer" button: typing a name then Enter would close the dialog. Move
      // focus to the first field of the body when there is one.
      el.querySelector<HTMLElement>(
        ".dialog-body input:not([type=hidden]):not([disabled]), .dialog-body select, .dialog-body textarea",
      )?.focus();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open]);

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} aria-labelledby="dlg-title">
      <div className="dialog-head">
        <h2 id="dlg-title">{title}</h2>
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={onClose}
          aria-label="Fermer"
        >
          Fermer
        </button>
      </div>
      <div className="dialog-body">{children}</div>
    </dialog>
  );
}

/**
 * A button that asks for confirmation in a dialog before running `onConfirm`.
 * Used for destructive or irreversible actions (delete, purge, revoke).
 */
export function ConfirmAction({
  label,
  title,
  message,
  confirmLabel,
  onConfirm,
  pending = false,
  disabled = false,
  danger = false,
  className,
}: {
  label: string;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
  disabled?: boolean;
  danger?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className={className ?? "btn btn-small"}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        {label}
      </button>
      <Dialog open={open} title={title} onClose={() => setOpen(false)}>
        <div className="dialog-text">{message}</div>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={() => setOpen(false)}>
            Annuler
          </button>
          <button
            type="button"
            className={danger ? "btn btn-danger" : "btn btn-primary"}
            disabled={pending}
            onClick={() => {
              setOpen(false);
              onConfirm();
            }}
          >
            {pending ? "En cours…" : confirmLabel}
          </button>
        </div>
      </Dialog>
    </>
  );
}
