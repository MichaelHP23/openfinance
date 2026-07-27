import { test, expect } from "@playwright/test";

// iPhone 15 Pro Max dimensions on chromium — webkit isn't installed locally.
test.use({ viewport: { width: 430, height: 932 }, isMobile: true, hasTouch: true });

test("mobile navigation and layout", async ({ page }) => {
  const overflow: string[] = [];

  const checkWidth = async (name: string) => {
    const bad = await page.evaluate(() => {
      const docWidth = document.documentElement.clientWidth;
      return document.scrollingElement!.scrollWidth > docWidth + 1
        ? { scrollWidth: document.scrollingElement!.scrollWidth, docWidth }
        : null;
    });
    if (bad) overflow.push(`${name}: page scrolls sideways ${JSON.stringify(bad)}`);
  };

  await page.goto("/");
  await page.waitForTimeout(1200);
  await checkWidth("overview");

  // Navigate using only what a phone user can see.
  await page.getByRole("link", { name: "Accounts" }).click();
  await page.waitForTimeout(900);
  await expect(page.getByRole("heading", { name: "Accounts" })).toBeVisible();
  await checkWidth("accounts");

  await page.getByRole("link", { name: "Invest" }).click();
  await page.waitForTimeout(900);
  await expect(page.getByRole("heading", { name: "Investments" })).toBeVisible();
  await checkWidth("investments");

  await page.getByRole("link", { name: "Activity" }).click();
  await page.waitForTimeout(900);
  await expect(page.getByRole("heading", { name: "Transactions" })).toBeVisible();
  await checkWidth("transactions");

  // A phone screen that scrolls sideways is the single most common mobile regression here.
  expect(overflow, overflow.join("; ")).toEqual([]);
});
