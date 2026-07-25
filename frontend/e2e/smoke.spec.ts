import { test, expect } from "@playwright/test";

test("register → add account → add transaction → import CSV", async ({ page }) => {
  await page.goto("/register");
  await page.getByPlaceholder("Email").fill(`u${Date.now()}@example.com`);
  await page.getByPlaceholder("Password").fill("pw12345");
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page).toHaveURL("http://localhost:5173/");

  await page.getByPlaceholder("Name").fill("Main Checking");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Main Checking (checking)")).toBeVisible();

  await page.getByLabel("Date").fill("2026-01-15");
  await page.getByPlaceholder("Merchant", { exact: true }).fill("Starbucks");
  await page.getByLabel("Amount").fill("-9.99");
  await page.getByRole("button", { name: "Add transaction" }).click();
  await expect(page.getByText("Starbucks")).toBeVisible();

  await page.getByLabel("Import CSV").setInputFiles({
    name: "txns.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("date,amount,merchant\n2026-02-01,-4.50,Amazon\n"),
  });
  await expect(page.getByText("Imported 1, skipped 0")).toBeVisible();
  await expect(page.getByText("Amazon")).toBeVisible();
});
