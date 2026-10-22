import { test, expect } from "@playwright/test";
import { frenchNote, healthDetail } from "../src/lib/adminText";

const fmt = (n: number) => `${n} o`;

test("a supervision line has no dangling separator and is in French", () => {
  expect(healthDetail({ uptime_s: 74 }, fmt)).toBe("démarrée depuis 74 s");
  expect(healthDetail({ latency_ms: 2 }, fmt)).toBe("2 ms");
  expect(healthDetail({ error: "unreachable" }, fmt)).toBe("injoignable");
  expect(healthDetail({ free_bytes: 5, note: "local process volume; not the object-store capacity" }, fmt)).toBe(
    "libres : 5 o · volume local du processus ; ce n'est pas la capacité du stockage d'objets",
  );
  expect(healthDetail({}, fmt)).toBe("");
});

test("an unknown server note is shown as received, never dropped", () => {
  expect(frenchNote("something new")).toBe("something new");
  expect(frenchNote(undefined)).toBe("");
});
