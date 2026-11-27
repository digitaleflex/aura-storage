import { describe, expect, it } from "vitest";
import { activeSpaces } from "./adminText";

describe("activeSpaces", () => {
  it("keeps only active spaces for identity and partner forms", () => {
    const spaces = [
      { id: "active", status: "active" },
      { id: "disabled", status: "disabled" },
      { id: "other", status: "pending" },
    ];

    expect(activeSpaces(spaces)).toEqual([{ id: "active", status: "active" }]);
  });

  it("accepts missing data while the admin query is loading", () => {
    expect(activeSpaces(undefined)).toEqual([]);
    expect(activeSpaces(null)).toEqual([]);
  });
});
