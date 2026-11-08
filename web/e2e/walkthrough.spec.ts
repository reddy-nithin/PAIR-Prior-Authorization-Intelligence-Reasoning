import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** Press Tab (no mouse) until the focused element's text matches, then return. Fails after `max` presses. */
async function tabTo(page: Page, name: RegExp, max = 80): Promise<void> {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const text = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return el ? `${el.getAttribute("aria-label") ?? ""} ${el.innerText ?? ""}`.trim() : "";
    });
    if (name.test(text)) return;
  }
  throw new Error(`Tab never reached ${name}`);
}

async function noSeriousAxe(page: Page, screen: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`), `axe on ${screen}`).toEqual([]);
}

async function next(page: Page, step: string, isPhone: boolean): Promise<void> {
  await tabTo(page, /^Next:/);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/${step}$`));
  await expect(page.locator("h1:visible")).toHaveCount(1);
  // Focus moves to the new step, so the next Tab starts inside it.
  await expect(page.locator("main:visible")).toBeFocused();
  if (!isPhone) await expect(page.locator('.rail a[aria-current="step"]')).toBeVisible();
}

test("all 7 screens by keyboard only, with no serious axe problems", async ({ page, isMobile }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // Cached mode: the API is down, so the page says so and the demo cases still load.
  await expect(page.getByText("The live checker is not running right now.")).toBeVisible();
  await noSeriousAxe(page, "start");

  // The skip link is the first stop.
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText("Skip to main content");

  await tabTo(page, /Demo|pap|sleep|CPAP|apnea/i);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/why$/);
  await expect(page.getByRole("heading", { level: 1, name: "Why they said no" })).toBeVisible();
  await noSeriousAxe(page, "why");

  await next(page, "stand", isMobile);
  const firstRow = page.locator(".row").first();
  await firstRow.focus();
  await page.keyboard.press("Enter");
  await expect(firstRow).toHaveAttribute("data-state", "open");
  await noSeriousAxe(page, "stand");

  await next(page, "missing", isMobile);
  const box = page.locator(".todo input").first();
  if (await box.count()) {
    await box.focus();
    await page.keyboard.press("Space");
    await expect(box).toBeChecked();
  }
  await noSeriousAxe(page, "missing");

  await next(page, "letter", isMobile);
  await tabTo(page, /show source 1/);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("source-mark")).toBeVisible();
  await expect(page.locator('.sent[aria-pressed="true"]')).toHaveCount(1);
  await noSeriousAxe(page, "letter");

  await next(page, "chances", isMobile);
  await noSeriousAxe(page, "chances");

  await next(page, "download", isMobile);
  await expect(page.getByRole("link", { name: "Download as PDF" })).toHaveAttribute("href", /\/demo\/files\/.+\.pdf$/);
  await noSeriousAxe(page, "download");
});

test("cached letter files are served", async ({ request }) => {
  const index = await (await request.get("/demo/index.json")).json();
  const id = index.cases[0].case_id as string;
  for (const ext of ["docx", "pdf"]) {
    const response = await request.get(`/demo/files/${id}.${ext}`);
    expect(response.ok()).toBe(true);
    expect((await response.body()).length).toBeGreaterThan(1000);
  }
});

test("a live case id that isn't in memory says it is gone", async ({ page }) => {
  await page.goto("/case/live-deadbeef/why");
  await expect(page.locator("main [role=alert]")).toContainText("kept only while this tab is open");
});

test("every published case shows all 6 case screens with no serious axe problems", async ({ page, request }) => {
  const index = await (await request.get("/demo/index.json")).json();
  for (const row of index.cases as { case_id: string }[]) {
    for (const step of ["why", "stand", "missing", "letter", "chances", "download"]) {
      await page.goto(`/case/${row.case_id}/${step}`);
      await expect(page.locator("h1:visible")).toHaveCount(1);
      await expect(page.locator("main [role=alert]")).toHaveCount(0);
      await noSeriousAxe(page, `${row.case_id}/${step}`);
    }
  }
});
