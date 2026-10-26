import { ApiError, PresignedUploadError } from "./api";

/**
 * One place that turns a failure into a sentence a person can act on.
 *
 * The API answers in English for developers ("object not available"); the
 * interface must say, in French, what happened and what to do next. Unknown
 * details fall back to a message chosen by the caller, never to a raw code.
 */
const KNOWN_DETAILS: Record<string, string> = {
  "object not found": "Ce fichier n'existe plus ou n'est pas visible pour votre compte.",
  "object not available": "Ce fichier n'est pas encore disponible : son envoi ou sa vérification n'est pas terminé.",
  "object not deletable": "Ce fichier ne peut pas être supprimé dans son état actuel.",
  "object not committable": "Cet envoi ne peut plus être validé (annulé, expiré ou déjà traité).",
  "object is not in the trash": "Ce fichier n'est pas dans la corbeille.",
  "object was never uploaded": "Ce fichier a été supprimé avant la fin de son envoi : il n'y a rien à restaurer.",
  "upload intent expired": "Le délai d'envoi a expiré. Relancez l'import de ce fichier.",
  "upload not found at storage": "Le fichier n'est pas arrivé au stockage. Relancez l'envoi.",
  "uploaded size does not match storage": "Le fichier reçu est incomplet ou différent de l'original. Relancez l'envoi.",
  "object not encrypted at rest": "Le stockage n'a pas chiffré ce fichier : il a été refusé par sécurité.",
  "object exceeds maximum allowed size": "Ce fichier dépasse la taille maximale autorisée.",
  "too many pending uploads": "Trop d'envois en cours. Attendez la fin de quelques-uns puis réessayez.",
  "storage capacity reached": "Espace de stockage plein : import refusé. Libérez de la place ou contactez l'administrateur.",
  "storage delete failed": "Le stockage n'a pas pu supprimer le fichier. La fiche est conservée ; réessayez plus tard.",
  "storage unavailable": "Le stockage ne répond pas. Réessayez dans un instant.",
  "folder not empty": "Ce dossier n'est pas vide.",
  "folder not found": "Ce dossier n'existe plus.",
  "preview not supported for this content type": "Ce type de fichier ne peut pas être affiché dans le navigateur.",
  "invalid credentials": "Identifiant ou mot de passe incorrect.",
  "too many login attempts": "Trop de tentatives de connexion. Patientez une minute.",
  "master mode required": "Activez le mode maître pour cette action.",
  "password does not match": "Mot de passe incorrect.",
  forbidden: "Action non autorisée pour votre compte.",
};

export function describeError(err: unknown, fallback: string): string {
  if (err instanceof PresignedUploadError) {
    if (err.kind === "network") return "Connexion au stockage interrompue.";
    if (err.kind === "expired") return "Le lien d'envoi a expiré.";
    if (err.kind === "aborted") return "Envoi annulé.";
    if (err.status === 499) {
      return "L'envoi a été interrompu par le proxy (délai d'attente dépassé). Réessayez : seule la partie concernée sera renvoyée.";
    }
    return fallback;
  }
  if (err instanceof ApiError) {
    const known = KNOWN_DETAILS[err.detail];
    if (known) return known;
    if (err.status === 401) return "Votre session a expiré. Reconnectez-vous.";
    if (err.status === 403) return "Action non autorisée pour votre compte.";
    if (err.status === 404) return "Élément introuvable : il a peut-être déjà été supprimé.";
    if (err.status === 409) return `${fallback} L'élément a changé entre-temps : actualisez la page.`;
    if (err.status === 413) return "Fichier trop volumineux.";
    if (err.status === 429) return "Trop de requêtes en peu de temps. Patientez un instant puis réessayez.";
    if (err.status === 507) return KNOWN_DETAILS["storage capacity reached"]!;
    if (err.status >= 500) return "Le serveur rencontre un problème. Réessayez dans un instant.";
    return fallback;
  }
  // fetch() rejects with a TypeError when the network or server is unreachable.
  if (err instanceof TypeError) {
    return "Connexion au serveur impossible. Vérifiez votre réseau puis réessayez.";
  }
  if (err instanceof Error && err.message === "Session expirée.") {
    return "Votre session a expiré. Reconnectez-vous.";
  }
  return fallback;
}
