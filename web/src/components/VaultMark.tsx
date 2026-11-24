import { useId } from "react";

/** Marque AURA Vault — direction « Halo Vault » : monogramme A en voûte de
 *  coffre, halo d'aura et accent lime. Dessin original, sans élément tiers. */
export function VaultMark({ size = 26 }: { size?: number }) {
  // Identifiants uniques : plusieurs instances de la marque peuvent coexister
  // dans la même page (barre latérale, connexion, pages d'erreur).
  const uid = useId().replace(/:/g, "");
  const tile = `aura-vault-tile-${uid}`;
  const glow = `aura-vault-glow-${uid}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      role="img"
      aria-label="AURA Vault"
    >
      <defs>
        <linearGradient id={tile} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#10203a" />
          <stop offset="1" stopColor="#060d1a" />
        </linearGradient>
        <radialGradient id={glow}>
          <stop offset="0" stopColor="#2e7cf6" stopOpacity=".38" />
          <stop offset="1" stopColor="#2e7cf6" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect
        x="1"
        y="1"
        width="62"
        height="62"
        rx="17"
        fill={`url(#${tile})`}
        stroke="#1a2f52"
      />
      <circle cx="32" cy="32" r="28" fill={`url(#${glow})`} />
      <path
        d="M53.7 44.5 A25 25 0 1 1 44.5 10.4"
        stroke="#2e7cf6"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <circle cx="44.5" cy="10.4" r="3.2" fill="#c5f441" />
      <path d="M32 14 L50 50 H41 L32 27 L23 50 H14 Z" fill="#dbe4f3" />
      <rect x="19" y="38" width="26" height="4.6" rx="2.3" fill="#c5f441" />
    </svg>
  );
}
