/**
 * Gestion du tour d'accueil (onboarding) pour les nouveaux utilisateurs.
 *
 * L'onboarding s'affiche une seule fois : le premier login d'un utilisateur.
 * L'état est mémorisé dans localStorage sous la clé `aura_onboarding_seen`.
 */

const ONBOARDING_SEEN_KEY = "aura_onboarding_seen";

export function hasSeenOnboarding(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(ONBOARDING_SEEN_KEY) === "1";
}

export function markOnboardingSeen(): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(ONBOARDING_SEEN_KEY, "1");
}

export interface OnboardingStep {
  id: string;
  title: string;
  description: string;
  action: string;          // libellé du bouton d'action suggéré
  target?: string;         // route vers laquelle rediriger après l'action
}

export const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    id: "import",
    title: "Importer vos premiers fichiers",
    description:
      "Glissez-déposez vos fichiers ou cliquez sur « Importer » pour les ajouter à votre coffre AURA.",
    action: "Aller aux fichiers",
    target: "/",
  },
  {
    id: "share",
    title: "Partager un fichier ou un dossier",
    description:
      "Sélectionnez un fichier, cliquez sur « Partager » et envoyez le lien à vos destinataires. Aucun compte AURA n'est requis pour les recevoir.",
    action: "Voir les partages",
    target: "/shares",
  },
  {
    id: "trash",
    title: "Récupérer depuis la corbeille",
    description:
      "Un fichier supprimé va dans la corbeille. Vous pouvez le restaurer ou le purger définitivement à tout moment.",
    action: "Voir la corbeille",
    target: "/trash",
  },
  {
    id: "done",
    title: "Vous êtes prêt !",
    description:
      "Explorez votre coffre AURA en toute sécurité. Vos fichiers sont chiffrés au repos.",
    action: "Commencer",
    target: "/",
  },
];
