import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  actions,
  className,
}: EmptyStateProps) {
  return (
    <section className={["empty-state", className].filter(Boolean).join(" ")}>
      {icon ? (
        <span className="empty-state-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <h2>{title}</h2>
      {description ? <p className="muted">{description}</p> : null}
      {actions ? <div className="empty-state-actions">{actions}</div> : null}
    </section>
  );
}
