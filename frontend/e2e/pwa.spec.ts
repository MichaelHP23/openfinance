// frontend/e2e/pwa.spec.ts
import { test, expect } from "@playwright/test";

test.use({ baseURL: "http://localhost:4174" });

test("manifest is valid and carries what Chrome's installability check requires", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const manifestHref = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(manifestHref).toBe("/manifest.json");

  const res = await request.get("http://localhost:4174/manifest.json");
  expect(res.ok()).toBe(true);
  const manifest = await res.json();

  expect(manifest.name).toBeTruthy();
  expect(manifest.start_url).toBe("/");
  expect(manifest.display).toBe("standalone");
  expect(Array.isArray(manifest.icons) && manifest.icons.length).toBeGreaterThan(0);
  // Chrome's ManifestIconSelector accepts an SVG icon declared sizes: "any" as satisfying
  // the 192px/512px installability floor — see Task 2's Icon decision note.
  expect(manifest.icons.some((i: { sizes: string }) => i.sizes === "any")).toBe(true);

  const themeColor = await page.locator('meta[name="theme-color"]').getAttribute("content");
  expect(themeColor).toBe(manifest.theme_color);
});

test("service worker activates and serves the app shell when the network is cut", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); // first controlled load — populates the shell cache via the fetch handler
  await page.waitForLoadState("networkidle");

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await context.setOffline(false);
});

test("a page visited online stays readable offline from the API cache", async ({
  page,
  context,
}) => {
  await page.goto("/accounts");
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
  // The very first navigation to any route lands before the service worker is controlling
  // the page, so /accounts's shell document is never written to SHELL_CACHE by that first
  // load alone (see the fetch handler in service-worker.js: same-origin GET is cache-first
  // with no fallback beyond a live fetch on an uncontrolled request). A second, now-SW-
  // controlled load is what actually populates the shell cache — same reasoning as the
  // previous test's warm-up reload, just against a different route.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
  await page.waitForLoadState("networkidle"); // let the GET /accounts response land in the cache

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
  // context.setOffline() fails real network requests over CDP but — a documented Chromium/
  // Playwright limitation — does not flip navigator.onLine or fire the window "offline"
  // event a real disconnect would. OfflineBanner (src/ui/OfflineBanner.tsx) listens for
  // exactly that event, so it never reacts to setOffline() on its own; dispatch the event
  // this page would genuinely receive from a real network drop.
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByText(/offline — showing cached data as of/i)).toBeVisible();
  await context.setOffline(false);
});
