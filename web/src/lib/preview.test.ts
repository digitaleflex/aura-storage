import { describe, expect, it } from "vitest";
import { isPreviewable, previewKind } from "./preview";

describe("previewKind", () => {
  it("maps each allow-listed family to its renderer", () => {
    expect(previewKind("image/png")).toBe("image");
    expect(previewKind("application/pdf")).toBe("pdf");
    expect(previewKind("audio/mpeg")).toBe("audio");
    expect(previewKind("video/mp4")).toBe("video");
    expect(previewKind("video/webm; codecs=avc1")).toBe("video");
    expect(previewKind("video/ogg")).toBe("video");
  });

  it("returns null for types the API refuses inline", () => {
    expect(previewKind("image/svg+xml")).toBeNull();
    expect(previewKind("text/html")).toBeNull();
    expect(previewKind("application/octet-stream")).toBeNull();
    expect(previewKind(undefined)).toBeNull();
  });
});

describe("isPreviewable", () => {
  it("ignores parameters and case", () => {
    expect(isPreviewable("Video/MP4")).toBe(true);
    expect(isPreviewable("video/mp4; codecs=avc1")).toBe(true);
    expect(isPreviewable(" Application/PDF ; charset=binary")).toBe(true);
  });

  it("keeps script-capable types out", () => {
    expect(isPreviewable("image/svg+xml")).toBe(false);
    expect(isPreviewable("text/html")).toBe(false);
    expect(isPreviewable("application/xml")).toBe(false);
  });
});
