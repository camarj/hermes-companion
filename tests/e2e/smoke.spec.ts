import { test, expect } from "@playwright/test";

test("playwright runner smoke", async ({ page }) => {
  await page.goto("data:text/html,<title>hermes-companion smoke</title><h1>ok</h1>");
  await expect(page).toHaveTitle("hermes-companion smoke");
  await expect(page.locator("h1")).toHaveText("ok");
});
