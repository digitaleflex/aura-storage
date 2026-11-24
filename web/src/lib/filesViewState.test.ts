import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearFilesView, loadFilesView, patchFilesView } from "./filesViewState";

/** In-memory stand-in: the module reads window.sessionStorage at call time. */
function fakeStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
  };
}

beforeEach(() => {
  vi.stubGlobal("window", { sessionStorage: fakeStorage() });
});

describe("tag filter persistence", () => {
  it("gives legacy saved views an empty tag filter", () => {
    window.sessionStorage.setItem(
      "aura-files-view-v1",
      JSON.stringify({ folderId: null, search: "note" }),
    );
    expect(loadFilesView()).toMatchObject({ search: "note", tagFilter: "", tagMode: "all" });
  });

  it("restores the tag filter and keeps the other filters on later patches", () => {
    patchFilesView({ tagFilter: "maths, l1", tagMode: "any", search: "note" });
    expect(loadFilesView()).toMatchObject({
      tagFilter: "maths, l1",
      tagMode: "any",
      search: "note",
    });

    // A scroll or filter write must not erase the tag the user typed.
    patchFilesView({ typeFilter: "image/*" });
    expect(loadFilesView()).toMatchObject({
      tagFilter: "maths, l1",
      tagMode: "any",
      search: "note",
      typeFilter: "image/*",
    });
  });

  it("drops the saved tag filter on explicit logout", () => {
    patchFilesView({ tagFilter: "maths" });
    clearFilesView();
    expect(loadFilesView()).toBeNull();
  });
});
