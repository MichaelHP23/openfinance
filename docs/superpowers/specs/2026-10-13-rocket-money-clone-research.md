# Rocket Money PC experience — research and clone plan

**Date:** 2026-10-13
**Status:** Research complete for everything reachable without an account. §8 steps 1–4 and Net Worth from step 5 are built and live; the recurring ••• menu, Spending, budget rings, and category icon/colour are not.
**Why this exists:** three rounds of restyling did not make the app look like Rocket Money. The earlier spec (`2026-10-12-rocket-money-features-design.md`) inventoried *features* from public docs; nobody had looked at the *screens*. This document is the screens.

## 1. Tools: what was found, used, and blocked

| Tool | Used | Notes |
|---|---|---|
| REA (`morluto/rea`, npm `rea-agents` 6.4.0) | Yes, after the user approved it | `list-browser-targets`, `inspect-web-page`, `analyze-web-bundle` against a throwaway headless browser. Result: `app.rocketmoney.com` lands on `auth.rocketaccount.com/authorize` with no application code served; on `www.rocketmoney.com` it enumerated the public feature pages. Nothing about the logged-in app, as expected. Its native-analysis engines (Hopper, Ghidra, IDA) are not installed and not relevant to a website. |
| Playwright (already in `frontend/`) | Yes | Followed `app.rocketmoney.com` to its login redirect; crawled the public help centre. Never submitted a login form. |
| GitHub CLI | Yes | Read REA's README. |
| Claude-in-Chrome extension | Available, unused | The route for observing a logged-in session, if the user logs in themselves and says to proceed. |
| `frontend-design` skill | Loaded earlier | For the build phase. |
| Subagents | Not used | Standing instruction on this repo is one at a time; the crawl was one script. |

## 2. Confirmed facts about the PC experience

Evidence is the public help centre (`help.rocketmoney.com`, 15 collections, 140 articles, read 2026-10-13) unless stated.

- **It is a website, not an installed Windows program.** `app.rocketmoney.com` redirects to `auth.rocketaccount.com/authorize` before serving any application code (observed). No web-app manifest or service worker is exposed on the login page (observed).
- **The website is Premium-only.** "The Rocket Money website will now be exclusively available to Premium members." Without Premium a logged-in user can reach only profile, linked accounts, and notification settings. ("Rocket Money for desktop".)
- **Demo mode does not exist on the website** — mobile only. ("Using demo mode".) So there is no legitimate way to see the desktop app without a paying account.
- **The help centre has no desktop screenshots.** 33 unique screenshots, all phone-shaped. Desktop layout is known only from the wording of step-by-step instructions (§3).

## 3. Desktop navigation, from the help centre's own instructions

Quoted positions are theirs.

- **Left sidebar** ("along the left side of the screen", "left hand sidebar"): Dashboard, Recurring, Transactions, Budgets, Net Worth. A **Calendar** heading holds subscriptions and bills. Mobile's tab bar adds **Spending**.
- **Settings gear, top-left of the sidebar "next to your name"**, opening a side menu: Profile (Change Email, Share Account, Delete Account), Linked Accounts (+ Add Institution, View, ••• → Unlink, hide toggle), Categories (New Category: name, icon, colour, group = Expenses / Earnings / Ignored), Transaction Rules (New Rule: Match on Name, Match on Amount, then updates to apply), Notifications (Alerts / Updates / Tips, email and push each), Membership (Manage → price slider), Logout last.
- **"Go Premium" under the user's name**, top-left, for free users.
- **Dashboard:** an **Accounts section "in the top right"**; clicking a category opens the account, with **connection status "at the top right"**. A **Savings section "along the right side"** expands to goals; a goal page has **Recent Transfers**.
- **Transactions:** search bar; **hover a row** to edit category, name, etc.; **checkbox at the left of each row**, multi-select, then a bulk **Ignore** with two choices (one is "Ignore from Budgets"); **Export** with filters, delivered by email.
- **Recurring:** **View All** for the full list; **•••** at the right of each row → "Cancel this for me".
- **Net Worth:** three screens "along the top": **Summary, Assets, Debts**; "Link Accounts"; "Include homes" toggle on Summary.
- **Budgets:** "Start My Budget", then a three-step setup beginning with monthly income.

**Not available on the website** (mobile only, stated article by article): manual transactions, tags, splitting, Payday View, low-balance alert customisation, manual subscriptions, Apple subscriptions, creating or funding goals, home-value edits, payment-method updates, password change.

## 4. Visual language, from the 33 help-centre screenshots (phone)

- **Header:** a crimson-to-raspberry gradient band. Gear top-left, wordmark centred, bell top-right. On inner screens the title replaces the wordmark (e.g. "Transactions") and a search field sits inside the band.
- **Page:** very light grey. **Cards:** white, large radius, hairline or no border, soft shadow. Section labels are small, grey, upper-case, letter-spaced ("ACCOUNTS", "UPCOMING", "YOUR BUDGET", "CONNECTION STATUS").
- **Type:** a geometric sans, medium weight for headings and figures; figures are *not* monospaced. Near-black text.
- **Dashboard order:** (1) white hero card overlapping the header band — "Current spend this month", big figure, a ✓ badge "$98 below avg. spend", blue line with a pale lavender fill, a dashed "BUDGET" line, then a "Payday in 8 days" row; three pager dots. (2) ACCOUNTS with "Add account" link — rows Checking, Card Balance, Net Cash (green), Savings, Investments; outline icon, amount, chevron to expand; expanded Savings shows the bank row and FINANCIAL GOALS with a progress bar and "+ New Goal". (3) UPCOMING — a horizontal row of small tiles: merchant logo, name, amount, "TODAY" / "IN 1 DAY" / "IN 5 DAYS". (4) Offer cards ("Lower your bills").
- **Bottom tabs:** Dashboard, Recurring, Spending, Transactions, More — outline icons, the active one crimson with a crimson line above it.
- **Transactions list:** month header with "$2,398 total spend" at right; rows = coloured round category icon, merchant, "Jan 25 | Pending" plus small tag chips, amount at right.
- **Transaction detail sheet:** lavender top with date, merchant, amount, a category pill; then rows Rename · Is Recurring? (toggle) · Is Tax Deductible? (toggle) · Ignore (dropdown "Don't Ignore") · Add Note · Create Rule · Split; an outlined **Delete** pill.
- **Add a Transaction:** crimson top, Spend / Income segmented control, fields Name, Date, Amount, Category, a black full-width **Save** pill.
- **Spending** (from `rocketmoney.com/feature/spending-insights`): crimson band holding a Week / Month / Quarter / Year segmented control and a row of per-period bars (income beside spending, the selected period outlined); below it a white card with rows Earnings, Total Spend, Net Income (green).
- **Budget:** "Left for Spending $781", a row of round category icons each with a progress ring.
- **Connection status card:** First Synced, Last Synced, Status (Healthy green / Temporary Issue amber / Delayed amber) with an ⓘ; outlined "Sync Account" pill, or a filled amber "Fix Connection".
- **Settings menu:** a list of bordered rows — Refer a Friend, Chat, Leave Demo Mode, Profile, Share Account, Manage Budget, Categories Tags & Rules, Linked Accounts, Notifications & Alerts, App Appearance, Premium membership.
- **Buttons:** black filled pill for the primary action; white pill with a dark outline for secondary.

## 5. Feature matrix

Status: **C** confirmed (screenshot or explicit instruction), **P** partly observed, **I** inferred.

| Feature | Observed behaviour | Evidence | Dependencies | Implementation plan here | Status |
|---|---|---|---|---|---|
| Dashboard hero | Spend this month, vs-average badge, cumulative line with budget line, payday row | Screenshots | Transactions, budget, income detection | Exists (`SpendHero`); add the dashed budget line and "avg. spend" (3-month mean) instead of last month | C |
| Accounts roll-up | Five groups, expandable to accounts and goals, "Add account" | Screenshots; "Accounts section top right" on desktop | Linked accounts | Exists (`accountGroups`); make rows expand; move to the top-right on desktop | C |
| Upcoming | Horizontal tiles with logo, amount, days-until | Screenshots | Recurring detection | Rebuild the Upcoming card as tiles; merchant logos → coloured initial discs (no logo assets) | C |
| Transactions list | Month groups with total; icon, merchant, date, pending, tags, amount | Screenshots | Categories | Rebuild list: month headers with totals, category icon discs | C |
| Row editing on desktop | Hover to edit; checkbox column; bulk Ignore | Instructions | — | Add checkbox column and a bulk action bar | C (wording only) |
| Transaction detail | Rename, recurring, tax-deductible, ignore, note, rule, split, delete | Screenshot | — | Slide-over panel; rename → `merchant_normalized`, note → `notes`, tax → tag `tax`, ignore → P12; split stays cut | C |
| Search and export | Search bar; Export with filters, emailed | Instructions | Email | Search exists; export exists as a direct download (no email infrastructure) | C |
| Categories | Custom, with icon, colour, group Expenses / Earnings / Ignored | Instructions | — | Categories exist; add icon and colour columns (one migration) | C |
| Transaction rules | Match on name and amount → updates | Instructions | — | Exists (P1) | C |
| Recurring | List, View All, ••• → cancel request | Instructions; screenshots | Concierge (human) | Exists; cancel is self-serve links (P11) — the human service is out of scope | C |
| Calendar | Bills and subscriptions on a calendar | One sentence | Recurring | New month-grid page from `upcoming` | P |
| Budgets | Start My Budget, 3 steps; "Left for spending"; category rings | Instructions; screenshot | Income | Budgets exist (P2); add the left-for-spending headline and ring row | C |
| Spending | A tab in the mobile bar | Tab label only | — | Map to the existing Reports spending breakdown | I |
| Net Worth | Summary / Assets / Debts tabs; link accounts; include-homes toggle | Instructions | Snapshots | Split the existing chart into a three-tab page | C (wording only) |
| Financial goals | Under Savings; progress bar; transfer history | Screenshot; instructions | Money movement | Goals exist (P3) without transfers — the app cannot move money | C |
| Connection status | First/last synced, status, Sync | Screenshots | Provider | Exists (`services/connections.py`); restyle as their card | C |
| Linked accounts | Add institution, unlink (destroys history), hide from budget | Instructions | SimpleFIN | Exists; add "hide from budget" per account | C |
| Notifications | Alerts / Updates / Tips, email and push | Instructions | Email, push | In-app alerts exist (P9); no delivery channels | C |
| Settings menu | Gear, top-left, list of sections | Screenshot; instructions | — | Move Settings from a sidebar link to a gear by the wordmark | C |
| Share account | Invite a partner by name and email | Instructions | Email | Exists as shareable links (P6) | C |
| AI assistant (Rowan) | Named in the site banner | Banner only | LLM | Exists (advisor); only shows when a key is configured | P |
| Premium / upgrade prompts | Price slider, Go Premium | Instructions | Billing | Not built: nothing to sell | C |
| Credit score, bill negotiation | Present in the app | Screenshots | Bureau, human staff | Cut (unchanged) | C |
| Empty, loading, error states | — | **Not observable** | — | Keep ours | — |

## 6. Honest gap list

- **No desktop pixels.** Everything in §4 is the phone app; §3 is the desktop app described in words. A desktop layout built from this is an informed reconstruction, not a copy.
- **Not observable without an account:** hover and focus states, dialogs, validation messages, empty/loading/error states, exact spacing, breakpoints, the Spending and Calendar pages, charts' interactions.
- **Not reproducible at all:** their logo, wordmark, typeface files, merchant logos, and copy. Brand marks stay out of a public repository; merchant logos become coloured initials.

## 7. What would close the gap

1. **A logged-in session, with the user's say-so.** The website needs Premium. If the user has it, they log in themselves in Chrome; with their go-ahead the session is observed through the Chrome extension — screenshots and DOM only, no credentials or tokens read, real figures kept out of anything committed.
2. **Screenshots from the user.** Lower effort, same value for layout.
3. **REA.** Needs the user to allow running `npx rea-agents`. Against this target it would meet the same login redirect it met on 2026-10-12; it adds evidence only once there is a session to point it at. It does not get past a login and is not being asked to.

## 8. Build order once the reference is settled

1. Shell: crimson gradient top band on every width; sidebar = Dashboard, Recurring, Spending, Transactions, Budgets, Net Worth; gear + name top-left; Settings sections behind the gear.
2. Dashboard to §4's order: hero with budget line and avg-spend badge, expandable Accounts top-right, Upcoming tiles.
3. Transactions: month groups, icon discs, checkbox column with bulk Ignore, detail slide-over.
4. Recurring list with ••• menu; Calendar page.
5. Net Worth as Summary / Assets / Debts; Budgets headline and rings.
6. Category icon and colour (the one migration).

Each step: tests first, then verified on the user's real window (see `TASK.md`), not only in a clean test browser.
