import { expect, test } from "@playwright/test";

// Runs against `docker compose up`, which does not set ANTHROPIC_API_KEY by default —
// GET /insights/available reports itself unavailable and the whole card disappears,
// so this is the one thing about the assistant that's both deterministic and
// privacy-critical enough to check without mocking the model.
test("the assistant card is absent with no API key configured", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("What's up with my money")).toHaveCount(0);
});
