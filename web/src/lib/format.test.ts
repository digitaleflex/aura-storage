import { describe, expect, it } from "vitest";
import {
  fileExtension,
  formatBytes,
  formatDuration,
  formatRate,
  formatRemaining,
  parseMegabytes,
} from "./format";

describe("formatBytes", () => {
  it("formats zero and invalid values", () => {
    expect(formatBytes(0)).toBe("0 o");
    expect(formatBytes(-1)).toBe("—");
    expect(formatBytes(Number.NaN)).toBe("—");
  });
  it("uses binary units with one decimal", () => {
    expect(formatBytes(1024)).toBe("1.0 Ko");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 Mo");
    expect(formatBytes(1)).toBe("1 o");
  });
});

describe("formatRate", () => {
  it("returns a dash when inactive", () => {
    expect(formatRate(0)).toBe("—");
    expect(formatRate(-1)).toBe("—");
  });
  it("formats a positive rate", () => {
    expect(formatRate(1024)).toBe("1.0 Ko/s");
  });
});

describe("formatRemaining", () => {
  it("returns indisponible for missing or non-positive values", () => {
    expect(formatRemaining(null)).toBe("Indisponible");
    expect(formatRemaining(0)).toBe("Indisponible");
    expect(formatRemaining(Number.NaN)).toBe("Indisponible");
  });
  it("formats seconds, minutes and hours", () => {
    expect(formatRemaining(45)).toBe("~ 45 s");
    expect(formatRemaining(120)).toBe("~ 2 min");
    expect(formatRemaining(3660)).toBe("~ 1 h 01 min");
    expect(formatRemaining(90000)).toBe("> 24 h");
  });
});

describe("formatDuration", () => {
  it("formats sub-second and clock durations", () => {
    expect(formatDuration(0.4)).toBe("< 1 s");
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(42)).toBe("0:42");
    expect(formatDuration(3660)).toBe("1 h 01 min");
  });
  it("returns a dash for invalid input", () => {
    expect(formatDuration(Number.NaN)).toBe("—");
  });
});

describe("parseMegabytes", () => {
  it("parses comma decimals and rejects bad input", () => {
    expect(parseMegabytes("1,5")).toBe(1.5 * 1024 * 1024);
    expect(parseMegabytes("")).toBeNull();
    expect(parseMegabytes("abc")).toBeNull();
    expect(parseMegabytes("-1")).toBeNull();
  });
});

describe("fileExtension", () => {
  it("extracts and upper-cases the extension", () => {
    expect(fileExtension("rapport.PDF")).toBe("PDF");
    expect(fileExtension("noext")).toBe("");
    expect(fileExtension(".hidden")).toBe("HIDDEN");
  });
});
