import { describe, expect, it } from "vitest";
import { absoluteShareUrl, canShareInline, shareState } from "./shares";
import type { ObjectShare } from "./api";

function share(overrides: Partial<ObjectShare> = {}): ObjectShare {
  return {
    id: "s1",
    object_id: "o1",
    created_by: "u1",
    created_by_kind: "user",
    content_disposition: "attachment",
    created_at: 1_700_000_000,
    expires_at: 1_700_086_400,
    max_uses: null,
    use_count: 0,
    last_used_at: null,
    revoked_at: null,
    active: true,
    ...overrides,
  };
}

describe("canShareInline", () => {
  it("mirrors the server's safe inline list", () => {
    expect(canShareInline("application/pdf")).toBe(true);
    expect(canShareInline("image/png")).toBe(true);
    expect(canShareInline("text/plain; charset=utf-8")).toBe(true);
  });

  it("keeps active documents and media download-only", () => {
    expect(canShareInline("text/html")).toBe(false);
    expect(canShareInline("image/svg+xml")).toBe(false);
    expect(canShareInline("video/mp4")).toBe(false);
    expect(canShareInline("audio/mpeg")).toBe(false);
  });
});

describe("absoluteShareUrl", () => {
  it("keeps an absolute URL untouched", () => {
    expect(absoluteShareUrl("https://app.example/s/tok", "https://other")).toBe(
      "https://app.example/s/tok",
    );
  });

  it("resolves the API's relative form against the app origin", () => {
    expect(absoluteShareUrl("/s/tok", "https://app.example")).toBe(
      "https://app.example/s/tok",
    );
    expect(absoluteShareUrl("s/tok", "https://app.example/")).toBe(
      "https://app.example/s/tok",
    );
  });
});

describe("shareState", () => {
  const now = 1_700_000_000;

  it("is active while usable", () => {
    expect(shareState(share({ expires_at: now + 60 }), now)).toBe("active");
  });

  it("names the reason in server precedence order", () => {
    expect(shareState(share({ revoked_at: now - 1 }), now)).toBe("revoked");
    expect(shareState(share({ expires_at: now }), now)).toBe("expired");
    expect(shareState(share({ max_uses: 2, use_count: 2 }), now)).toBe("exhausted");
  });
});
