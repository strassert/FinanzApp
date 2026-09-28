// F10: offline display of the last state.
// App shell: cache first, refreshed in the background. API GETs: network first,
// on failure the last cached answer, marked with X-Finanzen-Offline.
const SHELL = "finanzen-shell-v1";
const DATA = "finanzen-data-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icon.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/connect/") || url.pathname.startsWith("/fake-bank/")) return;

  if (url.pathname.startsWith("/api/")) {
    e.respondWith((async () => {
      try {
        const resp = await fetch(req);
        if (resp.ok) (await caches.open(DATA)).put(req, resp.clone());
        return resp;
      } catch {
        const cached = await caches.match(req, { cacheName: DATA });
        if (!cached) throw new Error("offline");
        const headers = new Headers(cached.headers);
        headers.set("X-Finanzen-Offline", "1");
        headers.set("X-Finanzen-Fetched-At", cached.headers.get("Date") || "");
        return new Response(await cached.blob(), { status: 200, headers });
      }
    })());
    return;
  }

  // navigation -> index.html; assets -> cache first
  const key = req.mode === "navigate" ? "/" : req;
  e.respondWith((async () => {
    const cache = await caches.open(SHELL);
    const cached = await cache.match(key);
    const network = fetch(req).then((resp) => {
      if (resp.ok) cache.put(key, resp.clone());
      return resp;
    }).catch(() => cached);
    return cached || network;
  })());
});
