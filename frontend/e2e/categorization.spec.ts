import { expect, test } from "@playwright/test";

// Runs against `docker compose up`, which sets LOCAL_MODE=true — no login involved.
// Names are unique per run so the assertions hold against a database that already
// has data in it, same convention as smoke.spec.ts.
test("a rule categorizes an imported transaction", async ({ page }) => {
  const stamp = Date.now();
  const account = `Rules Checking ${stamp}`;
  const pattern = `whole foods ${stamp}`;
  const merchant = `WHOLE FOODS ${stamp} #4471`;

  await page.goto("/accounts");
  await page.getByPlaceholder("Main Checking").fill(account);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(account)).toBeVisible();

  await page.goto("/transactions");
  await page.getByLabel("Account", { exact: true }).selectOption({ label: account });

  // Create the rule.
  await page.getByLabel("Merchant contains").fill(pattern);
  await page.getByLabel("Rule category").selectOption({ label: "Groceries" });
  await page.getByRole("button", { name: "Add rule" }).click();
  await expect(page.getByText(pattern)).toBeVisible();

  // Add a matching transaction via CSV import. Manual single-row entry
  // (`POST /transactions`, `NewTransactionForm`) is not wired to the categorizer —
  // `app/services/transactions.py::create` never calls `apply_to`. Only CSV import and
  // bank sync categorize on the way in (see `csv_import.py` / `sync.py`, Task 4), so the
  // import path is what actually exercises "a rule categorizes an imported transaction".
  await page.getByLabel("Import CSV").setInputFiles({
    name: "txns.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`date,amount,merchant\n2026-07-01,-42.00,${merchant}\n`),
  });
  await expect(page.getByText(/Imported 1, skipped 0/)).toBeVisible();

  // It arrives categorized — no manual step in between.
  await expect(page.getByLabel(`Category for ${merchant}`)).toHaveValue(/.+/);

  // Clean up after ourselves — this runs against the real local database.
  await page.getByRole("button", { name: `Delete ${pattern}` }).click();
  await page.goto("/accounts");
  await page.getByRole("button", { name: `Remove ${account}` }).click();
  await page.getByRole("button", { name: "Delete account and its transactions" }).click();
  await expect(page.getByText(`${account} (checking)`)).toHaveCount(0);
});
