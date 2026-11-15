import { describe, expect, it } from "vitest";
import {
  buildZipEntries,
  ensureUniqueZipPaths,
  safeSegment,
  type ZipEntry,
} from "./zip";

const folders = [
  { id: "root", name: "Racine", parent_id: null },
  { id: "sub", name: "SousDossier", parent_id: "root" },
  { id: "other", name: "Autre", parent_id: null },
];

describe("buildZipEntries", () => {
  it("reproduit l'arborescence des sous-dossiers", () => {
    const entries = buildZipEntries({
      selectedFiles: [],
      selectedFolders: [{ id: "root", name: "Racine" }],
      folders,
      objects: [
        {
          id: "o1",
          display_name: "note.txt",
          folder_id: "root",
          status: "available",
        },
        {
          id: "o2",
          display_name: "photo.jpg",
          folder_id: "sub",
          status: "available",
        },
      ],
    });
    expect(entries.map((entry) => entry.path).sort()).toEqual([
      "Racine/SousDossier/photo.jpg",
      "Racine/note.txt",
    ]);
  });

  it("dédoublonne un fichier sélectionné seul et présent dans un dossier", () => {
    const entries = buildZipEntries({
      selectedFiles: [
        { id: "o1", name: "note.txt" },
        { id: "outside", name: "hors-dossier.txt" },
      ],
      selectedFolders: [{ id: "root", name: "Racine" }],
      folders,
      objects: [
        {
          id: "o1",
          display_name: "note.txt",
          folder_id: "root",
          status: "available",
        },
      ],
    });
    expect(entries).toHaveLength(2);
    expect(entries.filter((entry) => entry.id === "o1")).toEqual([
      { id: "o1", path: "Racine/note.txt", name: "note.txt" },
    ]);
    expect(entries.map((entry) => entry.path)).toContain("hors-dossier.txt");
  });

  it("distingue deux fichiers de même nom dans deux dossiers", () => {
    const entries = buildZipEntries({
      selectedFiles: [],
      selectedFolders: [{ id: "root", name: "Racine" }],
      folders,
      objects: [
        {
          id: "o1",
          display_name: "rapport.pdf",
          folder_id: "root",
          status: "available",
        },
        {
          id: "o2",
          display_name: "rapport.pdf",
          folder_id: "sub",
          status: "available",
        },
      ],
    });
    expect(entries.map((entry) => entry.path).sort()).toEqual([
      "Racine/SousDossier/rapport.pdf",
      "Racine/rapport.pdf",
    ]);
  });

  it("ignore les objets non téléchargeables et les dossiers non sélectionnés", () => {
    const entries = buildZipEntries({
      selectedFiles: [],
      selectedFolders: [{ id: "root", name: "Racine" }],
      folders,
      objects: [
        {
          id: "pending",
          display_name: "en-cours.bin",
          folder_id: "root",
          status: "pending",
        },
        {
          id: "elsewhere",
          display_name: "autre.txt",
          folder_id: "other",
          status: "available",
        },
      ],
    });
    expect(entries).toEqual([]);
  });

  it("ne remonte pas à la racine un fichier en attente déjà couvert par un dossier", () => {
    const entries = buildZipEntries({
      selectedFiles: [{ id: "pending", name: "en-cours.bin" }],
      selectedFolders: [{ id: "root", name: "Racine" }],
      folders,
      objects: [
        {
          id: "pending",
          display_name: "en-cours.bin",
          folder_id: "root",
          status: "pending",
        },
      ],
    });
    expect(entries).toEqual([]);
  });

  it("garde l'ancêtre en premier même si le descendant est listé avant", () => {
    const entries = buildZipEntries({
      selectedFiles: [],
      selectedFolders: [
        { id: "sub", name: "SousDossier" },
        { id: "root", name: "Racine" },
      ],
      folders,
      objects: [
        {
          id: "o2",
          display_name: "photo.jpg",
          folder_id: "sub",
          status: "available",
        },
      ],
    });
    expect(entries.map((entry) => entry.path)).toEqual([
      "Racine/SousDossier/photo.jpg",
    ]);
  });
});

describe("safeSegment", () => {
  it("neutralise les séparateurs de chemin", () => {
    expect(safeSegment("a/b\\c.txt")).toBe("a-b-c.txt");
    expect(safeSegment("   ")).toBe("fichier");
  });
});

describe("ensureUniqueZipPaths", () => {
  const entries: ZipEntry[] = [
    { id: "a", path: "Dossier/rapport.pdf", name: "rapport.pdf" },
    { id: "b", path: "Dossier/rapport.pdf", name: "rapport.pdf" },
    { id: "c", path: "Dossier/rapport.pdf", name: "rapport.pdf" },
  ];

  it("suffixe les collisions sans écraser un fichier", () => {
    expect(ensureUniqueZipPaths(entries).map((entry) => entry.path)).toEqual([
      "Dossier/rapport.pdf",
      "Dossier/rapport (2).pdf",
      "Dossier/rapport (3).pdf",
    ]);
  });

  it("suffixe aussi les collisions en mode aplati", () => {
    expect(
      ensureUniqueZipPaths(entries, true).map((entry) => entry.path),
    ).toEqual(["rapport.pdf", "rapport (2).pdf", "rapport (3).pdf"]);
  });

  it("gère un nom sans extension", () => {
    const result = ensureUniqueZipPaths([
      { id: "a", path: "README", name: "README" },
      { id: "b", path: "README", name: "README" },
    ]);
    expect(result.map((entry) => entry.path)).toEqual([
      "README",
      "README (2)",
    ]);
  });
});
