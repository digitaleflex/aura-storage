import JSZip from "jszip";
import { api } from "./api";

/**
 * Télécharge un dossier entier en tant que fichier ZIP.
 *
 * Récupère tous les objets du dossier, télécharge chacun via une URL
 * présignée, les ajoute à une archive JSZip, puis déclenche le
 * téléchargement de l'archive complète.
 *
 * @param folderId - ID du dossier à télécharger
 * @param csrf - Token CSRF de la session courante
 * @param onProgress - Callback optionnel de progression (0 à 1)
 */
export async function downloadFolderAsZip(
  folderId: string,
  csrf: string,
  onProgress?: (progress: number) => void,
): Promise<void> {
  // Récupère tous les objets du dossier (pagination si nécessaire)
  const allItems: Array<{
    id: string;
    display_name: string;
    size_bytes: number;
  }> = [];
  let offset = 0;
  const limit = 100;

  for (;;) {
    const response = await api.listObjects({
      folderId,
      limit,
      offset,
    });
    allItems.push(
      ...response.items.map((item) => ({
        id: item.id,
        display_name: item.display_name,
        size_bytes: item.size_bytes ?? 0,
      })),
    );

    if (response.items.length < limit) break;
    offset += limit;
  }

  if (allItems.length === 0) {
    throw new Error("Le dossier est vide.");
  }

  const zip = new JSZip();
  const total = allItems.length;

  for (let i = 0; i < total; i++) {
    const item = allItems[i];
    if (!item) continue;

    // Obtient une URL présignée pour télécharger le fichier
    const intent = await api.createDownloadIntent(item.id, csrf);

    // Télécharge les bytes
    const response = await fetch(intent.download_url);
    if (!response.ok) {
      throw new Error(
        `Échec du téléchargement de ${item.display_name}: ${response.status}`,
      );
    }
    const blob = await response.blob();

    // Ajoute au ZIP (les dossiers sont aplatis pour simplifier)
    zip.file(item.display_name, blob);

    if (onProgress) {
      onProgress((i + 1) / total);
    }
  }

  // Génère le ZIP et déclenche le téléchargement
  const zipBlob = await zip.generateAsync({ type: "blob" });
  const url = URL.createObjectURL(zipBlob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `dossier-${folderId.slice(0, 8)}.zip`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
