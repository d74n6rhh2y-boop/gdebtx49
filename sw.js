/* hexplay service worker — instant repeat visits.
   images/fonts/css/js: cache-first (immutable by filename)
   games.json + pages:  network-first with cache fallback (fresh when online, instant when not) */
const V = 'hx-v1';
const SHELL = ['/', '/styles.css', '/layout.js',
  '/fonts/unbounded-600.woff2', '/fonts/unbounded-800.woff2',
  '/fonts/space-mono-400.woff2', '/fonts/space-mono-700.woff2'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => Promise.allSettled(SHELL.map(u => c.add(u)))));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  const p = url.pathname;
  const cacheFirst = p.startsWith('/img/') || p.startsWith('/fonts/') ||
                     p === '/styles.css' || p === '/layout.js';

  if (cacheFirst) {
    e.respondWith(caches.open(V).then(async c => {
      const hit = await c.match(req, { ignoreSearch: p !== '/games.json' });
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) c.put(req, res.clone());
      return res;
    }));
    return;
  }

  // navigations + games.json: network first, cached copy as fallback
  if (req.mode === 'navigate' || p === '/games.json') {
    e.respondWith(caches.open(V).then(async c => {
      try {
        const res = await fetch(req);
        if (res.ok) c.put(req, res.clone());
        return res;
      } catch (err) {
        const hit = await c.match(req, { ignoreSearch: true });
        if (hit) return hit;
        throw err;
      }
    }));
  }
});
