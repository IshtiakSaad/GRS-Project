import { createHmac } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, type Page } from "@playwright/test";

export const PASSWORD = process.env.E2E_DEMO_PASSWORD ?? "demo-password-2026";
export const ADMIN = "01000000001";
export const TRADE_OFFICER = { phone: "01000000014", name: "Mizanur Rahman" };

// --- two-step codes (RFC 6238, as src/apps/accounts/totp.py) ---------------------------------

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

function codeAt(secret: string, counter: number): string {
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(counter));
  const mac = createHmac("sha1", base32(secret)).update(msg).digest();
  const offset = mac[mac.length - 1] & 0x0f;
  const value = mac.readUInt32BE(offset) & 0x7fffffff;
  return String(value % 1_000_000).padStart(6, "0");
}

// The last step used, kept on disk: Playwright starts a fresh worker process after a failure,
// and a counter held in memory would then hand out a code the API has already accepted.
const LAST_STEP_FILE = join(tmpdir(), "grs-e2e-totp-step");

function lastStep(): number {
  try {
    return Number(readFileSync(LAST_STEP_FILE, "utf8")) || 0;
  } catch {
    return 0;
  }
}

/** A code the API has not seen: a used code is refused (replay protection), so wait for the next step. */
export async function freshTotp(secret: string): Promise<string> {
  let counter = Math.floor(Date.now() / 30_000);
  while (counter <= lastStep()) {
    await new Promise((r) => setTimeout(r, 1000));
    counter = Math.floor(Date.now() / 30_000);
  }
  writeFileSync(LAST_STEP_FILE, String(counter));
  return codeAt(secret, counter);
}

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
  const secret = process.env.E2E_ADMIN_TOTP_SECRET;
  if (!secret) throw new Error("set E2E_ADMIN_TOTP_SECRET (printed by seed_demo)");
  await login(page, ADMIN);
  await expect(page).toHaveURL(/\/login\/two-step\//);
  await page.getByLabel("Code").fill(await freshTotp(secret));
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
    const match = rows[0]?.body.match(/\d{6}/) ?? rows[0]?.body.match(/[০-৯]{6}/);
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
