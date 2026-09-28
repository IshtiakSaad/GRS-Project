import { defineConfig, devices } from "@playwright/test";

// Runs against a full stack (Nginx on :8080 by default) loaded with `seed_demo`.
// E2E_ADMIN_TOTP_SECRET is the administrator's two-step secret that seed_demo prints.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // A mid-range Android phone: the app's main audience.
  projects: [{ name: "phone", use: { ...devices["Pixel 7"] } }],
});
