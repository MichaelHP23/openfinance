# P7 — Mobile / PWA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app installable on a phone home screen, usable read-only offline with cached
data, and fix the one pre-existing mobile e2e bug that's been carried forward since before P1.

**Architecture:** A static `manifest.json` plus a hand-rolled, dependency-free
`service-worker.js` (cache-first for the same-origin app shell, network-first-with-fallback for
cross-origin API GETs). An install-prompt banner captures `beforeinstallprompt`; an offline banner
reads `navigator.onLine` plus a global TanStack Query error hook. Three components that render
raw HTML `<table>`s get a second, `md:hidden` card-list rendering — the same dual-render pattern
`holdings.tsx`/`HoldingsList` already ships — because a hover-only table is unusable at 360px.

**Tech Stack:** React 19, TanStack Query 5, Tailwind 4, Vite 8, Playwright, Vitest + Testing
Library. No new dependency of any kind — see Global Constraints.

## Global Constraints

- **No new dependencies.** `docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md` §3.1
  flags PWA installability as the one place in this roadmap most likely to tempt
  `vite-plugin-pwa`. It is not used. A hand-rolled service worker covers this app's actual need
  (same-origin JSON API, no complex precache manifest) in about the ~40 lines the spec predicts.
- **No offline writes, no background sync, no queue.** A write attempted offline fails visibly.
  This is explicit in spec §3.2: a queued mutation that replays against a since-changed balance
  is a correctness bug, not a feature.
- **`frontend/src/ui/Shell.tsx`'s `NAV`/`MORE` split is decided** (`docs/superpowers/plans/PLAN-CONSTRAINTS.md`
  §Navigation). This plan does not touch it.
- **Money stays `string` in TypeScript**, never `number`/`float`, in any new or touched code —
  the dual-render tasks below reuse the existing `usd()`/`units()`/`pct()` formatters verbatim,
  they never re-derive a number from a money string.
- **Gates, from `frontend/`:** `npm test`, `npm run build` (not `npm run typecheck` —
  PLAN-CONSTRAINTS.md explains why those two disagree), `npm run lint`, `npm run e2e` (needs
  `docker compose up -d`; the dev webServer is auto-started by Playwright).
- **Vite resolves `./foo` to `foo.ts` before `foo.tsx`.** Every new component file below uses a
  name distinct from any hooks module in the same directory.
- React Testing Library: a query that used to be unambiguous can become ambiguous once a
  component dual-renders (table + card). `holdings.test.tsx` already hit this and fixed it with
  `findAllByText`/`getAllByLabelText` plus a `.closest("table")` disambiguator where a specific
  instance matters — every test touched by Task 5 follows that same precedent.

---

## Task 1: Fix the pre-existing `mobile.spec.ts` heading bug

`frontend/e2e/mobile.spec.ts` has failed on `main` since before P1:
`getByRole("heading", { name: "Accounts" })` matches both `AccountsPage`'s `<h1>Accounts</h1>`
(from `PageHead`) and its "Your accounts" `<h2>` card title, because Playwright's `name` matcher
is a case-insensitive substring match by default and `"Your accounts"` contains `"accounts"`.
`docs/superpowers/plans/PLAN-CONSTRAINTS.md` and `TASK.md` have both carried this as "not yours"
through five phases. P7 touches every mobile surface anyway — fix it now.

**Files:**
- Modify: `frontend/e2e/mobile.spec.ts:26`

**Interfaces:** None — this task touches only test code.

- [ ] **Step 1: Confirm the failure**

Run: `cd frontend && npm run e2e -- mobile.spec.ts` (needs `docker compose up -d` running from
an earlier session, and `npm run dev` — Playwright's `webServer` config starts it automatically).
Expected: FAIL, with an error naming both the `<h1>` and the `<h2>` as matches for `"Accounts"`.

- [ ] **Step 2: Narrow the matcher to `exact: true`**

```typescript
// frontend/e2e/mobile.spec.ts:26
await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
```

`exact: true` makes the match case-sensitive and whole-string, so `"Your accounts"` no longer
qualifies (different case, and not the whole string either) while `<h1>Accounts</h1>` still does.

- [ ] **Step 3: Run it again to confirm it passes**

Run: `cd frontend && npm run e2e -- mobile.spec.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/mobile.spec.ts
git commit -m "fix: narrow mobile e2e's Accounts heading match to exact"
```

---

## Task 2: PWA manifest, icons, and an install-prompt banner

**Files:**
- Create: `frontend/public/manifest.json`
- Modify: `frontend/index.html`
- Create: `frontend/src/ui/InstallBanner.tsx`
- Create: `frontend/src/ui/InstallBanner.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces: `InstallBanner` — a zero-prop component, default export not needed (named export,
  matching every other component in `ui/`).

### Icon decision — recorded so nobody "fixes" it later

The spec (§3.1) expected `frontend/public/icons.svg` to hold "what's needed" for sized PNG
export. Checked against the tree: `icons.svg` is a sprite of *social-link* icons (Bluesky,
Discord, GitHub, X) used elsewhere in the app's marketing surface — unrelated to an app icon.
The actual app mark is `frontend/public/favicon.svg` (the purple "O" glyph already wired as the
browser tab favicon in `index.html:5`).

No PNG rasterizer exists anywhere in this toolchain — no ImageMagick, no `rsvg-convert`, no
Pillow/cairosvg in the backend venv, no `sharp`/`vite-plugin-pwa` in the frontend. Adding one
for a one-time icon export is exactly the dependency this phase's own constraints warn against.
**The manifest ships a single SVG icon entry, `sizes: "any"`.** Chrome/Edge/Android have accepted
`sizes: "any"` SVG manifest icons for installability since 2022; this is not a workaround, it's
the documented mechanism for a vector icon. **Cut: a `maskable` purpose variant** — `favicon.svg`'s
mark fills most of its viewBox with little safe-zone padding, and a maskable icon needs padding
inside the safe circle or platforms crop it. Shipping it as `purpose: "any"` (never cropped,
platforms compose their own background shape) is the honest choice; a real maskable variant is a
design task, not an engineering one, and isn't blocking installability. **Cut: `apple-touch-icon`
PNG** — iOS 17+ WebKit accepts SVG there too, so `index.html` links `favicon.svg` for it as a
best effort; older iOS falls back to a screenshot-based icon, which is a cosmetically worse but
functionally fine outcome, not worth a rasterization dependency to avoid.

- [ ] **Step 1: Write the manifest**

```json
// frontend/public/manifest.json
{
  "name": "OpenFinance",
  "short_name": "OpenFinance",
  "description": "Track accounts, budgets, goals, and investments — self-hosted.",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0b0b0c",
  "theme_color": "#0b0b0c",
  "icons": [
    { "src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" }
  ]
}
```

- [ ] **Step 2: Link it and add the iOS home-screen icon from `index.html`**

```html
<!-- frontend/index.html — add inside <head>, near the existing favicon link -->
<link rel="manifest" href="/manifest.json" />
<link rel="apple-touch-icon" href="/favicon.svg" />
```

- [ ] **Step 3: Write the failing test for the install banner**

```typescript
// frontend/src/ui/InstallBanner.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { InstallBanner } from "./InstallBanner";

afterEach(() => {
  localStorage.clear();
});

function firePrompt() {
  const event = new Event("beforeinstallprompt") as Event & {
    prompt: () => void;
    userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
  };
  event.prompt = vi.fn();
  event.userChoice = Promise.resolve({ outcome: "accepted" });
  window.dispatchEvent(event);
  return event;
}

test("renders nothing until the browser fires beforeinstallprompt", () => {
  render(<InstallBanner />);
  expect(screen.queryByText(/install/i)).not.toBeInTheDocument();
});

test("shows an Install button after the event fires, and calling it invokes prompt()", () => {
  render(<InstallBanner />);
  const event = firePrompt();
  fireEvent.click(screen.getByRole("button", { name: "Install" }));
  expect(event.prompt).toHaveBeenCalled();
});

test("dismissing hides the banner and remembers the choice", () => {
  render(<InstallBanner />);
  firePrompt();
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
  expect(localStorage.getItem("pwa-install-dismissed")).toBe("1");
});

test("stays hidden on a fresh render if already dismissed", () => {
  localStorage.setItem("pwa-install-dismissed", "1");
  render(<InstallBanner />);
  firePrompt();
  expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
});
```

- [ ] **Step 4: Run it to verify it fails**

Run: `cd frontend && npm test -- InstallBanner`
Expected: FAIL — `Cannot find module './InstallBanner'`.

- [ ] **Step 5: Implement the banner**

```tsx
// frontend/src/ui/InstallBanner.tsx
import { useEffect, useState } from "react";

const DISMISSED_KEY = "pwa-install-dismissed";

type InstallPromptEvent = Event & {
  prompt: () => void;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export function InstallBanner() {
  const [deferred, setDeferred] = useState<InstallPromptEvent | null>(null);

  useEffect(() => {
    if (localStorage.getItem(DISMISSED_KEY)) return;
    const onPrompt = (e: Event) => {
      // Chrome shows its own mini-infobar unless this fires; capturing it lets the
      // app offer install on its own terms instead.
      e.preventDefault();
      setDeferred(e as InstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (!deferred) return null;

  const dismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "1");
    setDeferred(null);
  };

  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-20 z-30 flex items-center justify-between gap-3 rounded-lg border border-line bg-ink/95 px-4 py-3 text-sm backdrop-blur md:bottom-4 md:left-auto md:right-4 md:w-80"
    >
      <span>Install OpenFinance for quicker access.</span>
      <div className="flex shrink-0 gap-2">
        <button
          className="btn-ghost px-2 py-1 text-[13px]"
          onClick={async () => {
            deferred.prompt();
            await deferred.userChoice;
            setDeferred(null);
          }}
        >
          Install
        </button>
        <button className="text-[13px] text-muted" onClick={dismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
```

`bottom-20` on mobile clears the fixed tab bar (`Shell.tsx`'s bottom nav); `md:bottom-4` drops
that offset on desktop, where there's no tab bar to clear.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && npm test -- InstallBanner`
Expected: PASS, all four tests.

- [ ] **Step 7: Wire it into the app**

```tsx
// frontend/src/App.tsx — add the import and render it once, at the top level, outside Routes
// so it survives navigation and shows on /login too.
import { InstallBanner } from "./ui/InstallBanner";

// inside <QueryClientProvider client={qc}>, as a sibling of <BrowserRouter>:
      <BrowserRouter>
        {/* ...existing <Routes> unchanged... */}
      </BrowserRouter>
      <InstallBanner />
    </QueryClientProvider>
```

- [ ] **Step 8: Commit**

```bash
git add frontend/public/manifest.json frontend/index.html frontend/src/ui/InstallBanner.tsx frontend/src/ui/InstallBanner.test.tsx frontend/src/App.tsx
git commit -m "feat: PWA manifest and an install-prompt banner"
```

---

## Task 3: Hand-rolled service worker — app shell cache-first, API GETs network-first

**Files:**
- Create: `frontend/public/service-worker.js`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: two cache names, `shell-v1` and `api-v1` (see `CACHE_VERSION` below), and the
  registration path `/service-worker.js` — Task 6's e2e test asserts against both.

Not TDD-able the normal way (Vitest's jsdom has no Service Worker / Cache API); verified instead
by Task 6's Playwright test against a production build, where both actually exist. This task's
own "test" is running it manually against a built app once, per Step 3.

- [ ] **Step 1: Write the service worker**

```javascript
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
```

- [ ] **Step 2: Register it, production builds only**

```typescript
// frontend/src/main.tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Dev mode serves hundreds of individual unbundled ES modules that change on every edit;
// cache-first over that would fight Vite's own HMR instead of helping anyone. Only register
// against a real production build, where the shell is the small bundle it's meant to be.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js");
  });
}
```

- [ ] **Step 3: Manually verify it installs against a production build**

Run:
```bash
cd frontend
npm run build
npm run preview -- --port 4174
```
Open `http://localhost:4174` in a browser, open DevTools → Application → Service Workers.
Expected: a worker registered at `/service-worker.js`, status "activated and is running". Stop
the preview server (Ctrl-C) once confirmed.

- [ ] **Step 4: Commit**

```bash
git add frontend/public/service-worker.js frontend/src/main.tsx
git commit -m "feat: hand-rolled service worker for the app shell and cached API reads"
```

---

## Task 4: Offline read banner

**Files:**
- Create: `frontend/src/ui/OfflineBanner.tsx`
- Create: `frontend/src/ui/OfflineBanner.test.tsx`
- Modify: `frontend/src/ui/Shell.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks — reads `navigator.onLine` and the `window` `online`/
  `offline` events directly, per spec §3.2 ("driven by `navigator.onLine`").
- Produces: `OfflineBanner`, a zero-prop component rendered once inside `Shell`'s `<main>`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/ui/OfflineBanner.test.tsx
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { OfflineBanner } from "./OfflineBanner";

let online = true;

beforeEach(() => {
  online = true;
  vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function goOffline() {
  online = false;
  act(() => window.dispatchEvent(new Event("offline")));
}

function goOnline() {
  online = true;
  act(() => window.dispatchEvent(new Event("online")));
}

test("renders nothing while online", () => {
  render(<OfflineBanner />);
  expect(screen.queryByText(/offline/i)).not.toBeInTheDocument();
});

test("shows a banner naming the outage time when the browser goes offline", () => {
  render(<OfflineBanner />);
  goOffline();
  expect(screen.getByText(/offline — showing cached data as of/i)).toBeInTheDocument();
});

test("hides again once back online", () => {
  render(<OfflineBanner />);
  goOffline();
  goOnline();
  expect(screen.queryByText(/offline/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- OfflineBanner`
Expected: FAIL — `Cannot find module './OfflineBanner'`.

- [ ] **Step 3: Implement the banner**

```tsx
// frontend/src/ui/OfflineBanner.tsx
import { useEffect, useState } from "react";

const fmtTime = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

export function OfflineBanner() {
  const [since, setSince] = useState<Date | null>(() => (navigator.onLine ? null : new Date()));

  useEffect(() => {
    const onOffline = () => setSince(new Date());
    const onOnline = () => setSince(null);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, []);

  if (!since) return null;

  return (
    <p
      role="status"
      className="mb-4 rounded-lg border border-line bg-[rgba(232,120,90,0.08)] px-3 py-2 text-[13px] text-clay"
    >
      Offline — showing cached data as of {fmtTime(since)}.
    </p>
  );
}
```

`since` is the moment the browser reported going offline, not a per-query last-fetch time —
TanStack Query tracks that per query, not globally, and this banner is one line for the whole
page. Close enough to be honest without adding a query-cache-wide "most recent success" tracker
nothing else needs (spec's own §3.2 asks for "as of {time}", not a precise data-freshness audit).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- OfflineBanner`
Expected: PASS, all three tests.

- [ ] **Step 5: Render it in the Shell**

```tsx
// frontend/src/ui/Shell.tsx — add the import
import { OfflineBanner } from "./OfflineBanner";

// and render it as the first child of <main>, before {children}:
        <main className="min-w-0 flex-1 px-5 py-6 pb-28 md:px-10 md:py-12 md:pb-12">
          <div className="mx-auto w-full max-w-5xl">
            <OfflineBanner />
            {children}
          </div>
        </main>
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/ui/OfflineBanner.tsx frontend/src/ui/OfflineBanner.test.tsx frontend/src/ui/Shell.tsx
git commit -m "feat: offline banner driven by navigator.onLine"
```

---

## Task 5: Responsive audit — dual-render the three tables that overflow at 360px

Verified against the actual components (not guessed): at a 360px viewport, `Shell`'s
`main` padding (`px-5` = 20px each side) plus `Card`'s `p-5` (20px each side) leaves ~280px of
content width. `holdings.tsx`/`HoldingsList` already solves this with a `hidden md:table` table
plus a `md:hidden` `<ul>` of cards — this task applies the same pattern to the three components
whose tables genuinely exceed 280px:

- `TxnRows` (`transactions.tsx`) — date (96px) + merchant + a `<select>` category picker (~110px
  min) + amount. Shared by three pages: `TransactionsPage` (via `TransactionList`),
  `AccountDetailPage`, and `OverviewPage`'s "Recent activity" card — fixing `TxnRows` once fixes
  all three.
- `BudgetBoard` — category name + a `w-24` input + a rollover checkbox+label + a `w-32` progress
  bar + two right-aligned amounts. Six columns; the widest single offender in the app.
- `TaxCard`'s realized-gains table (`ReportsCards.tsx`) — symbol + date + term + gain. Narrower
  than the other two, but the spec (§3.4) names `ReportsCards.tsx` explicitly, and its own e2e
  test in Task 6 visits `/reports` at 360px, so it needs to actually pass.

**Cut from this task:** `CategoryCards.tsx`'s three tables (rules, uncategorized-suggestions,
uncategorized-fallback) — each is 2-3 short columns (a merchant string, a category name, one or
two small buttons) that fit inside 280px as-is; and `GoalCards.tsx`, which was never a table.
Global tap-target sizing (`input`/`.btn` padding in `index.css`) is also cut — spec §3.4 calls it
only a "likely finding," the existing ~38px control height isn't a functional blocker, and
widening it is a global visual change to every desktop surface too, for a phone-only concern
that isn't demonstrated by anything in this task's actual audit.

**Files:**
- Modify: `frontend/src/transactions.tsx:11-21` (`TxnRows`)
- Modify: `frontend/src/transactions.test.tsx`
- Modify: `frontend/src/BudgetBoard.tsx:97-153`
- Modify: `frontend/src/BudgetBoard.test.tsx`
- Modify: `frontend/src/ReportsCards.tsx:126-138` (`TaxCard`'s gains table)

**Interfaces:** No exported signatures change — `TxnRows({ txns })`, `BudgetBoard({ month,
onMonthChange })`, `TaxCard({ year })` all keep their existing props.

### 5a — `TxnRows`

- [ ] **Step 1: Update the existing tests for dual-render, before touching the component**

Every test in `transactions.test.tsx` that queries by a label/text unique to one `TxnRow` will
now find two matches (table row + card) once Step 2 ships. Update them the same way
`holdings.test.tsx` already did:

```typescript
// frontend/src/transactions.test.tsx — replace the five affected tests' query calls.
// "keeps the chosen category visible while its PATCH is in flight":
render(<TxnRows txns={[txn]} />, { wrapper });
const selects = (await screen.findAllByLabelText(
  "Category for Whole Foods",
)) as HTMLSelectElement[];
await screen.findAllByRole("option", { name: "B" });
for (const select of selects) fireEvent.change(select, { target: { value: "c2" } });
await waitFor(() => selects.forEach((s) => expect(s.value).toBe("c2")));
```

Apply the same `findAllByLabelText`/loop-over-matches shape to the other four tests in that file
that call `findByLabelText("Category for Whole Foods")` (`"keeps the chosen category visible
after the PATCH succeeds..."`, `"shows the PATCH error message..."`, `"keeps the rule prompt
open..."`) and to the two `renderList()`-based tests at the top of the file
(`"renders transactions with a short date"`, `"signs amounts..."`), which switch `getByText` to
`getAllByText(...)[0]` (either match — table or card — renders the identical string).

- [ ] **Step 2: Run the tests to verify they fail against the *old* single-render component**

Run: `cd frontend && npm test -- transactions.test`
Expected: FAIL — `findAllByLabelText` etc. now expect 2 matches but the unmodified component
still renders 1 (or the tests fail for the opposite reason if run before Step 1 — either way,
confirm they don't silently pass yet).

- [ ] **Step 3: Give `TxnRows` a card rendering, mirroring `HoldingsList`'s pattern**

```tsx
// frontend/src/transactions.tsx — replace the existing TxnRows/TxnRow pair (lines 11-112)
export function TxnRows({ txns }: { txns: Txn[] }) {
  return (
    <>
      <table className="hidden w-full md:table">
        <tbody>
          {txns.map((t, i) => (
            <TxnRow key={t.id} txn={t} index={i} />
          ))}
        </tbody>
      </table>
      {/* Mobile: not a table — four columns plus a select don't fit in 280px. */}
      <ul className="flex flex-col gap-3 md:hidden">
        {txns.map((t, i) => (
          <TxnCard key={t.id} txn={t} index={i} />
        ))}
      </ul>
    </>
  );
}

function useCategoryMutation(txn: Txn) {
  const qc = useQueryClient();
  const createRule = useCreateRule();
  const [askAbout, setAskAbout] = useState<string | null>(null);
  const [pendingCategory, setPendingCategory] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    if (pendingCategory !== undefined && txn.category_id === pendingCategory) {
      setPendingCategory(undefined);
    }
  }, [txn.category_id, pendingCategory]);

  const setCategory = useMutation({
    mutationFn: (categoryId: string | null) =>
      apiFetch(`/transactions/${txn.id}`, {
        method: "PATCH",
        body: JSON.stringify({ category_id: categoryId }),
      }),
    onSuccess: (_data, categoryId) => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["uncategorized"] });
      if (categoryId) setAskAbout(categoryId);
    },
    onError: () => setPendingCategory(undefined),
  });

  return { createRule, askAbout, setAskAbout, pendingCategory, setPendingCategory, setCategory };
}

function TxnRow({ txn, index }: { txn: Txn; index: number }) {
  const { createRule, askAbout, setAskAbout, pendingCategory, setPendingCategory, setCategory } =
    useCategoryMutation(txn);

  return (
    <>
      <tr
        className="rise border-b border-line/60 transition-colors last:border-0 hover:bg-[rgba(237,234,228,0.02)]"
        style={{ "--d": `${Math.min(index, 12) * 30}ms` } as React.CSSProperties}
      >
        <td className="tnum w-24 py-3 text-[13px] text-muted">{shortDate(txn.posted_at)}</td>
        <td className="py-3 text-sm">{txn.merchant_raw}</td>
        <td className="py-3">
          <CategoryPicker
            value={pendingCategory !== undefined ? pendingCategory : txn.category_id}
            onChange={(id) => {
              setPendingCategory(id);
              setCategory.mutate(id);
            }}
            ariaLabel={`Category for ${txn.merchant_raw}`}
          />
          {setCategory.isError && (
            <p className="mt-1 text-[13px] text-clay">{(setCategory.error as Error).message}</p>
          )}
        </td>
        <td
          className={`tnum py-3 text-right text-sm ${
            Number(txn.amount) > 0 ? "text-acid" : "text-bone"
          }`}
        >
          {Number(txn.amount) > 0 ? `+${usd(txn.amount)}` : usd(txn.amount)}
        </td>
      </tr>
      {askAbout && (
        <tr>
          <td colSpan={4} className="pb-3 text-[13px] text-muted">
            <RuleOffer merchant={txn.merchant_raw} categoryId={askAbout} createRule={createRule} onDone={() => setAskAbout(null)} />
          </td>
        </tr>
      )}
    </>
  );
}

function TxnCard({ txn, index }: { txn: Txn; index: number }) {
  const { createRule, askAbout, setAskAbout, pendingCategory, setPendingCategory, setCategory } =
    useCategoryMutation(txn);

  return (
    <li
      className="rise card p-3"
      style={{ "--d": `${Math.min(index, 12) * 30}ms` } as React.CSSProperties}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm">{txn.merchant_raw}</p>
          <p className="tnum text-[12px] text-muted">{shortDate(txn.posted_at)}</p>
        </div>
        <span
          className={`tnum shrink-0 text-sm ${Number(txn.amount) > 0 ? "text-acid" : "text-bone"}`}
        >
          {Number(txn.amount) > 0 ? `+${usd(txn.amount)}` : usd(txn.amount)}
        </span>
      </div>
      <div className="mt-2">
        <CategoryPicker
          value={pendingCategory !== undefined ? pendingCategory : txn.category_id}
          onChange={(id) => {
            setPendingCategory(id);
            setCategory.mutate(id);
          }}
          ariaLabel={`Category for ${txn.merchant_raw}`}
        />
        {setCategory.isError && (
          <p className="mt-1 text-[13px] text-clay">{(setCategory.error as Error).message}</p>
        )}
      </div>
      {askAbout && (
        <div className="mt-2 text-[13px] text-muted">
          <RuleOffer merchant={txn.merchant_raw} categoryId={askAbout} createRule={createRule} onDone={() => setAskAbout(null)} />
        </div>
      )}
    </li>
  );
}

function RuleOffer({
  merchant,
  categoryId,
  createRule,
  onDone,
}: {
  merchant: string;
  categoryId: string;
  createRule: ReturnType<typeof useCreateRule>;
  onDone: () => void;
}) {
  return (
    <>
      Always categorize “{merchant}” this way?{" "}
      <button
        className="text-acid"
        onClick={() => createRule.mutate({ pattern: merchant, category_id: categoryId }, { onSuccess: onDone })}
      >
        Make it a rule
      </button>{" "}
      <button className="ml-2" onClick={onDone}>
        No
      </button>
      {createRule.isError && <p className="mt-1 text-clay">{(createRule.error as Error).message}</p>}
    </>
  );
}
```

`useCategoryMutation` is lifted out of the old single `TxnRow` so both the table row and the
card share one mutation instance's *shape* — each still gets its own hook call (React requires
that), but the logic that used to live inline is now identical between the two renderings instead
of drifting.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npm test -- transactions.test`
Expected: PASS, all six tests.

### 5b — `BudgetBoard`

- [ ] **Step 5: Update `BudgetBoard.test.tsx` for dual-render**

```typescript
// frontend/src/BudgetBoard.test.tsx — every test that asserts a single row's text/label now
// has two matches (table row + card). Representative diff for two of the six tests:

it("shows the category name, actual, and remaining", async () => {
  vi.mocked(apiFetch).mockResolvedValue([row()]);
  show();
  expect((await screen.findAllByText("Groceries")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("$40.00").length).toBeGreaterThan(0);
  expect(screen.getAllByText("$60.00").length).toBeGreaterThan(0);
});

it("filling in an amount and saving PUTs the new budget", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string, opts?: RequestInit) => {
    if (path === "/budgets/2026-07" && opts?.method === "PUT") return [];
    return [row()];
  });
  show();
  const [input] = await screen.findAllByLabelText("Budget for Groceries");
  fireEvent.change(input, { target: { value: "150" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Save changes" })[0]);
  await waitFor(() =>
    expect(apiFetch).toHaveBeenCalledWith(
      "/budgets/2026-07",
      expect.objectContaining({ method: "PUT" }),
    ),
  );
});
```

Apply the same `findAllBy*`/`getAllBy*` change to the remaining four tests
(`"has no save button..."` stays as-is — it asserts absence, which is unaffected by dual-render;
`"shows the carry-in..."`, `"does not show a carry-in..."`, `"disables save..."` each switch their
single-match query to the `findAllBy*`/`[0]` shape above). The drafts state lives in the parent
`BudgetBoard`, not per-rendering, so a value typed into the table's input and one typed into the
card's input for the *same* category would both write to the same `drafts[categoryId]` entry —
Step 6 keeps that shared-state design, it just renders two inputs bound to it instead of one.

- [ ] **Step 6: Give `BudgetBoard` a card rendering**

```tsx
// frontend/src/BudgetBoard.tsx — replace the <table> block (the existing lines 97-153)
      {isLoading ? (
        <Empty>Loading…</Empty>
      ) : rows.length === 0 ? (
        <Empty>No categories yet.</Empty>
      ) : (
        <>
          <table className="hidden w-full md:table">
            <tbody>
              {rows.map((r) => (
                <BudgetRow
                  key={r.category_id}
                  row={r}
                  draft={drafts[r.category_id]}
                  onDraft={(v) => setDraft(r.category_id, v)}
                  onToggleRollover={() => toggleRollover(r.category_id, r.rollover, r.budgeted)}
                />
              ))}
            </tbody>
          </table>
          <ul className="flex flex-col gap-3 md:hidden">
            {rows.map((r) => (
              <BudgetCard
                key={r.category_id}
                row={r}
                draft={drafts[r.category_id]}
                onDraft={(v) => setDraft(r.category_id, v)}
                onToggleRollover={() => toggleRollover(r.category_id, r.rollover, r.budgeted)}
              />
            ))}
          </ul>
        </>
      )}
```

```tsx
// frontend/src/BudgetBoard.tsx — add above the BudgetBoard function
function fillPctOf(r: BudgetItem & { effective_budget: string; actual: string }) {
  const effective = Number(r.effective_budget);
  const actual = Number(r.actual);
  return effective > 0 ? Math.min((actual / effective) * 100, 100) : 0;
}

function BudgetRow({
  row: r,
  draft,
  onDraft,
  onToggleRollover,
}: {
  row: ReturnType<typeof useBudgetStatus>["data"] extends (infer T)[] | undefined ? T : never;
  draft: string | undefined;
  onDraft: (v: string) => void;
  onToggleRollover: () => void;
}) {
  const fillPct = fillPctOf(r);
  const overPace = r.pace !== null && r.pace > 1;
  return (
    <tr className="border-b border-line/60 last:border-0">
      <td className="py-2 text-sm">{r.category_name}</td>
      <td className="py-2">
        <input
          aria-label={`Budget for ${r.category_name}`}
          value={draft ?? r.budgeted}
          onChange={(e) => onDraft(e.target.value)}
          className="w-24 text-[13px]"
        />
        {Number(r.carry_in) !== 0 && (
          <span className="ml-2 text-[12px] text-muted">+{usd(r.carry_in)} carried in</span>
        )}
      </td>
      <td className="py-2">
        <label className="flex items-center gap-1 text-[12px] text-muted">
          <input
            type="checkbox"
            aria-label={`Roll over ${r.category_name}`}
            checked={r.rollover}
            onChange={onToggleRollover}
          />
          Roll over
        </label>
      </td>
      <td className="w-32 py-2">
        <div className="h-1.5 w-full rounded-full bg-line/60">
          <div
            className={`h-1.5 rounded-full ${overPace ? "bg-amber-400" : "bg-acid"}`}
            style={{ width: `${fillPct}%` }}
          />
        </div>
      </td>
      <td className="tnum py-2 text-right text-[13px]">{usd(r.actual)}</td>
      <td
        className={`tnum py-2 text-right text-[13px] ${
          Number(r.remaining) < 0 ? "text-amber-400" : "text-muted"
        }`}
      >
        {usd(r.remaining)}
      </td>
    </tr>
  );
}

function BudgetCard({
  row: r,
  draft,
  onDraft,
  onToggleRollover,
}: {
  row: ReturnType<typeof useBudgetStatus>["data"] extends (infer T)[] | undefined ? T : never;
  draft: string | undefined;
  onDraft: (v: string) => void;
  onToggleRollover: () => void;
}) {
  const fillPct = fillPctOf(r);
  const overPace = r.pace !== null && r.pace > 1;
  return (
    <li className="card p-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm">{r.category_name}</span>
        <span
          className={`tnum text-sm ${Number(r.remaining) < 0 ? "text-amber-400" : "text-muted"}`}
        >
          {usd(r.remaining)} left
        </span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-line/60">
        <div
          className={`h-1.5 rounded-full ${overPace ? "bg-amber-400" : "bg-acid"}`}
          style={{ width: `${fillPct}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <input
          aria-label={`Budget for ${r.category_name}`}
          value={draft ?? r.budgeted}
          onChange={(e) => onDraft(e.target.value)}
          className="w-24 text-[13px]"
        />
        <span className="tnum text-[13px] text-muted">actual {usd(r.actual)}</span>
      </div>
      <div className="mt-2 flex items-center justify-between text-[12px] text-muted">
        {Number(r.carry_in) !== 0 ? <span>+{usd(r.carry_in)} carried in</span> : <span />}
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            aria-label={`Roll over ${r.category_name}`}
            checked={r.rollover}
            onChange={onToggleRollover}
          />
          Roll over
        </label>
      </div>
    </li>
  );
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd frontend && npm test -- BudgetBoard.test`
Expected: PASS, all six tests.

### 5c — `TaxCard`'s gains table

`ReportsCards.test.tsx`'s `TaxCard` test uses `gains: []`, so it never renders the gains table —
no existing test needs a dual-render update here, only the component.

- [ ] **Step 8: Give the gains table a card rendering**

```tsx
// frontend/src/ReportsCards.tsx — replace the gains <table> block (existing lines 126-138)
      {gains.gains.length === 0 ? (
        <Empty>No realized sales in {year}.</Empty>
      ) : (
        <>
          <table className="hidden w-full md:table">
            <tbody>
              {gains.gains.map((g, i) => (
                <tr key={i} className="border-b border-line/60 last:border-0">
                  <td className="py-2 text-sm">{g.symbol}</td>
                  <td className="py-2 text-[13px] text-muted">{g.closed_on}</td>
                  <td className="py-2 text-[13px] text-muted">{g.term}</td>
                  <td className="tnum py-2 text-right text-sm">{usd(g.gain)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="flex flex-col gap-2 md:hidden">
            {gains.gains.map((g, i) => (
              <li key={i} className="flex items-center justify-between gap-3 border-b border-line/60 py-2 text-[13px] last:border-0">
                <span>
                  <span className="text-sm">{g.symbol}</span>{" "}
                  <span className="text-muted">· {g.closed_on} · {g.term}</span>
                </span>
                <span className="tnum shrink-0">{usd(g.gain)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
```

- [ ] **Step 9: Run the full frontend unit suite**

Run: `cd frontend && npm test`
Expected: PASS — every test file, no regressions in files this task didn't touch.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/transactions.tsx frontend/src/transactions.test.tsx frontend/src/BudgetBoard.tsx frontend/src/BudgetBoard.test.tsx frontend/src/ReportsCards.tsx
git commit -m "fix: card layout for the three tables that overflow at 360px"
```

---

## Task 6: e2e — PWA installability, offline caching, and the 360px audit

The manifest and service worker only mean anything against a production build (`import.meta.env.PROD`
gates registration — Task 3, Step 2), but every other e2e spec in this repo runs against `npm run
dev`. Rather than change that shared server for every other spec file, this task adds a *second*
Playwright `webServer` entry that builds and previews the app, and points only the new spec file
at it.

**Files:**
- Modify: `frontend/playwright.config.ts`
- Create: `frontend/e2e/pwa.spec.ts`
- Modify: `frontend/e2e/mobile.spec.ts`

**Interfaces:** None — e2e-only, no production code.

- [ ] **Step 1: Add the preview server to the Playwright config**

```typescript
// frontend/playwright.config.ts
import { defineConfig } from "@playwright/test";

// Assumes the API stack is up: `docker compose up -d`.
export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    { command: "npm run dev", url: "http://localhost:5173", reuseExistingServer: true },
    // Service worker registration is gated on import.meta.env.PROD (see src/main.tsx) —
    // it's meaningless against unbundled dev-mode modules. pwa.spec.ts targets this one
    // instead of the default baseURL above.
    {
      command: "npm run build && npm run preview -- --port 4174",
      url: "http://localhost:4174",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
```

- [ ] **Step 2: Write `pwa.spec.ts`**

```typescript
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
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await context.setOffline(false);
});

test("a page visited online stays readable offline from the API cache", async ({
  page,
  context,
}) => {
  await page.goto("/accounts");
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
  await page.waitForLoadState("networkidle"); // let the GET /accounts response land in the cache

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
  await expect(page.getByText(/offline — showing cached data as of/i)).toBeVisible();
  await context.setOffline(false);
});
```

- [ ] **Step 3: Extend `mobile.spec.ts` with the 360px audit pass**

```typescript
// frontend/e2e/mobile.spec.ts — add below the existing test, in the same file
test.describe("360px width audit", () => {
  test.use({ viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true });

  const noHorizontalScroll = async (page: import("@playwright/test").Page) => {
    const overflow = await page.evaluate(() => {
      const docWidth = document.documentElement.clientWidth;
      return document.scrollingElement!.scrollWidth > docWidth + 1;
    });
    expect(overflow).toBe(false);
  };

  const pages: [string, string][] = [
    ["/", "Overview"],
    ["/accounts", "Accounts"],
    ["/transactions", "Transactions"],
    ["/budgets", "Budgets"],
    ["/goals", "Goals"],
    ["/reports", "Reports"],
  ];

  for (const [path, heading] of pages) {
    test(`${path || "/"} has no horizontal scroll at 360px`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
      await page.waitForTimeout(600); // let async data settle before measuring layout
      await noHorizontalScroll(page);
    });
  }
});
```

- [ ] **Step 4: Run the full e2e suite**

Run: `cd frontend && docker compose up -d && npm run e2e`
Expected: PASS — every spec file, including the new `pwa.spec.ts` and the extended
`mobile.spec.ts`.

- [ ] **Step 5: Run the full gate set one more time**

```bash
cd frontend
npm test
npm run build
npm run lint
npm run e2e
```
Expected: all four green. Paste the output — this is the phase-done gate per `TASK.md`, not an
assertion.

- [ ] **Step 6: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e/pwa.spec.ts frontend/e2e/mobile.spec.ts
git commit -m "test: pwa installability, offline caching, and a 360px viewport audit"
```

---

## Self-review notes

**Spec coverage (§3):** 3.1 installability → Task 2 + Task 3. 3.2 offline read cache → Task 3 +
Task 4. 3.3 mobile nav bug → Task 1. 3.4 responsive polish → Task 5 (tables; tap targets
explicitly cut with reasoning, matching the spec's own "likely findings" framing rather than a
requirement). Tests section → Task 6 covers manifest validity, SW-offline-shell,
API-cache-fallback, `mobile.spec.ts` passing, and the 360px pass across the six named pages.

**Placeholder scan:** no TBD/"add error handling"/"similar to Task N" — every step above either
has runnable code or a runnable command with an expected result.

**Type consistency:** `TxnRows({ txns })`, `BudgetBoard({ month, onMonthChange })`, `TaxCard({
year })` are unchanged externally. `InstallBanner`/`OfflineBanner` are both zero-prop, matching
every other file in `ui/`. Cache names (`SHELL_CACHE`/`API_CACHE`) and the registration path
(`/service-worker.js`) referenced in Task 3 are the exact strings Task 6's assertions check.
