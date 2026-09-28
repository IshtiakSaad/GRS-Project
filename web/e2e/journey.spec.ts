// One request from start to finish, through the three roles, on a phone-sized screen:
// a citizen registers and submits with a file; the administrator assigns it; the officer
// asks a question; the citizen answers; the officer resolves; the citizen sees the outcome
// and who looked at the request.

import { expect, test } from "@playwright/test";
import { english, login, loginAdmin, logout, PASSWORD, smsCode, TRADE_OFFICER, tinyPdf } from "./helpers";

test.describe.configure({ mode: "serial" });

const run = Date.now().toString().slice(-7);
const citizen = { phone: `0109${run}`, name: "E2E Citizen", password: `${PASSWORD}-e2e` };
const title = `Renew my trade licence ${run}`;
let requestUrl = "";

test("a citizen registers, confirms the number by SMS code, and logs in", async ({ page }) => {
  await english(page);
  await page.goto("/register/");
  await page.getByLabel("Full name").fill(citizen.name);
  await page.getByLabel("Mobile number").fill(citizen.phone);
  await page.getByLabel("Password").fill(citizen.password);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page).toHaveURL(/\/register\/verify\//);
  await page.getByLabel("Code").fill(await smsCode(page, citizen.phone));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Number confirmed")).toBeVisible();

  await page.getByLabel("Password").fill(citizen.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/requests\/$/);
  await expect(page.getByText("You have no requests yet.")).toBeVisible();
});

test("the citizen submits a request with a document and gets a tracking number", async ({ page }) => {
  await login(page, citizen.phone, citizen.password);
  await page.getByRole("link", { name: "New request" }).first().click();
  await page.getByLabel("Choose a service").selectOption("TRADE_LICENCE_RENEWAL");
  await page.getByLabel("Subject").fill(title);
  await page.getByLabel("Details").fill("The licence expires at the end of the month. Documents attached.");
  await page.locator('input[type="file"]').setInputFiles({ name: "licence.pdf", mimeType: "application/pdf", buffer: tinyPdf() });
  await page.getByRole("button", { name: "Submit request" }).click();

  await expect(page.getByText(/Submitted\. Your tracking number is \d{2}-\d{7}-\d\./)).toBeVisible();
  requestUrl = page.url();
  await expect(page.getByText("Submitted", { exact: true }).first()).toBeVisible();

  await page.getByRole("tab", { name: "Files" }).click();
  await expect(page.getByText("licence.pdf")).toBeVisible();
  await expect(page.getByText("Ready")).toBeVisible({ timeout: 60_000 });
});

test("the administrator assigns it to an officer of the department", async ({ page }) => {
  await loginAdmin(page);
  await expect(page.getByText("Resolved on time").first()).toBeVisible();
  await page.goto(requestUrl);
  await page.getByRole("button", { name: "Assign" }).click();
  await page.getByLabel("Officer").selectOption({ label: `${TRADE_OFFICER.name} · +88${TRADE_OFFICER.phone}` });
  await page.getByRole("button", { name: "Assign" }).last().click();
  await expect(page.getByText("Done.")).toBeVisible();
  await expect(page.getByText("Assigned", { exact: true }).first()).toBeVisible();
});

test("the officer starts work and asks the citizen for a document", async ({ page }) => {
  await login(page, TRADE_OFFICER.phone);
  await expect(page).toHaveURL(/\/officer\/$/);
  await page.goto(requestUrl);
  await page.getByRole("button", { name: "Start work" }).click();
  await expect(page.getByText("In progress").first()).toBeVisible();

  await page.getByRole("button", { name: "Ask the citizen" }).click();
  await page.getByLabel("Reason").selectOption("MISSING_DOCUMENT");
  await page.getByLabel("Message").fill("Please upload last year's licence as well.");
  await page.getByRole("button", { name: "Ask the citizen" }).last().click();
  await expect(page.getByText("Waiting for citizen").first()).toBeVisible();
  await logout(page);
});

test("the citizen answers, which puts the request back in progress", async ({ page }) => {
  await login(page, citizen.phone, citizen.password);
  await page.getByRole("tab", { name: "Waiting for you" }).click();
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await expect(page.getByText("The office is waiting for your answer.")).toBeVisible();
  await page.getByRole("button", { name: "Send your answer" }).click();
  await page.getByLabel("Message").fill("Uploaded it under Files. Thank you.");
  await page.getByRole("button", { name: "Send your answer" }).last().click();
  await expect(page.getByText("In progress").first()).toBeVisible();
});

test("the officer resolves it", async ({ page }) => {
  await login(page, TRADE_OFFICER.phone);
  await expect(page).toHaveURL(/\/officer\/$/);
  await page.goto(requestUrl);
  await page.getByRole("button", { name: "Resolve" }).click();
  await page.getByLabel("Note").fill("Licence renewed until next June.");
  await page.getByRole("button", { name: "Resolve" }).last().click();
  await expect(page.getByText("Resolved").first()).toBeVisible();
});

test("the citizen sees the outcome, the timeline, and which office looked", async ({ page }) => {
  await login(page, citizen.phone, citizen.password);
  await page.goto(requestUrl);
  await expect(page.getByText("Licence renewed until next June.").first()).toBeVisible();
  await expect(page.getByText("Information requested").first()).toBeVisible();
  await page.getByRole("tab", { name: "Who looked" }).click();
  await expect(page.getByText(/Opened|Changed/).first()).toBeVisible();
  // Officers are never named to the citizen.
  await expect(page.getByText(TRADE_OFFICER.name)).toHaveCount(0);
});

test("the interface is in Bangla until the citizen switches", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("grs.lang"));
  await page.goto("/login/");
  await expect(page.getByRole("heading", { name: "লগইন করুন" })).toBeVisible();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
});
