// Service worker du portail (servi sur /sw.js pour couvrir tout le site).
//  - Pages (accueil, fiches livre) : réseau d'abord, copie locale si hors connexion.
//  - Fichiers statiques versionnés : cache d'abord.
//  - Livres téléchargés (cache « aura-audio ») : servis avec la prise en charge
//    de « Range », donc lecture et déplacement dans le livre sans réseau.
//  - Déconnexion : les pages mises en cache (progression, favoris) sont effacées ;
//    les livres téléchargés restent (contenu public choisi par le visiteur).
var VERSION = 'v1';
var PAGES = 'aura-pages-' + VERSION;
var STATIC = 'aura-static-' + VERSION;
var AUDIO = 'aura-audio';
var OFFLINE_URL = '/hors-ligne';

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(PAGES).then(function (c) { return c.add(OFFLINE_URL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    var keep = [PAGES, STATIC, AUDIO];
    var names = await caches.keys();
    for (var i = 0; i < names.length; i++) {
      if (keep.indexOf(names[i]) < 0) await caches.delete(names[i]);
    }
    await self.clients.claim();
  })());
});

// Efface les pages personnelles (progression, favoris) mais garde la page « hors connexion ».
async function forgetPages() {
  var cache = await caches.open(PAGES);
  var keys = await cache.keys();
  for (var i = 0; i < keys.length; i++) {
    if (new URL(keys[i].url).pathname !== OFFLINE_URL) await cache.delete(keys[i]);
  }
}

function cacheablePage(url) {
  return url.pathname === '/' || url.pathname.indexOf('/livre/') === 0;
}

async function page(request) {
  var cache = await caches.open(PAGES);
  try {
    var response = await fetch(request);
    if (response.ok && cacheablePage(new URL(request.url))) cache.put(request, response.clone());
    return response;
  } catch (err) {
    return (await cache.match(request)) || (await cache.match(OFFLINE_URL)) || Response.error();
  }
}

async function staticFile(request) {
  var cache = await caches.open(STATIC);
  var hit = await cache.match(request);
  if (hit) return hit;
  var response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

async function fromBlob(request, hit) {
  var blob = await hit.blob();
  var size = blob.size;
  var type = hit.headers.get('Content-Type') || 'audio/mpeg';
  var base = { 'Content-Type': type, 'Accept-Ranges': 'bytes' };
  var range = request.headers.get('range');
  var m = range && /^bytes=(\d*)-(\d*)$/.exec(range);
  if (!m) {
    base['Content-Length'] = String(size);
    return new Response(blob, { status: 200, headers: base });
  }
  var start = m[1] ? parseInt(m[1], 10) : 0;
  var end = m[2] ? parseInt(m[2], 10) : size - 1;
  if (!m[1] && m[2]) { start = Math.max(0, size - parseInt(m[2], 10)); end = size - 1; }
  if (start >= size || start > end) {
    return new Response(null, { status: 416, headers: { 'Content-Range': 'bytes */' + size } });
  }
  end = Math.min(end, size - 1);
  base['Content-Range'] = 'bytes ' + start + '-' + end + '/' + size;
  base['Content-Length'] = String(end - start + 1);
  return new Response(blob.slice(start, end + 1, type), { status: 206, headers: base });
}

async function media(request) {
  var url = new URL(request.url);
  var cache = await caches.open(AUDIO);
  var hit = await cache.match(url.origin + url.pathname);
  if (hit) return fromBlob(request, hit);
  return fetch(request);
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method === 'POST' && url.pathname === '/api/public/logout') {
    event.waitUntil(forgetPages());
    return; // la déconnexion se déroule normalement
  }
  if (request.method !== 'GET') return;
  if (url.pathname.indexOf('/m/') === 0) { event.respondWith(media(request)); return; }
  if (url.pathname.indexOf('/portal-assets/') === 0) { event.respondWith(staticFile(request)); return; }
  if (request.mode === 'navigate') { event.respondWith(page(request)); }
});
