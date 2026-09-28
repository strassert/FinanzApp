import { describe, expect, it } from "vitest";
import { axis, eur, eurCents, monthShort, percent, relativeDay, signed } from "./format";

const nb = (s: string) => s.replace(/ | /g, " ");

describe("format", () => {
  it("key figures without cents", () => {
    expect(nb(eur(123456))).toBe("€ 1.235");
    expect(nb(eur(-5000))).toBe("−€ 50");
    expect(eur(null)).toBe("–");
  });
  it("list amounts with cents", () => {
    expect(nb(eurCents(1250))).toBe("€ 12,50");
    expect(nb(eurCents(-1299, "USD"))).toBe("−$ 12,99");
    expect(nb(eurCents(1000, "JPY"))).toContain("1.000");
  });
  it("signed amounts", () => {
    expect(nb(signed(-2380))).toBe("−€ 23,80");
    expect(nb(signed(324000))).toBe("+€ 3.240,00");
  });
  it("axis, percent, months", () => {
    expect(axis(250000)).toBe("2.500");
    expect(axis(50000)).toBe("500");
    expect(nb(percent(0.284))).toBe("28 %");
    expect(monthShort("2026-01")).toBe("Jän");
  });
  it("relative days", () => {
    expect(relativeDay("2026-09-28", "2026-09-28")).toBe("Heute");
    expect(relativeDay("2026-09-27", "2026-09-28")).toBe("Gestern");
    expect(relativeDay("2026-09-20", "2026-09-28")).toContain("20. September");
  });
});
