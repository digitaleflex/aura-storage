/**
 * Folder glyph: a single closed folder outline, drawn with the interface's own
 * geometry (no emoji, no third-party artwork). Inherits `currentColor`.
 */
export function FolderMark({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M3 7a3 3 0 0 1 3-3h3.1a2 2 0 0 1 1.6.8l1 1.3H18a3 3 0 0 1 3 3V17a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3z"
        fill="currentColor"
        opacity="0.9"
      />
      <path
        d="M3 10h18"
        stroke="#ffffff"
        strokeOpacity="0.55"
        strokeWidth="1.2"
      />
    </svg>
  );
}
