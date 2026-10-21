import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

export interface RowMenuItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
}

/**
 * A quiet per-row action menu: one trigger instead of a row of buttons.
 * Closes on outside click, Escape and item selection. Destructive items are
 * highlighted, and their confirmation is owned by the caller's dialog so the
 * panel can safely unmount.
 *
 * Keyboard contract: the trigger opens the menu and focuses its first item;
 * Arrow keys move between items (Home/End jump to the edges), Escape closes
 * and returns focus to the trigger so the row keeps the user's place.
 */
export function RowMenu({ label, items }: { label: string; items: RowMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  function closeMenu(restoreFocus = false) {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }

  function enabledItems(): HTMLButtonElement[] {
    const panel = panelRef.current;
    if (!panel) return [];
    return Array.from(
      panel.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)'),
    );
  }

  useEffect(() => {
    if (!open) return;
    // Opening from the keyboard should land on the first action, not keep
    // focus on the trigger where Arrow keys would do nothing visible.
    const frame = requestAnimationFrame(() => enabledItems()[0]?.focus());

    function onPointerDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu(true);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function onPanelKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (
      event.key !== "ArrowDown" &&
      event.key !== "ArrowUp" &&
      event.key !== "Home" &&
      event.key !== "End"
    ) {
      return;
    }
    const buttons = enabledItems();
    if (buttons.length === 0) return;
    event.preventDefault();
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    let next: number;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = buttons.length - 1;
    else if (event.key === "ArrowDown") next = (current + 1) % buttons.length;
    else next = (current - 1 + buttons.length) % buttons.length;
    buttons[next]?.focus();
  }

  return (
    <div className="menu" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        className="menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((value) => !value)}
      >
        ⋯
      </button>
      {open ? (
        <div
          ref={panelRef}
          className="menu-panel"
          role="menu"
          aria-label={label}
          onKeyDown={onPanelKeyDown}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              className={item.danger ? "menu-item menu-item-danger" : "menu-item"}
              disabled={item.disabled}
              onClick={() => {
                // The action may open a modal; let the dialog own focus rather
                // than pulling it back to a trigger that is now inert.
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
