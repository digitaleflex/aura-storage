import React from "react";

/** Registre minimal d'icônes (SVG 24×24, stroke). Étendre au fil des migrations. */
const ICONS: Record<string, React.ReactNode> = {
  menu: <path d="M3 12h18M3 6h18M3 18h18" />,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />,
  shield: <path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z" />,
  lock: (
    <>
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </>
  ),
  close: <path d="M18 6 6 18M6 6l12 12" />,
};

export interface IconProps {
  name: keyof typeof ICONS;
  size?: number;
  className?: string;
  ariaHidden?: boolean;
  title?: string;
}

export function Icon({ name, size = 18, className, ariaHidden = true, title }: IconProps) {
  return (
    <svg
      aria-hidden={ariaHidden}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      className={className}
      role={title ? "img" : undefined}
      aria-label={title}
    >
      {ICONS[name]}
    </svg>
  );
}