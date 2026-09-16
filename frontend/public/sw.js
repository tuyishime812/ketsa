/* Minimal placeholder service worker.

   Previous deployments of this origin registered a service worker that is now
   gone, so browsers keep requesting /sw.js on every load (and Next dev logs a
   `GET /sw.js 404` for it). Serving a valid file here stops that 404 loop and
   lets any stale registration settle. It deliberately keeps no caches, so the
   app is always served fresh.
*/

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener('fetch', () => {
  /* Pass-through: never intercept application requests. */
});