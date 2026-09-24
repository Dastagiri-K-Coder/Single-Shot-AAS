/* Single Shot AAS v2.0 — Service Worker
 * Cache-first for static shell, network-first for API routes.
 * Enables offline UI loading from faculty smartphones.
 */

const CACHE_NAME    = 'aas-v2-shell-v1';
const API_CACHE     = 'aas-v2-api-v1';

// Static shell assets to cache on install
const SHELL_ASSETS = [
  '/',
  '/dashboard',
  '/static/style.css',
  '/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

// Routes that should always go network-first (real-time data)
const NETWORK_FIRST_PATTERNS = [
  '/api/',
  '/take-attendance',
  '/take-attendance-individual',
  '/upload-photo',
  '/login',
  '/logout',
];

// ── Install: cache static shell ──────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Caching shell assets');
      return cache.addAll(SHELL_ASSETS.map(url => new Request(url, { cache: 'reload' })));
    }).then(() => self.skipWaiting())
  );
});

// ── Activate: clean up old caches ────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: routing strategy ───────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  // Network-first for API and form submission routes
  const isNetworkFirst = NETWORK_FIRST_PATTERNS.some(
    (p) => url.pathname.startsWith(p)
  );

  if (isNetworkFirst) {
    event.respondWith(networkFirst(event.request));
  } else {
    event.respondWith(cacheFirst(event.request));
  }
});

// ── Strategies ────────────────────────────────────────────────────────────────

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    return response;
  } catch (_) {
    // Offline: return cached version if available
    const cached = await caches.match(request);
    if (cached) return cached;
    // Return a minimal offline response for API calls
    return new Response(
      JSON.stringify({ status: 'offline', message: 'Device is offline. Please reconnect to the AAS network.' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response && response.status === 200 && response.type === 'basic') {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    // Return offline fallback page
    const fallback = await caches.match('/');
    return fallback || new Response('Offline — reconnect to AAS network', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' }
    });
  }
}
