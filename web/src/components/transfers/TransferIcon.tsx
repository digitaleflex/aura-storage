import type { ReactNode } from "react";

export type TransferIconName =
  | "pause"
  | "play"
  | "plus"
  | "close"
  | "search"
  | "sliders"
  | "dots"
  | "clock"
  | "gauge"
  | "queue"
  | "check"
  | "alert"
  | "retry"
  | "arrow-down"
  | "shield"
  | "trash"
  | "eye"
  | "chevron-down"
  | "upload"
  | "file"
  | "audio"
  | "video"
  | "image"
  | "pdf"
  | "archive";

const PATHS: Record<TransferIconName, ReactNode> = {
  pause: (
    <>
      <rect x="7" y="5" width="3" height="14" rx="0.8" />
      <rect x="14" y="5" width="3" height="14" rx="0.8" />
    </>
  ),
  play: <path d="M8 5.5 19 12 8 18.5Z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  sliders: (
    <>
      <path d="M4 7h5M13 7h7M4 17h9M17 17h3" />
      <circle cx="11" cy="7" r="2" />
      <circle cx="15" cy="17" r="2" />
    </>
  ),
  dots: (
    <>
      <circle cx="5.5" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="18.5" cy="12" r="1.4" fill="currentColor" stroke="none" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5.2l3.2 2" />
    </>
  ),
  gauge: (
    <>
      <path d="M4 18a8 8 0 1 1 16 0" />
      <path d="m12 14 4-4" />
    </>
  ),
  queue: <path d="M4 6h16M4 12h16M4 18h10" />,
  check: <path d="m5 13 4 4L19 7" />,
  alert: (
    <>
      <path d="M12 4 3.5 19h17Z" />
      <path d="M12 9v4.5M12 16.5v.01" />
    </>
  ),
  retry: (
    <>
      <path d="M4.5 12a7.5 7.5 0 1 1 2.2 5.3" />
      <path d="M4 20v-5.5h5.5" />
    </>
  ),
  "arrow-down": <path d="M12 5v14M6 13l6 6 6-6" />,
  shield: (
    <>
      <path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z" />
      <path d="m9.5 12 1.8 1.8 3.4-3.6" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" />
      <path d="M10 11v5M14 11v5" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  "chevron-down": <path d="m6 9 6 6 6-6" />,
  upload: <path d="M12 19V5M6 11l6-6 6 6" />,
  file: (
    <>
      <path d="M7 3h7l4 4v14H7Z" />
      <path d="M14 3v4h4M9.5 13h5M9.5 17h4" />
    </>
  ),
  audio: (
    <>
      <path d="M9 18V6.5l10-2V16" />
      <circle cx="6.5" cy="18" r="2.5" />
      <circle cx="16.5" cy="16" r="2.5" />
    </>
  ),
  video: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m10 9 5 3-5 3Z" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="8.5" cy="9.5" r="1.6" />
      <path d="m4 17 5-5 4 4 3-2.5 4 3.5" />
    </>
  ),
  pdf: (
    <>
      <path d="M7 3h7l4 4v14H7Z" />
      <path d="M14 3v4h4M9.5 12h5M9.5 15.5h5M9.5 19h3" />
    </>
  ),
  archive: (
    <>
      <path d="M4 4h16v5H4zM5.5 9v11h13V9" />
      <path d="M10 13h4" />
    </>
  ),
};

export function TransferIcon({
  name,
  size = 18,
  title,
  className,
}: {
  name: TransferIconName;
  size?: number;
  title?: string;
  className?: string;
}) {
  return (
    <svg
      className={className}
      aria-hidden={title ? undefined : "true"}
      role={title ? "img" : undefined}
      aria-label={title}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {PATHS[name]}
    </svg>
  );
}
