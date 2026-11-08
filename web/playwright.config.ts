import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;

/** Runs against a production build serving the published demo cache. The API is pointed at a dead port, so these
 * tests also prove cached mode needs no backend. Run `make demo-fixture` (or the real `make demo-publish`) first. */
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
    { name: "dark", use: { ...devices["Desktop Chrome"], colorScheme: "dark" } },
  ],
  webServer: {
    command: `npm run build && npx next start -H 127.0.0.1 -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    env: { NEXT_PUBLIC_PAIR_API: "http://127.0.0.1:9" },
    reuseExistingServer: false,
    timeout: 240_000,
  },
});
