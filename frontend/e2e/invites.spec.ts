import { test, expect } from "@playwright/test";

// Requires LOCAL_MODE=false on the api container — unlike every other e2e spec here,
// this one exercises the real auth flow (register/login/RBAC), which local mode
// bypasses entirely. Run separately: docker compose run with LOCAL_MODE overridden,
// then `npx playwright test e2e/invites.spec.ts`.
test("owner invites a member, who joins and is blocked from an owner-only page", async ({ browser }) => {
  const ownerEmail = `owner-${Date.now()}@example.com`;
  const memberEmail = `member-${Date.now()}@example.com`;

  const ownerContext = await browser.newContext();
  const ownerPage = await ownerContext.newPage();
  await ownerPage.goto("/register");
  await ownerPage.getByPlaceholder("Email").fill(ownerEmail);
  await ownerPage.getByPlaceholder("Password").fill("pw123456");
  await ownerPage.getByRole("button", { name: "Sign up" }).click();
  await expect(ownerPage).toHaveURL("/");

  await ownerPage.goto("/settings");
  await ownerPage.getByRole("button", { name: "Generate invite link" }).click();
  const link = await ownerPage.locator("code").first().innerText();

  const memberContext = await browser.newContext();
  const memberPage = await memberContext.newPage();
  await memberPage.goto(new URL(link).pathname);
  await memberPage.getByLabel("Email").fill(memberEmail);
  await memberPage.getByLabel("Password").fill("pw123456");
  await memberPage.getByRole("button", { name: "Join" }).click();
  await expect(memberPage).toHaveURL("/");

  // Member has no owner-only nav entry to connections; hitting the API directly
  // confirms the server-side gate, independent of what the UI renders.
  const response = await memberPage.request.get("http://localhost:8000/connections", {
    failOnStatusCode: false,
  });
  expect(response.status()).toBe(403);

  await ownerContext.close();
  await memberContext.close();
});
