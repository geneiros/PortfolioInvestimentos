/* Service worker do Portfolio Investimentos (aplicação instalável).
 *
 * - Bibliotecas e ícones: primeiro a cache (não mudam entre versões).
 * - CSS e JavaScript da aplicação: primeiro a rede, com a cópia guardada se a aplicação estiver parada.
 * - Páginas: primeiro a rede. Só com o modo "Disponível offline" ligado (Definições) é que o servidor marca
 *   as páginas de consulta com o cabeçalho X-PM-Offline e elas são guardadas, para se poderem consultar
 *   com a aplicação parada. Desligar o modo ou sair (Sair) apaga a cópia (mensagem "clear").
 */
const VERSION = "pi-v3";
const PAGES = "pi-pages";
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
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION && k !== PAGES).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function savePage(req, res) {
  if (res.ok && res.headers.get("X-PM-Offline") === "1") {
    const cache = await caches.open(PAGES);
    await cache.put(req.url, res.clone());
  }
  return res;
}

async function offlinePage(req) {
  const cache = await caches.open(PAGES);
  // a cópia da página; se nunca foi guardada (ex.: Definições), a página "aplicação parada", que lista as guardadas
  return (await cache.match(req.url)) || caches.match("/static/offline.html");
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname === "/ping") return;

  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then((res) => savePage(req, res)).catch(() => offlinePage(req)));
    return;
  }
  if (url.pathname.startsWith("/static/vendor/") || url.pathname.startsWith("/static/icons/")) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
      return res;
    })));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    // CSS, JavaScript e manifesto da aplicação: versão nova quando há rede, cópia quando não há
    e.respondWith(fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req)));
  }
});

self.addEventListener("message", (e) => {
  const msg = e.data || {};
  if (msg.type === "clear") {
    e.waitUntil(caches.delete(PAGES));
  } else if (msg.type === "warm" && Array.isArray(msg.urls)) {
    // guarda as páginas principais (só as que o servidor marcar como consultáveis offline)
    e.waitUntil(Promise.all(msg.urls.map((u) => {
      const req = new Request(new URL(u, self.location.origin).href, { credentials: "same-origin" });
      return fetch(req).then((res) => savePage(req, res)).catch(() => null);
    })));
  }
});
