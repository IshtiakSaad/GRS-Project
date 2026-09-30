// The flows the journey does not walk: drafts, duplicates, withdraw and reopen, reassign and
// priority, the review queue, break-glass, account recovery and profile, and the admin's
// people and directory screens. Needs REVIEW_SAMPLE_RATE=1 on the stack so that every
// resolution goes to the review queue.

import { expect, test, type Page } from "@playwright/test";
import { english, login, loginAdmin, PASSWORD, smsCode, TRADE_OFFICER } from "./helpers";

test.describe.configure({ mode: "serial" });

const run = Date.now().toString().slice(-6);
// A citizen of its own, so reruns do not hit the per-citizen submit limit (10 an hour).
const CITIZEN = `0106${run}0`;
const CITIZEN_PASSWORD = `${PASSWORD}-flows`;
const REGISTRY = [
  { phone: "01000000011", name: "Nasrin Akter" },
  { phone: "01000000012", name: "Tanvir Hasan" },
];
const requests: Record<"a" | "b", { url: string; no: string }> = { a: { url: "", no: "" }, b: { url: "", no: "" } };

async function fillRequest(page: Page, title: string) {
  await page.goto("/requests/new/");
  await page.getByLabel("Choose a service").selectOption("BIRTH_CERT_CORRECTION");
  await page.getByLabel("Subject").fill(title);
  await page.getByLabel("Details").fill(`Father's name is misspelt on the certificate (${run}).`);
}

async function act(page: Page, button: string, fields: Record<string, string> = {}) {
  await page.getByRole("button", { name: button, exact: true }).click();
  for (const [label, value] of Object.entries(fields)) {
    const field = page.getByLabel(label, { exact: true });
    if ((await field.evaluate((el) => el.tagName)) === "SELECT") await field.selectOption(value);
    else await field.fill(value);
  }
  if (Object.keys(fields).length) await page.getByRole("button", { name: button, exact: true }).last().click();
}

async function status(page: Page, text: string) {
  await expect(page.locator("main span.rounded-full").first()).toHaveText(text);
}

test("a citizen signs up for these flows", async ({ page }) => {
  await english(page);
  await page.goto("/register/");
  await page.getByLabel("Full name").fill("E2E Flows");
  await page.getByLabel("Mobile number").fill(CITIZEN);
  await page.getByLabel("Password").fill(CITIZEN_PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Code").fill(await smsCode(page, CITIZEN));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Number confirmed")).toBeVisible();
});

test("a draft is saved, edited and discarded", async ({ page }) => {
  await login(page, CITIZEN, CITIZEN_PASSWORD);
  await fillRequest(page, `Draft ${run}`);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("heading", { name: `Draft ${run}` })).toBeVisible();
  await status(page, "Draft");

  await page.getByRole("link", { name: "Edit draft" }).click();
  await expect(page.getByLabel("Subject")).toHaveValue(`Draft ${run}`);
  await page.getByLabel("Subject").fill(`Edited draft ${run}`);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("heading", { name: `Edited draft ${run}` })).toBeVisible();

  await page.getByRole("button", { name: "Discard draft" }).click();
  await page.getByRole("button", { name: "Discard draft" }).last().click();
  await expect(page).toHaveURL(/\/requests\/$/);
  await expect(page.getByText(`Edited draft ${run}`)).toHaveCount(0);
});

test("a second identical request is flagged, and can be sent anyway", async ({ page }) => {
  await login(page, CITIZEN, CITIZEN_PASSWORD);
  for (const key of ["a", "b"] as const) {
    await fillRequest(page, `Name correction ${run}`);
    await page.getByRole("button", { name: "Submit request" }).click();
    if (key === "b") {
      await expect(page.getByText("You sent something very similar a few minutes ago.")).toBeVisible();
      await page.getByRole("button", { name: "Submit anyway" }).click();
    }
    const notice = page.getByText(/Your tracking number is/);
    await expect(notice).toBeVisible();
    requests[key] = { url: page.url(), no: (await notice.textContent())!.match(/\d{2}-\d{7}-\d/)![0] };
  }
  expect(requests.a.no).not.toEqual(requests.b.no);
});

test("the administrator assigns, reassigns with a reason, and raises the priority", async ({ page }) => {
  await loginAdmin(page);
  await page.goto(requests.a.url);
  await act(page, "Assign", { Officer: `${REGISTRY[0].name} · +88${REGISTRY[0].phone}` });
  await expect(page.getByText("Done.")).toBeVisible();
  await act(page, "Reassign", { Officer: `${REGISTRY[1].name} · +88${REGISTRY[1].phone}`, Reason: "Nasrin is on leave this week." });
  await expect(page.getByText(REGISTRY[1].name).first()).toBeVisible();
  await page.getByLabel("Set priority").selectOption("HIGH");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("High", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Timeline" }).click();
  await expect(page.getByText("Reassigned")).toBeVisible();
  await expect(page.getByText("Priority changed")).toBeVisible();

  await page.goto(requests.b.url);
  await act(page, "Assign", { Officer: `${REGISTRY[0].name} · +88${REGISTRY[0].phone}` });
  await expect(page.getByText("Done.")).toBeVisible();
});

test("the officers start and resolve their requests", async ({ page }) => {
  for (const [officer, key] of [
    [REGISTRY[1], "a"],
    [REGISTRY[0], "b"],
  ] as const) {
    await login(page, officer.phone);
    await page.goto(requests[key].url);
    await act(page, "Start work");
    await status(page, "In progress");
    await act(page, "Resolve", { Note: "Corrected certificate issued." });
    await status(page, "Resolved");
    await page.getByRole("button", { name: "Log out" }).click();
  }
});

test("the citizen asks to reopen one", async ({ page }) => {
  await login(page, CITIZEN, CITIZEN_PASSWORD);
  await page.goto(requests.a.url);
  await expect(page.getByText(/You can ask to reopen until/)).toBeVisible();
  await act(page, "Ask to reopen", { Reason: "The mother's name is still misspelt." });
  await status(page, "Submitted");
});

test("the administrator upholds one review and overturns the other", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/admin/reviews/");
  const card = (no: string) => page.locator("section").filter({ hasText: no });
  await expect(card(requests.a.no)).toBeVisible();
  await card(requests.a.no).getByRole("button", { name: "Uphold" }).click();
  await expect(card(requests.a.no)).toHaveCount(0);
  await card(requests.b.no).getByLabel(/Note/).fill("The certificate had not been reissued.");
  await card(requests.b.no).getByRole("button", { name: "Overturn" }).click();
  await expect(card(requests.b.no)).toHaveCount(0);

  await page.getByRole("tab", { name: "Overturned" }).click();
  await expect(card(requests.b.no)).toBeVisible();
  await page.goto(requests.b.url);
  await status(page, "Submitted");
});

test("the citizen withdraws the overturned request", async ({ page }) => {
  await login(page, CITIZEN, CITIZEN_PASSWORD);
  await page.goto(requests.b.url);
  await act(page, "Withdraw request", { "Reason (optional)": "Sorted out at the union office." });
  await status(page, "Withdrawn");
});

test("an officer of another department opens a request with break-glass; it is reported and shown to the citizen", async ({ page }) => {
  await login(page, TRADE_OFFICER.phone);
  await page.goto("/officer/break-glass/");
  await page.getByLabel("Tracking number").fill(requests.a.no);
  await page.getByLabel("Reason", { exact: true }).selectOption("CITIZEN_COMPLAINT");
  await page.getByLabel(/^Note/).fill("The citizen phoned the trade office about this request.");
  await page.getByRole("button", { name: "Open read-only" }).click();
  await expect(page.getByRole("heading", { name: `Name correction ${run}` })).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await login(page, CITIZEN, CITIZEN_PASSWORD);
  await page.goto(requests.a.url);
  await page.getByRole("tab", { name: "Who looked" }).click();
  await expect(page.getByText("Opened outside their office, with a stated reason").first()).toBeVisible();
});

test("a new citizen resets a forgotten password, then edits the profile", async ({ page }) => {
  const phone = `0108${run}0`;
  await english(page);
  await page.goto("/register/");
  await page.getByLabel("Full name").fill("E2E Recovery");
  await page.getByLabel("Mobile number").fill(phone);
  await page.getByLabel("Password").fill(`${PASSWORD}-first`);
  await page.getByRole("button", { name: "Continue" }).click();
  const first = await smsCode(page, phone);
  await page.getByLabel("Code").fill(first);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Number confirmed")).toBeVisible();

  await page.goto("/forgot/");
  await page.getByLabel("Mobile number").fill(phone);
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByText("it is on its way")).toBeVisible();
  const code = await smsCode(page, phone, first);
  await page.getByLabel("Code").fill(code);
  await page.getByLabel("New password").fill(`${PASSWORD}-second`);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Password changed. Log in with the new one.")).toBeVisible();

  await login(page, phone, `${PASSWORD}-second`);
  await expect(page).toHaveURL(/\/requests\/$/);
  await page.getByRole("link", { name: "Profile" }).click();
  await page.getByLabel("Full name").fill("E2E Recovered");
  await page.getByLabel("Email").fill(`e2e-${run}@example.test`);
  await page.getByRole("button", { name: "Save" }).first().click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await expect(page.getByText("Not confirmed yet: open the link we emailed you.")).toBeVisible();
  await expect(page.getByText("This device")).toBeVisible();

  await page.getByLabel("Current password").fill(`${PASSWORD}-second`);
  await page.getByLabel("New password").fill(`${PASSWORD}-third`);
  await page.getByRole("button", { name: "Save" }).nth(1).click();
  await expect(page.getByText("Password changed. Your other devices were logged out.")).toBeVisible();

  // The verification link from the email (Mailpit catches it) confirms the address.
  const mailpit = process.env.E2E_MAILPIT ?? "http://localhost:8025";
  let link = "";
  await expect(async () => {
    const found = await (await page.request.get(`${mailpit}/api/v1/search?query=to:e2e-${run}@example.test`)).json();
    const id = found.messages?.[0]?.ID;
    expect(id).toBeTruthy();
    const text = (await (await page.request.get(`${mailpit}/api/v1/message/${id}`)).json()).Text as string;
    link = text.match(/\/verify-email#token=\S+/)![0];
  }).toPass({ timeout: 30_000 });
  await page.goto(link);
  await expect(page.getByText("Email confirmed.")).toBeVisible();
  await page.getByRole("link", { name: "Back to your profile" }).click();
  await expect(page.getByText("✓ Email confirmed.")).toBeVisible();
});

test("the administrator adds an officer, sends a reset code, deactivates and reactivates", async ({ page }) => {
  const name = `E2E Officer ${run}`;
  await loginAdmin(page);
  await page.goto("/admin/people/");
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Mobile number").first().fill(`0107${run}0`);
  await page.getByLabel("Department").selectOption("TRADE");
  await page.getByRole("button", { name: "Add" }).click();
  const row = page.locator("li").filter({ hasText: name });
  await expect(row).toContainText("Password not set yet");
  await row.getByRole("button", { name: "Reset password" }).click();
  await expect(row.getByText("Reset code sent by SMS.")).toBeVisible();
  await row.getByRole("button", { name: "Deactivate" }).click();
  await expect(row.getByRole("button", { name: "Activate" })).toBeVisible();
  await row.getByRole("button", { name: "Activate" }).click();
  await expect(row.getByRole("button", { name: "Deactivate" })).toBeVisible();
});

test("the administrator edits the directory: department, service, holiday, suspension", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/admin/directory/");
  const code = `E2E${run}`;
  await page.getByLabel("Code").fill(code);
  await page.getByLabel("Name (Bangla)").fill(`পরীক্ষা ${run}`);
  await page.getByLabel("Name (English)").fill(`Test office ${run}`);
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText(`Test office ${run}`)).toBeVisible();

  await page.getByRole("tab", { name: "Services" }).click();
  await page.getByLabel("Department").selectOption(code);
  await page.getByLabel("Code").fill(`${code}_SVC`);
  await page.getByLabel("Name (Bangla)").fill(`পরীক্ষা সেবা ${run}`);
  await page.getByLabel("Name (English)").fill(`Test service ${run}`);
  await page.getByLabel("Target (working days)").last().fill("12");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText(`Test service ${run}`)).toBeVisible();

  await page.getByRole("tab", { name: "Holidays" }).click();
  const year = new Date().getFullYear();
  const day = `${year}-11-${String((Number(run) % 27) + 1).padStart(2, "0")}`;
  await page.getByLabel("Date").fill(day);
  await page.getByLabel("Name (Bangla)").fill(`ছুটি ${run}`);
  await page.getByLabel("Name (English)").fill(`Test holiday ${run}`);
  await page.getByRole("button", { name: "Add" }).click();
  const holiday = page.locator("li").filter({ hasText: `Test holiday ${run}` });
  await expect(holiday).toBeVisible();
  await holiday.getByRole("button", { name: "Remove" }).click();
  await expect(holiday).toHaveCount(0);

  await page.getByRole("tab", { name: "SLA suspensions" }).click();
  await page.getByLabel("Starts").fill(`${year + 1}-01-05`);
  await page.getByLabel("Ends").fill(`${year + 1}-01-06`);
  await page.getByLabel("Reason").fill(`Flooding drill ${run}`);
  await page.getByRole("button", { name: "Add" }).click();
  const suspension = page.locator("li").filter({ hasText: `Flooding drill ${run}` });
  await expect(suspension).toBeVisible();
  await suspension.getByRole("button", { name: "Remove" }).click();
  await expect(suspension).toHaveCount(0);
});

test("the break-glass report lists the opening, with who and why", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/admin/break-glass/");
  const entry = page.locator("li").filter({ hasText: requests.a.no });
  await expect(entry).toContainText(TRADE_OFFICER.name);
  await expect(entry).toContainText("Citizen complaint");
});
