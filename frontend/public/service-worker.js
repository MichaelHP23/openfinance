// frontend/public/service-worker.js
//
// Hand-rolled, not vite-plugin-pwa — see
// docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §3.1. This app's entire
// API surface is same-origin-shaped JSON (a different port, same protocol/host — see
// src/api/client.ts's API_BASE), so there's no precache manifest to keep in sync with Vite's
// content-hashed build output: the shell cache fills itself in as pages are actually visited
// instead of being built from a file list.
//
// Bump CACHE_VERSION by hand whenever this file's caching behavior changes — it is the only
// invalidation signal a runtime cache has, since there's no build step generating one.
const CACHE_VERSION = "v1";
const SHELL_CACHE = `shell-${CACHE_VERSION}`;
const API_CACHE = `api-${CACHE_VERSION}`;

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k !== SHELL_CACHE && k !== API_CACHE).map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  // No offline writes (spec §3.2) — a mutation attempted offline should fail visibly, not
  // silently replay later against data that may have moved on. Let the browser handle it
  // natively; it'll reject with a network error the app's existing TanStack Query error
  // states already render.
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (url.origin === self.location.origin) {
    // App shell: cache-first. First visit to any given asset populates the cache; every
    // later visit — online or not — serves instantly from it.
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // Cross-origin GET — the API. Network-first: a live answer always wins over a cached one,
  // and the cache is only ever a fallback for when the network fails outright.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(API_CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() =>
        caches.match(request).then((cached) => cached ?? Promise.reject(new Error("offline"))),
      ),
  );
});
