import { expect, test } from "@playwright/test";

// Runs against `docker compose up`, which sets LOCAL_MODE=true — no login involved.
test("setting a budget persists across a reload", async ({ page }) => {
  await page.goto("/budgets");
  await page.getByLabel("Budget for Groceries").fill("325");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);

  await page.reload();
  await expect(page.getByLabel("Budget for Groceries")).toHaveValue("325.0000");
});

test("Budgets is reachable from the mobile More menu", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "More" });
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("menuitem", { name: "Budgets" }).click();
  await expect(page).toHaveURL(/\/budgets$/);
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
});
