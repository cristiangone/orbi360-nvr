/**
 * Orbi360 assistant -- MEDIUM tier.
 *
 * Floating help button with searchable frequently asked questions (answers in
 * Spanish) and links to the matching settings page.
 */

import { test, expect } from "../fixtures/frigate-test";

test.describe("Orbi360 assistant @medium", () => {
  test("finds an answer and opens its settings page", async ({
    frigateApp,
  }, testInfo) => {
    await frigateApp.goto("/");
    const page = frigateApp.page;

    await page.getByRole("button", { name: "Open the assistant" }).click();
    const panel = page.getByRole("dialog");
    await expect(panel.getByText("Orbi360 assistant")).toBeVisible();

    await panel.getByPlaceholder(/Type your question/).fill("cocina_sub");
    await panel.getByRole("button", { name: /Qué significa «_sub»/ }).click();
    await expect(panel.getByText(/el secundario/)).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath(`assistant-${testInfo.project.name}.png`),
    });

    await panel.getByRole("button", { name: "Ver flujos go2rtc" }).click();
    await expect(page).toHaveURL(/page=systemGo2rtcStreams/);
    await expect(panel).toBeHidden();
  });

  test("filters by category and handles no results", async ({ frigateApp }) => {
    await frigateApp.goto("/");
    const page = frigateApp.page;
    await page.getByRole("button", { name: "Open the assistant" }).click();
    const panel = page.getByRole("dialog");

    await panel
      .getByRole("button", { name: "Inteligencia artificial", exact: true })
      .click();
    await expect(
      panel.getByRole("button", { name: /reconocimiento de patentes/ }),
    ).toBeVisible();
    await expect(
      panel.getByRole("button", { name: /Cómo agrego una cámara nueva/ }),
    ).toBeHidden();

    await panel.getByPlaceholder(/Type your question/).fill("zzzqqq");
    await expect(panel.getByText(/No answer found/)).toBeVisible();
  });
});

test.describe("Orbi360 assistant — mobile @medium @mobile", () => {
  test.skip(({ frigateApp }) => !frigateApp.isMobile, "Mobile-only");

  test("button and panel fit the phone screen", async ({ frigateApp }) => {
    await frigateApp.goto("/");
    const page = frigateApp.page;
    const button = page.getByRole("button", { name: "Open the assistant" });
    await expect(button).toBeInViewport();
    await button.click();
    await expect(
      page.getByRole("dialog").getByPlaceholder(/Type your question/),
    ).toBeInViewport();
  });
});
