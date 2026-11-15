import { describe, expect, it } from "vitest";
import {
  dedupeCascadeRoots,
  isDeletableStatus,
  planCascadeOps,
  planCascadeOpsForRoots,
  type CascadePlan,
} from "./cascade";

const folders = [
  { id: "a", name: "A", parent_id: null },
  { id: "b", name: "B", parent_id: "a" },
  { id: "c", name: "C", parent_id: "b" },
  { id: "d", name: "D", parent_id: null },
];

describe("isDeletableStatus", () => {
  it("n'accepte que les statuts que DELETE /objects autorise", () => {
    expect(isDeletableStatus("available")).toBe(true);
    expect(isDeletableStatus("pending")).toBe(true);
    // `verifying` est vivant mais refusé par l'API : il bloque la suppression.
    expect(isDeletableStatus("verifying")).toBe(false);
    expect(isDeletableStatus("deleted")).toBe(false);
    expect(isDeletableStatus(undefined)).toBe(true);
  });
});

describe("dedupeCascadeRoots", () => {
  it("ne garde que les racines qui ne sont pas déjà couvertes par un ancêtre", () => {
    const roots = [
      { id: "a", name: "A" },
      { id: "b", name: "B" },
      { id: "c", name: "C" },
      { id: "d", name: "D" },
    ];
    expect(dedupeCascadeRoots(roots, folders)).toEqual([
      { id: "a", name: "A" },
      { id: "d", name: "D" },
    ]);
  });

  it("garde l'ancêtre même si son descendant est listé en premier", () => {
    const roots = [
      { id: "c", name: "C" },
      { id: "a", name: "A" },
    ];
    expect(dedupeCascadeRoots(roots, folders)).toEqual([{ id: "a", name: "A" }]);
  });

  it("dédoublonne une racine répétée", () => {
    const roots = [
      { id: "d", name: "D" },
      { id: "d", name: "D" },
    ];
    expect(dedupeCascadeRoots(roots, folders)).toEqual([{ id: "d", name: "D" }]);
  });
});

const multiPlan: CascadePlan = {
  rootId: "a",
  rootName: "2 dossiers",
  roots: [
    { id: "a", name: "A" },
    { id: "d", name: "D" },
  ],
  folders: [
    { id: "a", name: "A", parentId: null, path: "Racine / A" },
    { id: "b", name: "B", parentId: "a", path: "Racine / A / B" },
    { id: "d", name: "D", parentId: null, path: "Racine / D" },
  ],
  objects: [
    { id: "f1", name: "f1.txt", folderId: "a", path: "Racine / A" },
    { id: "f2", name: "f2.txt", folderId: "b", path: "Racine / A / B" },
    { id: "f3", name: "f3.txt", folderId: "d", path: "Racine / D" },
    // Doublon volontaire : un objet ne doit produire qu'une seule opération.
    { id: "f2", name: "f2.txt", folderId: "b", path: "Racine / A / B" },
  ],
  fileCount: 4,
  folderCount: 1,
};

describe("planCascadeOpsForRoots", () => {
  it("ordonne fichiers, sous-dossier puis dossier, sur plusieurs racines", () => {
    const ops = planCascadeOpsForRoots(multiPlan);
    expect(ops.map((op) => `${op.kind}:${op.id}`)).toEqual([
      "object:f1",
      "object:f2",
      "folder:b",
      "folder:a",
      "object:f3",
      "folder:d",
    ]);
  });

  it("ne produit aucun doublon d'opération", () => {
    const ops = planCascadeOpsForRoots(multiPlan);
    const keys = ops.map((op) => `${op.kind}:${op.id}`);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("conserve le comportement mono-dossier de planCascadeOps", () => {
    const legacyPlan: CascadePlan = {
      rootId: "a",
      rootName: "A",
      folders: [
        { id: "a", name: "A", parentId: null, path: "Racine / A" },
        { id: "b", name: "B", parentId: "a", path: "Racine / A / B" },
      ],
      objects: [
        { id: "f1", name: "f1.txt", folderId: "a", path: "Racine / A" },
        { id: "f2", name: "f2.txt", folderId: "b", path: "Racine / A / B" },
      ],
      fileCount: 2,
      folderCount: 1,
    };
    expect(planCascadeOps(legacyPlan).map((op) => `${op.kind}:${op.id}`)).toEqual([
      "object:f1",
      "object:f2",
      "folder:b",
      "folder:a",
    ]);
  });
});
