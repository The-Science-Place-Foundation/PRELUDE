/* Service worker: offline capability once served over HTTPS.
   Registers only in a secure context - Safari refuses otherwise.

   Audio is cached separately and never revalidated: stimuli are immutable,
   regenerated under new names rather than edited. The shell is
   network-first so a design change reaches the phone on the next launch. */
const SHELL = 'prelude-shell-v1';
const AUDIO = 'prelude-audio-v1';
const CORE = ['/', '/style.css', '/app.js', '/manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k !== SHELL && k !== AUDIO).map((k) => caches.delete(k))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/')) return;           // never cache decisions
  if (url.pathname.startsWith('/audio/')) {
    e.respondWith(caches.open(AUDIO).then(async (c) => {
      const hit = await c.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok) c.put(e.request, res.clone());
      return res;
    }));
    return;
  }
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok) caches.open(SHELL).then((c) => c.put(e.request, res.clone()));
    return res;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match('/'))));
});
