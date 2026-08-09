import { expect, test } from "@playwright/test";

// Runs against `docker compose up`, which sets LOCAL_MODE=true — no login involved.
// Names are unique per run so the assertions hold against a database that already
// has data in it, same convention as categorization.spec.ts / goals.spec.ts.
test("spending report, vault upload, and the estate checklist", async ({ page }) => {
  const stamp = Date.now();
  const title = `Will ${stamp}`;

  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();

  await page.goto("/reports/vault");
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Document type").selectOption("will");
  await page.getByLabel("Upload document").setInputFiles({
    name: "will.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("the whole will, for the e2e run"),
  });
  // `{ name: /upload/i }` alone is ambiguous: the file input itself carries
  // `aria-label="Upload document"`, which browsers expose with an implicit ARIA
  // `button` role, so a loose regex matches both it and the real submit button.
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText(title)).toBeVisible();

  // The checklist should now report the will as on file.
  await expect(page.getByText(/will on file/i)).toBeVisible();

  // Clean up — this runs against the real local database.
  await page.getByRole("button", { name: `Delete ${title}` }).click();
  await expect(page.getByText(title)).toHaveCount(0);
});
