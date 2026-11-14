/* Aplicativo instalável: guarda a página e a última base para uso sem internet. */
var VERSAO = "concursos-sp-v1";
var CASCA = ["./", "index.html", "manifest.webmanifest", "icone-192.png", "icone-512.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(VERSAO).then(function (c) { return c.addAll(CASCA); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== VERSAO; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  var fonte = /fonts\.(googleapis|gstatic)\.com$/.test(url.hostname);
  if (url.origin !== self.location.origin && !fonte) return;

  if (fonte) { // fontes mudam raramente: primeiro o que está guardado
    e.respondWith(caches.match(req).then(function (r) {
      return r || fetch(req).then(function (res) {
        var copia = res.clone();
        caches.open(VERSAO).then(function (c) { c.put(req, copia); });
        return res;
      });
    }));
    return;
  }
  // página e dados: primeiro a rede (para vir sempre o mais novo); sem rede, o que está guardado
  e.respondWith(fetch(req).then(function (res) {
    if (res && res.ok) {
      var copia = res.clone();
      caches.open(VERSAO).then(function (c) { c.put(req, copia); });
    }
    return res;
  }).catch(function () {
    return caches.match(req, {ignoreSearch: true}).then(function (r) {
      return r || (req.mode === "navigate" ? caches.match("index.html") : Response.error());
    });
  }));
});
