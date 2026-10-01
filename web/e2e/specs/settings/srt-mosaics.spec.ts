/**
 * Orbi360 SRT mosaics settings page tests -- MEDIUM tier.
 *
 * Covers listing the existing outputs and creating mosaics with a different
 * number of cameras (the grid adapts from 1 to 9 streams).
 */

import { test, expect } from "../../fixtures/frigate-test";
import type { Page } from "@playwright/test";

const STREAMS = [
  "cocina",
  "cocina_sub",
  "entrada",
  "entrada_sub",
  "quincho",
  "quincho_sub",
  "sala_gym",
  "sala_gym_sub",
];

const PRINCIPAL = {
  id: "principal",
  name: "Principal",
  enabled: true,
  streams: ["sala_gym_sub", "cocina_sub", "quincho_sub", "entrada_sub"],
  srt_port: 9999,
  latency_ms: 5000,
  bitrate_kbps: 2500,
  fps: 15,
  resolution: "1920x1080",
  encoder: "auto",
};

async function installMosaicRoutes(page: Page) {
  let saved: { mosaics: (typeof PRINCIPAL)[] } | null = null;
  let current = [PRINCIPAL];

  await page.route("**/api/orbi360/mosaics", async (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON();
      current = saved!.mosaics;
    }
    await route.fulfill({
      json: {
        mosaics: current,
        status: Object.fromEntries(current.map((m) => [m.id, "active"])),
        streams: STREAMS,
        supported: true,
      },
    });
  });

  return { saved: () => saved };
}

async function pickOption(page: Page, trigger: string, option: string) {
  await page.getByRole("combobox").filter({ hasText: trigger }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test.describe("Orbi360 SRT mosaics settings @medium", () => {
  test("lists existing mosaics with their SRT address", async ({
    frigateApp,
  }) => {
    await installMosaicRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=srtMosaics");

    await expect(frigateApp.page.getByText("Principal")).toBeVisible();
    await expect(
      frigateApp.page.getByText(/srt:\/\/.*:9999\?mode=caller&latency=5000/),
    ).toBeVisible();
    await expect(frigateApp.page.getByText("Running")).toBeVisible();
  });

  test("creates a single camera mosaic", async ({ frigateApp }) => {
    const routes = await installMosaicRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=srtMosaics");

    await frigateApp.page.getByRole("button", { name: "Add mosaic" }).click();
    await frigateApp.page.getByLabel("Name").fill("Entrada Casa");
    await pickOption(
      frigateApp.page,
      "4 cameras",
      "1 camera · Full screen",
    );
    await expect(frigateApp.page.getByText("Tile 1")).toBeVisible();
    await expect(frigateApp.page.getByText("Tile 2")).toHaveCount(0);

    await frigateApp.page.getByRole("button", { name: "Save" }).click();
    await expect.poll(() => routes.saved()).not.toBeNull();

    const added = routes.saved()!.mosaics.find((m) => m.id === "entrada-casa");
    expect(added).toBeDefined();
    expect(added!.streams).toHaveLength(1);
    // 9999 is taken by Principal, so the next free port is proposed
    expect(added!.srt_port).toBe(9000);
  });

  test("offers one stream picker per camera up to a 3x3 grid", async ({
    frigateApp,
  }) => {
    await installMosaicRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=srtMosaics");

    await frigateApp.page.getByRole("button", { name: "Add mosaic" }).click();
    await pickOption(frigateApp.page, "4 cameras", "7 cameras · 3x3 grid");
    for (let n = 1; n <= 7; n++) {
      await expect(frigateApp.page.getByText(`Tile ${n}`)).toBeVisible();
    }
    await expect(frigateApp.page.getByText("Tile 8")).toHaveCount(0);
  });
});
