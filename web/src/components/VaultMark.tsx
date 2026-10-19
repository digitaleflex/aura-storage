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
        fill="#E0A33A"
      />
      <path
        d="M4 16.5 L16 23.5 L28 16.5 L28 19.5 L16 26.5 L4 19.5 Z"
        fill="currentColor"
      />
      <path
        d="M4 22 L16 29 L28 22 L28 23.5 L16 30.5 L4 23.5 Z"
        fill="currentColor"
        opacity="0.55"
      />
    </svg>
  );
}
