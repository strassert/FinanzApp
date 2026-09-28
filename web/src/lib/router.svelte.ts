// Minimal hash router: #/umsaetze?kategorie=3 -> { path: "umsaetze", params }

function parse(): { path: string; parts: string[]; params: URLSearchParams } {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart = ""] = raw.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  return { path: parts[0] ?? "", parts, params: new URLSearchParams(queryPart) };
}

export const route = $state(parse());

window.addEventListener("hashchange", () => {
  Object.assign(route, parse());
});

export function go(path: string, params: Record<string, string | number | undefined> = {}): void {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  location.hash = `#/${path}${s ? `?${s}` : ""}`;
}
