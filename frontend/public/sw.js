// Offline shell. Only the app's own static files are cached; API responses (financial data) never are.
// The build step (see vite.config.ts) replaces BUILD_ID and PRECACHE so every release gets its own cache and old ones are deleted.
const BUILD_ID = '__BUILD_ID__'
const PRECACHE = /*PRECACHE_START*/ ['/', '/offline.html', '/icon.svg', '/manifest.json'] /*PRECACHE_END*/
const CACHE = `ab-shell-${BUILD_ID}`

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)))
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((ks) => Promise.all(ks.filter((k) => k.startsWith('ab-shell-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (e) => {
  const req = e.request
  const url = new URL(req.url)
  if (req.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return
  if (req.mode === 'navigate') {
    // network first so a new release is picked up; the cached shell (then the offline page) when there is no network
    e.respondWith(fetch(req).catch(() => caches.match('/').then((m) => m || caches.match('/offline.html'))))
    return
  }
  // hashed build assets never change, so serve them from the cache first
  e.respondWith(
    caches.match(req).then(
      (m) =>
        m ||
        fetch(req).then((r) => {
          if (r.ok && url.pathname.startsWith('/assets/')) {
            const copy = r.clone()
            caches.open(CACHE).then((c) => c.put(req, copy))
          }
          return r
        }),
    ),
  )
})
