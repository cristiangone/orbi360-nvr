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

const PRINCIPAL: Record<string, unknown> & { id: string; streams: string[] } = {
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

async function installMosaicRoutes(
  page: Page,
  initial: (typeof PRINCIPAL)[] = [PRINCIPAL],
  runtime: Record<string, unknown> = {},
) {
  let saved: { mosaics: (typeof PRINCIPAL)[] } | null = null;
  let current = initial;

  await page.route("**/api/orbi360/mosaics", async (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON();
      current = saved!.mosaics;
    }
    await route.fulfill({
      json: {
        mosaics: current,
        status: Object.fromEntries(current.map((m) => [m.id, "active"])),
        runtime,
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
    await pickOption(frigateApp.page, "4 cameras", "1 camera · Full screen");
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

  test("protects a mosaic with a generated SRT passphrase", async ({
    frigateApp,
  }) => {
    const routes = await installMosaicRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=srtMosaics");

    await frigateApp.page.getByRole("button", { name: "Edit" }).click();
    await frigateApp.page.getByRole("button", { name: "Generate" }).click();
    await frigateApp.page.getByRole("button", { name: "Save" }).click();
    await expect.poll(() => routes.saved()).not.toBeNull();

    const passphrase = routes.saved()!.mosaics[0].passphrase as string;
    expect(passphrase).toMatch(/^[A-Za-z0-9]{20}$/);

    // the card flags the output as encrypted and never shows the passphrase
    await expect(frigateApp.page.getByText("Encrypted")).toBeVisible();
    await expect(
      frigateApp.page.getByText(/passphrase=•+&pbkeylen=16/),
    ).toBeVisible();
    await expect(frigateApp.page.getByText(passphrase)).toHaveCount(0);
  });

  test("creates a mosaic that pushes to an SRT server", async ({
    frigateApp,
  }) => {
    const routes = await installMosaicRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=srtMosaics");

    await frigateApp.page.getByRole("button", { name: "Add mosaic" }).click();
    await frigateApp.page.getByLabel("Name").fill("Nimble");
    await pickOption(
      frigateApp.page,
      "Wait for connections (listener)",
      "Send to a server (caller)",
    );
    // the local port is not asked in caller mode
    await expect(frigateApp.page.getByLabel("SRT port (UDP)")).toHaveCount(0);
    await frigateApp.page
      .getByLabel("Server (IP or domain)")
      .fill("stream.example.com");
    await frigateApp.page.getByLabel("Server port").fill("8890");
    await frigateApp.page
      .getByLabel("Stream ID (optional)")
      .fill("#!::r=live/mosaic,m=publish");
    await frigateApp.page.getByRole("button", { name: "Save" }).click();
    await expect.poll(() => routes.saved()).not.toBeNull();

    const added = routes.saved()!.mosaics.find((m) => m.id === "nimble")!;
    expect(added.mode).toBe("caller");
    expect(added.target_host).toBe("stream.example.com");
    expect(added.target_port).toBe(8890);
    expect(added.stream_id).toBe("#!::r=live/mosaic,m=publish");

    await expect(frigateApp.page.getByText("Sends to server")).toBeVisible();
    await expect(
      frigateApp.page.getByText(
        "srt://stream.example.com:8890?latency=5000&streamid=#!::r=live/mosaic,m=publish",
      ),
    ).toBeVisible();
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

test.describe("Orbi360 SRT mosaics live state and alerts @medium", () => {
  test("shows the real connection and video state of each mosaic", async ({
    frigateApp,
  }) => {
    const nimble = {
      ...PRINCIPAL,
      id: "nimble",
      name: "Nimble",
      srt_port: 9001,
      mode: "caller",
      target_host: "stream.example.com",
      target_port: 8890,
    };
    const camaras = {
      ...PRINCIPAL,
      id: "camaras",
      name: "Camaras",
      srt_port: 9002,
    };
    await installMosaicRoutes(frigateApp.page, [PRINCIPAL, nimble, camaras], {
      principal: {
        srt: "waiting",
        srt_since: 1700000000,
        encoder: "ok",
        encoder_since: 1700000000,
        restarts: 0,
        missing: ["entrada_sub"],
      },
      nimble: {
        srt: "connecting",
        srt_since: 1700000000,
        encoder: "ok",
        encoder_since: 1700000000,
        restarts: 2,
      },
      camaras: {
        srt: "connected",
        srt_since: 1700000000,
        encoder: "stalled",
        encoder_since: 1700000000,
        restarts: 1,
      },
    });
    await frigateApp.goto("/settings?page=srtMosaics");

    await expect(
      frigateApp.page.getByText("Waiting for client", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("Retrying", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("No video", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText(
        "The video restarted 2 times since the service started",
      ),
    ).toBeVisible();
    // a camera that went down is flagged on the grid preview
    await expect(
      frigateApp.page.getByText("entrada_sub · No signal"),
    ).toBeVisible();
    // the systemd state is only a fallback when the service reports nothing
    await expect(frigateApp.page.getByText("Running")).toHaveCount(0);
  });

  test("saves Telegram alerts without ever reading the token back", async ({
    frigateApp,
  }) => {
    await installMosaicRoutes(frigateApp.page);
    let settings = {
      enabled: false,
      chat_id: null as string | null,
      alert_after_s: 60,
      token_set: false,
    };
    let putBody: Record<string, unknown> | null = null;
    let testBody: Record<string, unknown> | null = null;
    await frigateApp.page.route("**/api/orbi360/telegram", async (route) => {
      if (route.request().method() === "PUT") {
        putBody = route.request().postDataJSON();
        settings = {
          enabled: putBody!.enabled as boolean,
          chat_id: putBody!.chat_id as string,
          alert_after_s: putBody!.alert_after_s as number,
          token_set: true,
        };
      }
      await route.fulfill({ json: settings });
    });
    await frigateApp.page.route(
      "**/api/orbi360/telegram/test",
      async (route) => {
        testBody = route.request().postDataJSON();
        await route.fulfill({ json: { success: true } });
      },
    );
    await frigateApp.goto("/settings?page=srtMosaics");

    const token = "123456789:AAH-abcdefghijklmnopqrstuvwxyz012345";
    await frigateApp.page.getByLabel("Bot token").fill(token);
    await frigateApp.page.getByLabel("Chat ID").fill("-1001234567890");
    await frigateApp.page.getByLabel("Send alerts").click();
    await frigateApp.page.getByRole("button", { name: "Send test" }).click();
    await expect.poll(() => testBody).not.toBeNull();
    expect(testBody!.bot_token).toBe(token);

    await frigateApp.page
      .getByRole("button", { name: "Save", exact: true })
      .click();
    await expect.poll(() => putBody).not.toBeNull();
    expect(putBody!.enabled).toBe(true);
    expect(putBody!.chat_id).toBe("-1001234567890");

    // after saving the field is cleared and only says a token is stored
    await expect(frigateApp.page.getByLabel("Bot token")).toHaveValue("");
    await expect(
      frigateApp.page.getByText("A token is saved. Leave it empty to keep it."),
    ).toBeVisible();
  });
});

test.describe("Orbi360 SRT mosaics — mobile @medium @mobile", () => {
  test.skip(({ frigateApp }) => !frigateApp.isMobile, "Mobile-only");

  test("mosaic card and SRT address fit the mobile viewport", async ({
    frigateApp,
  }) => {
    await installMosaicRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=srtMosaics");
    await expect(frigateApp.page.getByText("Principal")).toBeVisible();
    await expect(
      frigateApp.page.getByRole("button", { name: "Copy SRT address" }),
    ).toBeInViewport();
  });
});
