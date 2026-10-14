/** Original AURA Vault mark: layered vault geometry (no third-party artwork). */
export function VaultMark({ size = 26 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="AURA Vault"
    >
      <path
        d="M4 11 L16 4 L28 11 L16 18 Z"
        fill="#2E7CF6"
      />
      <path
        d="M4 16.5 L16 23.5 L28 16.5 L28 19.5 L16 26.5 L4 19.5 Z"
        fill="#C5F441"
      />
      <path
        d="M4 22 L16 29 L28 22 L28 23.5 L16 30.5 L4 23.5 Z"
        fill="#8B96AC"
        opacity="0.7"
      />
    </svg>
  );
}
