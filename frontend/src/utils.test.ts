import { describe, it, expect } from "vitest";
import { formatDuration, translateDurationType } from "./utils";

describe("formatDuration", () => {
  it("formats zero as 00:00", () => {
    expect(formatDuration(0)).toBe("00:00");
  });

  it("formats seconds under a minute", () => {
    expect(formatDuration(5)).toBe("00:05");
    expect(formatDuration(59)).toBe("00:59");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(65)).toBe("01:05");
    expect(formatDuration(600)).toBe("10:00");
  });

  it("pads with leading zeros", () => {
    expect(formatDuration(7)).toBe("00:07");
    expect(formatDuration(607)).toBe("10:07");
  });
});

describe("translateDurationType", () => {
  it("returns 0s for falsy values", () => {
    expect(translateDurationType(0)).toBe("0s");
    expect(translateDurationType(NaN)).toBe("0s");
  });

  it("formats seconds only", () => {
    expect(translateDurationType(45)).toBe("45s");
  });

  it("formats minutes and seconds", () => {
    expect(translateDurationType(105)).toBe("1m 45s");
    expect(translateDurationType(3600)).toBe("60m 0s");
  });
});