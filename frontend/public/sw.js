/*
 * SchoolYar service worker — offline mode.
 *
 * WHAT IT CACHES
 *   - The app's static build files (/_next/static/*): cache-first. Their names carry
 *     a content hash, so a cached copy can never be stale.
 *   - Signed-in app pages, as the user visits them: network-first. Online, the page
 *     always comes fresh from the server (and the copy is refreshed); offline, or when
 *     the server does not answer within a few seconds, the last copy is shown.
 *   - /offline.html: shown for a page that was never opened on this device.
 *
 * WHAT IT NEVER CACHES
 *   - /api/* — data and every write go through the app, which keeps its own offline
 *     copy (IndexedDB) and queue. Caching API responses here would show one user's
 *     data to the next, and replaying a cached POST would be a disaster.
 *   - Sign-in pages, the parent portal and the operator console.
 *   - Any response that was a redirect (an expired session bouncing to /login).
 *
 * Page copies hold a user's data, so the app deletes them on sign-out
 * (`clearOfflineData`) and when a different person signs in.
 */

const VERSION = "v1";
const STATIC_CACHE = `sy-static-${VERSION}`;
const PAGE_CACHE = `sy-pages-${VERSION}`;
const OFFLINE_URL = "/offline.html";
const NETWORK_TIMEOUT_MS = 6000;

const NEVER_CACHE_PAGES = [
  "/login",
  "/signup",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
  "/invite",
  "/parent",
  "/platform",
  "/admissions",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll([OFFLINE_URL, "/icons/icon-192.png"]))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith("sy-") && name !== STATIC_CACHE && name !== PAGE_CACHE)
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "clear-pages") {
    event.waitUntil(caches.delete(PAGE_CACHE));
  }
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request));
    return;
  }

  if (request.mode === "navigate" && !isExcludedPage(url.pathname)) {
    event.respondWith(networkFirstPage(request));
  }
});

function isExcludedPage(pathname) {
  return NEVER_CACHE_PAGES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(STATIC_CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirstPage(request) {
  const cache = await caches.open(PAGE_CACHE);
  // Keyed without the query string: "/attendance?session=…" opens the same page.
  const key = new URL(request.url);
  key.search = "";
  const cacheKey = key.toString();

  try {
    const response = await withTimeout(fetch(request), NETWORK_TIMEOUT_MS);
    const type = response.headers.get("content-type") || "";
    if (response.ok && !response.redirected && type.includes("text/html")) {
      cache.put(cacheKey, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(cacheKey);
    if (cached) return cached;
    const offline = await caches.match(OFFLINE_URL);
    return offline || Response.error();
  }
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}
