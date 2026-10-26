import { describe, expect, it } from "vitest";
import { escapeCsv } from "./csv";

describe("escapeCsv", () => {
  it("keeps plain values untouched", () => {
    expect(escapeCsv("rapport.pdf")).toBe("rapport.pdf");
    expect(escapeCsv(42)).toBe("42");
  });

  it("quotes separators, quotes and newlines", () => {
    expect(escapeCsv("a;b")).toBe('"a;b"');
    expect(escapeCsv('he said "hi"')).toBe('"he said ""hi"""');
    expect(escapeCsv("line1\nline2")).toBe('"line1\nline2"');
  });

  it("neutralises spreadsheet formulas", () => {
    // A file named like a formula must never execute when the CSV is opened.
    expect(escapeCsv("=HYPERLINK(\"http://evil\")")).toBe(
      '"\'=HYPERLINK(""http://evil"")"',
    );
    expect(escapeCsv("+1+1")).toBe("'+1+1");
    expect(escapeCsv("-cmd")).toBe("'-cmd");
    expect(escapeCsv("@SUM(A1)")).toBe("'@SUM(A1)");
    expect(escapeCsv("\tsecret")).toBe('"\'\tsecret"');
  });
});
