import React from "react";

/** Registre minimal d'icônes (SVG 24×24, stroke). Étendre au fil des migrations. */
const ICONS = {
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
  transfer: (
    <>
      <path d="M7 20V5M7 20l-3-3M7 20l3-3" />
      <path d="M17 4v15M17 4l-3 3M17 4l3 3" />
    </>
  ),
  dashboard: (
    <>
      <path d="M3 12h4l2-6 4 12 2-6h6" />
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
    </>
  ),
  pulse: <path d="M3 12h4l2-6 4 12 2-6h6" />,
  share: (
    <>
      <path d="M4 12v1a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-1" />
      <path d="M12 4v16" />
      <path d="M8 12h8" />
    </>
  ),
  trash: (
    <>
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <path d="M12 17h.01" />
    </>
  ),
  home: <path d="M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />,
  monitor: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </>
  ),
  "density-comfortable": (
    <>
      <rect x="3" y="4" width="18" height="6" rx="1.5" />
      <rect x="3" y="14" width="18" height="6" rx="1.5" />
    </>
  ),
  "density-compact": (
    <>
      <rect x="3" y="4" width="18" height="3.5" rx="1" />
      <rect x="3" y="10.25" width="18" height="3.5" rx="1" />
      <rect x="3" y="16.5" width="18" height="3.5" rx="1" />
    </>
  ),
  search: <path d="M21 21l-4.3-4.3M17 11a6 6 0 1 1-12 0 6 6 0 0 1 12 0z" />,
  sidebar: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="M9 4v16" />
    </>
  ),
} satisfies Record<string, React.ReactNode>;

export type IconName = keyof typeof ICONS;

export interface IconProps {
  name: IconName;
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
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={title ? "img" : undefined}
      aria-label={title}
    >
      {ICONS[name]}
    </svg>
  );
}