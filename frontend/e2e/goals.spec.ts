import { expect, test } from "@playwright/test";

// Runs against `docker compose up`, which sets LOCAL_MODE=true — no login involved.
test("create a goal, link an account, and see it on the Goals page", async ({ page }) => {
  const stamp = Date.now();
  const account = `Goal Savings ${stamp}`;
  const goalName = `Vacation ${stamp}`;

  await page.goto("/accounts");
  await page.getByPlaceholder("Main Checking").fill(account);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(account)).toBeVisible();

  await page.goto("/goals");
  await page.getByLabel("Goal name").fill(goalName);
  await page.getByLabel("Target amount").fill("2000");
  await page.getByLabel("Linked accounts").selectOption({ label: account });
  await page.getByRole("button", { name: "Add goal" }).click();
  await expect(page.getByText(goalName)).toBeVisible();

  // Clean up after ourselves — this runs against the real local database.
  await page.getByRole("button", { name: `Delete ${goalName}` }).click();
  await expect(page.getByText(goalName)).toHaveCount(0);
  await page.goto("/accounts");
  await page.getByRole("button", { name: `Remove ${account}` }).click();
  await page.getByRole("button", { name: "Delete account and its transactions" }).click();
  await expect(page.getByText(`${account} (savings)`)).toHaveCount(0);
});
