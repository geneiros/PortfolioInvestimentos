/* Service worker do Portfolio Investimentos (aplicação instalável).
 *
 * Só guarda em cache os ficheiros estáticos (Bootstrap, ícones, Chart.js) e a página "aplicação parada".
 * As páginas e a API vão sempre à aplicação local: os dados financeiros nunca ficam em cache.
 */
const VERSION = "pi-v2";
const PRECACHE = [
  "/static/offline.html",
  "/static/vendor/bootstrap/bootstrap.min.css",
  "/static/vendor/bootstrap-icons/bootstrap-icons.min.css",
  "/static/icons/favicon.svg",
  "/static/icons/icon-192.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;

  if (req.mode === "navigate") {
    // aplicação parada (servidor local desligado): mostra como a iniciar
    e.respondWith(fetch(req).catch(() => caches.match("/static/offline.html")));
    return;
  }
  if (url.pathname.startsWith("/static/vendor/") || url.pathname.startsWith("/static/icons/")) {
    // bibliotecas e ícones não mudam entre versões: primeiro a cache
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
      return res;
    })));
  }
});
