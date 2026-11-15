import JSZip from "jszip";
import { api } from "./api";
import type { ObjectItem } from "./api";

/** Message renvoyé quand plus rien n'est téléchargeable dans la sélection. */
const EMPTY_SELECTION_MESSAGE =
  "La sélection ne contient aucun fichier téléchargeable.";

/** Erreur interne : permet au téléchargement mono-dossier de garder son
 * ancien message (« Le dossier est vide. ») sans changer l'API publique. */
class EmptyZipSelectionError extends Error {
  constructor() {
    super(EMPTY_SELECTION_MESSAGE);
    this.name = "EmptyZipSelectionError";
  }
}

/** Un dossier de l'arbre, réduit à ce dont la construction des chemins a besoin. */
export interface ZipFolderNode {
  id: string;
  name: string;
  parent_id: string | null;
}

/** Un objet rapatrié d'un dossier sélectionné (ou de ses sous-dossiers). */
export interface ZipObjectCandidate {
  id: string;
  display_name: string;
  folder_id: string | null;
  status?: string;
}

/** Un fichier sélectionné hors dossier : il ira à la racine de l'archive. */
export interface ZipSelectedFile {
  id: string;
  name: string;
  /** Statut catalogue quand il est connu : seuls les disponibles sont inclus. */
  status?: string;
}

/** Une entrée finale de l'archive, avec son chemin relatif. */
export interface ZipEntry {
  id: string;
  /** Chemin complet dans le ZIP (« NomRacine/SousDossier/fichier »). */
  path: string;
  name: string;
}

/**
 * Construit les entrées de l'archive à partir de l'arbre et des objets listés.
 *
 * Fonction pure (testable) : elle ne fait aucun appel réseau. Les objets non
 * disponibles sont ignorés, les identifiants sont dédoublonnés (un fichier
 * sélectionné en même temps que son dossier n'apparaît qu'une fois) et les
 * dossiers imbriqués sélectionnés ne dupliquent pas leur sous-arbre.
 */
export function buildZipEntries(input: {
  selectedFiles: readonly ZipSelectedFile[];
  selectedFolders: readonly { id: string; name: string }[];
  folders: readonly ZipFolderNode[];
  objects: readonly ZipObjectCandidate[];
}): ZipEntry[] {
  const children = new Map<string, ZipFolderNode[]>();
  const depthOf = new Map<string, number>();
  for (const folder of input.folders) {
    if (!folder.parent_id) continue;
    const bucket = children.get(folder.parent_id);
    if (bucket) bucket.push(folder);
    else children.set(folder.parent_id, [folder]);
    depthOf.set(folder.id, (depthOf.get(folder.parent_id) ?? 0) + 1);
  }

  // Chemin relatif (sous la racine sélectionnée) de chaque dossier du sous-arbre.
  const folderPaths = new Map<string, string[]>();
  const addSubtree = (rootId: string, rootName: string) => {
    const stack: Array<{ id: string; names: string[] }> = [
      { id: rootId, names: [safeSegment(rootName)] },
    ];
    while (stack.length > 0) {
      const entry = stack.pop();
      if (!entry || folderPaths.has(entry.id)) continue;
      folderPaths.set(entry.id, entry.names);
      for (const child of children.get(entry.id) ?? []) {
        stack.push({
          id: child.id,
          names: [...entry.names, safeSegment(child.name)],
        });
      }
    }
  };
  // Les racines ancêtres passent en premier : si un descendant est aussi
  // sélectionné, il est déjà couvert et garde son chemin complet.
  const orderedRoots = [...input.selectedFolders].sort(
    (left, right) => (depthOf.get(left.id) ?? 0) - (depthOf.get(right.id) ?? 0),
  );
  const addedRoots = new Set<string>();
  for (const root of orderedRoots) {
    if (addedRoots.has(root.id)) continue;
    addedRoots.add(root.id);
    addSubtree(root.id, root.name);
  }

  const entries: ZipEntry[] = [];
  // Tous les objets listés, qu'ils soient téléchargeables ou non : un fichier
  // en attente ne doit pas être ajouté une seconde fois à la racine du ZIP
  // simplement parce que son dossier contient aussi sa sélection.
  const knownIds = new Set(input.objects.map((object) => object.id));
  const addedIds = new Set<string>();

  for (const object of input.objects) {
    // Seuls les objets réellement téléchargeables entrent dans l'archive.
    if (object.status !== "available") continue;
    if (!object.folder_id) continue;
    const prefix = folderPaths.get(object.folder_id);
    if (!prefix) continue;
    if (addedIds.has(object.id)) continue;
    addedIds.add(object.id);
    entries.push({
      id: object.id,
      path: [...prefix, safeSegment(object.display_name)].join("/"),
      name: object.display_name,
    });
  }

  // Les fichiers sélectionnés hors dossier vont à la racine ; ceux déjà
  // couverts par un dossier sélectionné sont ignorés (dédoublonnage par id).
  for (const file of input.selectedFiles) {
    if (file.status !== undefined && file.status !== "available") continue;
    if (knownIds.has(file.id) || addedIds.has(file.id)) continue;
    addedIds.add(file.id);
    entries.push({
      id: file.id,
      path: safeSegment(file.name),
      name: file.name,
    });
  }

  return entries;
}

/** Neutralise les séparateurs de chemin dans un nom affiché : un nom contenant
 * « / » créerait une arborescence implicite et pourrait entrer en collision
 * avec un vrai sous-dossier. */
export function safeSegment(name: string): string {
  return name.replace(/[\\/]+/g, "-").trim() || "fichier";
}

/** Deux fichiers peuvent porter le même nom (le serveur l'autorise, et le mode
 * « aplatir » supprime les dossiers). JSZip écrase silencieusement un chemin
 * déjà pris : on alloue donc des chemins uniques (« nom (2).ext »). */
export function ensureUniqueZipPaths(
  entries: readonly ZipEntry[],
  flatten = false,
): ZipEntry[] {
  const used = new Set<string>();
  const out: ZipEntry[] = [];
  for (const entry of entries) {
    const wanted = flatten ? safeSegment(entry.name) : entry.path;
    let candidate = wanted;
    if (used.has(candidate)) {
      const slash = candidate.lastIndexOf("/");
      const directory = slash >= 0 ? candidate.slice(0, slash + 1) : "";
      const file = slash >= 0 ? candidate.slice(slash + 1) : candidate;
      const dot = file.lastIndexOf(".");
      const stem = dot > 0 ? file.slice(0, dot) : file;
      const extension = dot > 0 ? file.slice(dot) : "";
      let index = 2;
      while (used.has(`${directory}${stem} (${index})${extension}`)) index += 1;
      candidate = `${directory}${stem} (${index})${extension}`;
    }
    used.add(candidate);
    out.push({ ...entry, path: candidate });
  }
  return out;
}

/** Liste paginée de tous les objets d'un dossier (limite serveur : 100). */
async function listAllFolderObjects(folderId: string): Promise<ObjectItem[]> {
  const out: ObjectItem[] = [];
  let offset = 0;
  const limit = 100;
  // Garde-fou : un serveur qui ignorerait `offset` ne boucle jamais à l'infini.
  for (let guard = 0; guard < 1000; guard += 1) {
    const page = await api.listObjects({ folderId, limit, offset });
    out.push(...page.items);
    if (page.items.length < limit) break;
    offset += page.items.length;
  }
  return out;
}

/** Options internes (le menu dossier conserve son nom d'archive et son
 * ancien aplatissement). */
interface ZipDownloadOptions {
  archiveName?: string;
  /** Aplatit tous les chemins : comportement historique du menu « Dossier ». */
  flatten?: boolean;
}

/**
 * Télécharge une sélection (fichiers et/ou dossiers) en une archive ZIP.
 *
 * Pour chaque dossier sélectionné, tout son sous-arbre est listé et reproduit
 * dans l'archive sous « NomRacine/SousDossier/fichier ». Les fichiers
 * sélectionnés hors dossier sont ajoutés à la racine. Les objets non
 * téléchargeables (`status !== "available"`) sont ignorés.
 */
export async function downloadSelectionAsZip(
  input: {
    files: ZipSelectedFile[];
    folders: { id: string; name: string }[];
  },
  csrf: string,
  onProgress?: (progress: number) => void,
  options?: ZipDownloadOptions,
): Promise<void> {
  const tree = await api.listAllFolders();
  const folders: ZipFolderNode[] = tree.items.map((folder) => ({
    id: folder.id,
    name: folder.name,
    parent_id: folder.parent_id,
  }));
  const children = new Map<string, ZipFolderNode[]>();
  for (const folder of folders) {
    if (!folder.parent_id) continue;
    const bucket = children.get(folder.parent_id);
    if (bucket) bucket.push(folder);
    else children.set(folder.parent_id, [folder]);
  }

  // Tous les dossiers du sous-arbre, racines imbriquées dédoublonnées.
  const folderIds = new Set<string>();
  for (const root of input.folders) {
    const stack = [root.id];
    while (stack.length > 0) {
      const id = stack.pop();
      if (!id || folderIds.has(id)) continue;
      folderIds.add(id);
      for (const child of children.get(id) ?? []) stack.push(child.id);
    }
  }

  const objects: ObjectItem[] = [];
  for (const folderId of folderIds) {
    objects.push(...(await listAllFolderObjects(folderId)));
  }

  const rawEntries = buildZipEntries({
    selectedFiles: input.files,
    selectedFolders: input.folders,
    folders,
    objects,
  });
  const entries = ensureUniqueZipPaths(rawEntries, options?.flatten ?? false);
  if (entries.length === 0) {
    throw new EmptyZipSelectionError();
  }

  const zip = new JSZip();
  const total = entries.length;

  for (let index = 0; index < total; index += 1) {
    const entry = entries[index];
    if (!entry) continue;

    // Obtient une URL présignée pour télécharger le fichier
    const intent = await api.createDownloadIntent(entry.id, csrf);

    // Télécharge les bytes
    const response = await fetch(intent.download_url);
    if (!response.ok) {
      throw new Error(
        `Échec du téléchargement de ${entry.name}: ${response.status}`,
      );
    }
    const blob = await response.blob();

    zip.file(entry.path, blob);

    if (onProgress) {
      onProgress((index + 1) / total);
    }
  }

  // Génère le ZIP et déclenche le téléchargement
  const zipBlob = await zip.generateAsync({ type: "blob" });
  const url = URL.createObjectURL(zipBlob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const seed =
    input.folders[0]?.id ?? input.files[0]?.id ?? String(Date.now());
  anchor.download = options?.archiveName ?? `selection-${seed.slice(0, 8)}.zip`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Safari annule le téléchargement si l'URL est révoquée dans le même tour.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Télécharge un dossier entier en tant que fichier ZIP.
 *
 * Réutilise le même moteur que la sélection ; le menu dossier conserve son nom
 * d'archive et son ancien aplatissement des chemins. Un dossier sans fichier
 * disponible garde son message historique.
 */
export async function downloadFolderAsZip(
  folderId: string,
  csrf: string,
  onProgress?: (progress: number) => void,
): Promise<void> {
  const folder = await api.getFolder(folderId);
  try {
    await downloadSelectionAsZip(
      { files: [], folders: [{ id: folderId, name: folder.name }] },
      csrf,
      onProgress,
      { archiveName: `dossier-${folderId.slice(0, 8)}.zip`, flatten: true },
    );
  } catch (err) {
    if (err instanceof EmptyZipSelectionError) {
      throw new Error("Le dossier est vide.");
    }
    throw err;
  }
}
