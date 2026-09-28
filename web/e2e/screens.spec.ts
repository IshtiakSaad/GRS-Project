// Every staff screen loads its data without an error, on a phone-sized screen.

import { expect, test, type Page } from "@playwright/test";
import { login, loginAdmin, TRADE_OFFICER } from "./helpers";

async function loads(page: Page, path: string, heading: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  await expect(page.getByText("Loading…")).toHaveCount(0);
  // In <main>: Next.js keeps its own role="alert" route announcer outside it.
  await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  // Nothing wider than the screen: no sideways scrolling on a phone.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("administrator screens", async ({ page }) => {
  await loginAdmin(page);
  await loads(page, "/admin/", "Dashboard");
  await loads(page, "/admin/requests/", "All requests");
  await loads(page, "/admin/reviews/", "Review queue");
  await loads(page, "/admin/people/", "People");
  await loads(page, "/admin/directory/", "Directory");
  await loads(page, "/admin/break-glass/", "Break-glass report");
  await loads(page, "/profile/", "Profile");
});

test("officer screens", async ({ page }) => {
  await login(page, TRADE_OFFICER.phone);
  await loads(page, "/officer/", "Queue");
  await loads(page, "/officer/break-glass/", "Break-glass access");
  await loads(page, "/track/", "Track a request");
  await loads(page, "/profile/", "Profile");
});

test("a citizen cannot open staff screens", async ({ page }) => {
  await login(page, "01000000101");
  await page.goto("/admin/");
  await expect(page.getByText("This page is not for your account.")).toBeVisible();
});
