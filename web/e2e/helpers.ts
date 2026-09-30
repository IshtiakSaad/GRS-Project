import { expect, type Page } from "@playwright/test";

export const PASSWORD = process.env.E2E_DEMO_PASSWORD ?? "demo-password-2026";
export const ADMIN = "01000000001";
export const TRADE_OFFICER = { phone: "01000000014", name: "Mizanur Rahman" };
// The demo administrator's fixed second-step code (demo mode only).
export const ADMIN_CODE = "123456";

// --- flows -----------------------------------------------------------------------------------

/** Switch the UI to English so the assertions read plainly. */
export async function english(page: Page) {
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("grs.lang", "en"));
}

export async function login(page: Page, phone: string, password = PASSWORD) {
  await english(page);
  await page.goto("/login/");
  await page.getByLabel("Mobile number").fill(phone);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  // Wait until the app has moved on (home page, or the two-step form).
  await page.waitForURL((url) => url.pathname !== "/login/");
}

export async function loginAdmin(page: Page) {
  await login(page, ADMIN);
  await expect(page).toHaveURL(/\/login\/two-step\//);
  await page.getByLabel("Code").fill(ADMIN_CODE);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/admin\/$/);
}

export async function logout(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login\//);
}

/** The newest code the demo SMS provider "sent" to a number; `after`: wait for one newer than it
 * (texts go out through the worker, so a fresh code can take a moment to arrive). */
export async function smsCode(page: Page, phone: string, after?: string): Promise<string> {
  let code = "";
  await expect(async () => {
    const res = await page.request.get(`/api/v1/demo/sms/${phone}`);
    const rows = (await res.json()) as { body: string }[];
    // Whole six-digit runs only: a staff SMS carries a link with the 11-digit number in it.
    const match = rows[0]?.body.match(/\b\d{6}\b/) ?? rows[0]?.body.match(/[০-৯]{6}/);
    expect(match).toBeTruthy();
    expect(match![0]).not.toEqual(after);
    code = match![0];
  }).toPass({ timeout: 20_000 });
  return code;
}

/** A one-page PDF, small enough to upload quickly and real enough to pass the checker. */
export function tinyPdf(): Buffer {
  const body = [
    "%PDF-1.4",
    "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
    "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj",
    "trailer<</Root 1 0 R>>",
    "%%EOF",
  ].join("\n");
  return Buffer.from(body);
}
