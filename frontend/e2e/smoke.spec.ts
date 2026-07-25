import { test, expect } from "@playwright/test";

// Runs against `docker compose up`, which sets LOCAL_MODE=true — no login involved.
// Names are unique per run so the assertions hold against a database that already
// has data in it.
test("add account → add transaction → import CSV → see it on the overview", async ({ page }) => {
  const stamp = Date.now();
  const account = `Checking ${stamp}`;
  const typed = `Typed ${stamp}`;
  const imported = `Imported ${stamp}`;

  await page.goto("/accounts");
  await page.getByPlaceholder("Main Checking").fill(account);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(account)).toBeVisible();

  await page.goto("/transactions");
  await page.getByLabel("Account", { exact: true }).selectOption({ label: account });
  await page.getByLabel("Date").fill("2026-01-15");
  await page.getByPlaceholder("Merchant", { exact: true }).fill(typed);
  await page.getByLabel("Amount").fill("-9.99");
  await page.getByRole("button", { name: "Add transaction" }).click();
  await expect(page.getByRole("cell", { name: typed })).toBeVisible();

  await page.getByLabel("Import CSV").setInputFiles({
    name: "txns.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`date,amount,merchant\n2026-02-01,-4.50,${imported}\n`),
  });
  await expect(page.getByText(/Imported 1, skipped 0/)).toBeVisible();
  await expect(page.getByRole("cell", { name: imported })).toBeVisible();

  // Search narrows the history to just the typed transaction.
  await page.getByPlaceholder("Search merchant…").fill(typed);
  await expect(page.getByRole("cell", { name: typed })).toBeVisible();
  await expect(page.getByRole("cell", { name: imported })).toHaveCount(0);

  await page.goto("/");
  await expect(page.getByText("Net worth")).toBeVisible();
});
