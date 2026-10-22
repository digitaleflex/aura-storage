import { test, expect } from "@playwright/test";
import { detectDelimiter, parseCsv, prettyJson, readTextHead } from "../src/lib/textPreview";
import { previewKind, textFlavor } from "../src/lib/preview";

test("CSV: quotes, doubled quotes, embedded newlines and CRLF", () => {
  const table = parseCsv('nom,note\r\n"Dupont, Jean","il a dit ""ok"""\r\n"ligne\nbrisée",3\r\n');
  expect(table.rows).toEqual([
    ["nom", "note"],
    ["Dupont, Jean", 'il a dit "ok"'],
    ["ligne\nbrisée", "3"],
  ]);
  expect(table.clipped).toBe(false);
});

test("CSV: the delimiter is detected, and rows/columns are bounded", () => {
  expect(detectDelimiter("a;b;c")).toBe(";");
  expect(detectDelimiter("a\tb\tc")).toBe("\t");
  expect(detectDelimiter("a,b;c,d")).toBe(",");
  expect(parseCsv("a;b\n1;2").rows).toEqual([["a", "b"], ["1", "2"]]);
  const many = Array.from({ length: 500 }, (_, i) => `r${i},x`).join("\n");
  const bounded = parseCsv(many, { maxRows: 50 });
  expect(bounded.rows).toHaveLength(50);
  expect(bounded.clipped).toBe(true);
  const wide = parseCsv(Array.from({ length: 40 }, (_, i) => `c${i}`).join(","), { maxCols: 30 });
  expect(wide.rows[0]).toHaveLength(30);
  expect(wide.clipped).toBe(true);
});

test("CSV: blank lines are not records and an unterminated quote does not hang", () => {
  expect(parseCsv("a,b\n\n\n1,2\n").rows).toEqual([["a", "b"], ["1", "2"]]);
  expect(parseCsv('a,"never closed\nstill').rows.length).toBeGreaterThan(0);
  expect(parseCsv("").rows).toEqual([]);
});

test("JSON is indented when valid and reported as null when not", () => {
  expect(prettyJson('{"a":[1,2],"b":null}')).toBe('{\n  "a": [\n    1,\n    2\n  ],\n  "b": null\n}');
  expect(prettyJson('{"a":')).toBeNull();
});

test("the kind and the flavour follow the content type", () => {
  expect(previewKind("video/mp4")).toBe("video");
  expect(previewKind("text/csv; charset=utf-8")).toBe("text");
  expect(previewKind("application/json")).toBe("text");
  expect(previewKind("text/html")).toBeNull();
  expect(previewKind("image/svg+xml")).toBeNull();
  expect(textFlavor("text/csv")).toBe("csv");
  expect(textFlavor("text/tab-separated-values")).toBe("csv");
  expect(textFlavor("application/json")).toBe("json");
  expect(textFlavor("text/markdown")).toBe("plain");
});

test("only the head of a large response is read, then the transfer is cancelled", async () => {
  const original = globalThis.fetch;
  let cancelled = false;
  let pulls = 0;
  globalThis.fetch = (async () =>
    new Response(
      new ReadableStream({
        pull(controller) {
          pulls += 1;
          controller.enqueue(new TextEncoder().encode("x".repeat(1024)));
        },
        cancel() {
          cancelled = true;
        },
      }),
      { status: 200 },
    )) as typeof fetch;
  try {
    const head = await readTextHead("https://s3.example/obj", 4096);
    expect(head.truncated).toBe(true);
    expect(head.text.length).toBe(4096);
    expect(cancelled).toBe(true);
    expect(pulls).toBeLessThan(20); // it did not keep reading
  } finally {
    globalThis.fetch = original;
  }
});

test("a small file is returned whole, and an HTTP error is an error", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = (async () => new Response("a,b\n1,2", { status: 200 })) as typeof fetch;
    expect(await readTextHead("https://s3.example/o", 4096)).toEqual({ text: "a,b\n1,2", truncated: false });
    globalThis.fetch = (async () => new Response("no", { status: 403 })) as typeof fetch;
    await expect(readTextHead("https://s3.example/o", 4096)).rejects.toThrow("HTTP 403");
  } finally {
    globalThis.fetch = original;
  }
});
