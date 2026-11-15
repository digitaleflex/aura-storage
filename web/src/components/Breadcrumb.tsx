import type { ReactNode } from "react";

export interface BreadcrumbItem {
  id: string | null;
  label: string;
  icon?: ReactNode;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  ariaLabel?: string;
  onSelect: (id: string | null) => void;
}

export function Breadcrumb({
  items,
  ariaLabel = "Fil d’Ariane",
  onSelect,
}: BreadcrumbProps) {
  return (
    <nav className="breadcrumb" aria-label={ariaLabel}>
      {items.map((item, index) => {
        const current = index === items.length - 1;
        return (
          <span key={item.id ?? "root"} className="crumb-item">
            {index > 0 ? (
              <span className="crumb-sep" aria-hidden="true">
                /
              </span>
            ) : null}
            <button
              type="button"
              className={current ? "crumb crumb-current" : "crumb"}
              aria-current={current ? "page" : undefined}
              onClick={() => onSelect(item.id)}
            >
              {item.icon ? (
                <span className="crumb-icon" aria-hidden="true">
                  {item.icon}
                </span>
              ) : null}
              <span className="crumb-label">{item.label}</span>
            </button>
          </span>
        );
      })}
    </nav>
  );
}
