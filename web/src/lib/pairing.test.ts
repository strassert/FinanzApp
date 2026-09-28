import { describe, expect, it } from "vitest";
import { tokenFromInput } from "./pairing";

const TOKEN = "Ab3_dE-fGhIjKlMnOpQrStUvWxYz0123456789abcde";

describe("tokenFromInput", () => {
  it("reads the token from a pairing link", () => {
    expect(tokenFromInput(`https://finanzen.example.ts.net/#/koppeln/${TOKEN}`)).toBe(TOKEN);
  });

  it("accepts a bare token and trims whitespace", () => {
    expect(tokenFromInput(`  ${TOKEN}\n`)).toBe(TOKEN);
  });

  it("rejects anything else", () => {
    expect(tokenFromInput("")).toBeNull();
    expect(tokenFromInput("https://finanzen.example.ts.net/")).toBeNull();
    expect(tokenFromInput("kurz")).toBeNull();
  });
});
