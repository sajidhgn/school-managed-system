import { expect, test } from "@playwright/test";

test.describe("public security boundary", () => {
  test("signed-out password reset reaches the fixed public handler", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.getByLabel(/email/i).fill("unknown@example.com");
    await page.getByRole("button", { name: /send reset link/i }).click();
    await expect(page.getByText(/if an account exists/i)).toBeVisible();
  });

  test("generic BFF refuses anonymous auth and admissions paths", async ({ request }) => {
    for (const path of ["auth/forgot-password", "auth/reset-password", "students/admissions"]) {
      const response = await request.post(`/api/bff/${path}`, { data: {} });
      expect(response.status()).toBe(403);
      expect((await response.json()).code).toBe("PROXY_BLOCKED");
    }
  });

  test("English and Urdu switch document direction", async ({ context, page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
    await context.addCookies([
      { name: "educloud_locale", value: "ur", domain: "127.0.0.1", path: "/" },
    ]);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("lang", "ur");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  });
});

test("platform login requires a valid operator credential and MFA code", async ({ page }) => {
  await page.goto("/platform/login");
  await page.getByLabel(/email/i).fill("nobody@example.com");
  await page.getByLabel(/password/i).fill("not-a-real-platform-password");
  const code = page.getByLabel(/authentication code/i);
  if (await code.isVisible()) await code.fill("000000");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByText(/incorrect|invalid/i)).toBeVisible();
});
