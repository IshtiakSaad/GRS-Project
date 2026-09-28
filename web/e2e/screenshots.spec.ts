// Screenshots of every screen for a visual review: SCREENSHOTS=1 npx playwright test screenshots
// Not part of CI; the images land in web/screenshots/.

import { test, type Page } from "@playwright/test";
import { english, login, loginAdmin, TRADE_OFFICER } from "./helpers";

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1");
test.describe.configure({ mode: "serial" });

const LANG = process.env.SCREENSHOTS_LANG === "bn" ? "bn" : "en";

async function shot(page: Page, name: string, path?: string) {
  if (path) await page.goto(path);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(300);
  await page.screenshot({ path: `screenshots/${LANG}-${name}.png`, fullPage: true });
}

async function language(page: Page) {
  if (LANG === "en") return english(page);
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("grs.lang", "bn"));
}

async function firstRequest(page: Page) {
  const link = page.locator('a[href^="/requests/view/"]').first();
  await link.waitFor();
  return (await link.getAttribute("href"))!;
}

test("public", async ({ page }) => {
  await language(page);
  await shot(page, "01-home", "/");
  await shot(page, "02-login", "/login/");
  await shot(page, "03-register", "/register/");
  await shot(page, "04-forgot", "/forgot/");
  await page.goto("/demo-sms/");
  await page.getByRole("textbox").fill("01000000101");
  await page.getByRole("textbox").press("Enter");
  await shot(page, "05-demo-sms");
});

test("citizen", async ({ page }) => {
  await login(page, "01000000101");
  if (LANG === "bn") await page.evaluate(() => localStorage.setItem("grs.lang", "bn"));
  await shot(page, "10-my-requests", "/requests/");
  await shot(page, "11-new-request", "/requests/new/");
  await page.goto("/requests/");
  await shot(page, "12-request", await firstRequest(page));
  await shot(page, "13-track", "/track/");
  await shot(page, "14-profile", "/profile/");
});

test("officer", async ({ page }) => {
  await login(page, TRADE_OFFICER.phone);
  if (LANG === "bn") await page.evaluate(() => localStorage.setItem("grs.lang", "bn"));
  await shot(page, "20-queue", "/officer/");
  await page.goto("/officer/");
  await shot(page, "21-work-request", await firstRequest(page));
  await shot(page, "22-break-glass", "/officer/break-glass/");
});

test("administrator", async ({ page }) => {
  await loginAdmin(page);
  if (LANG === "bn") await page.evaluate(() => localStorage.setItem("grs.lang", "bn"));
  await shot(page, "30-dashboard", "/admin/");
  await shot(page, "31-all-requests", "/admin/requests/");
  await page.goto("/admin/requests/");
  await shot(page, "32-request-as-admin", await firstRequest(page));
  await shot(page, "33-reviews", "/admin/reviews/");
  await shot(page, "34-people", "/admin/people/");
  await shot(page, "35-directory", "/admin/directory/");
  await shot(page, "36-break-glass-report", "/admin/break-glass/");
});
