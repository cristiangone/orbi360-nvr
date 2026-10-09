/**
 * Orbi360 camera network page tests -- MEDIUM tier.
 *
 * Cameras followed by MAC (status per camera) and new RTSP devices reported by
 * the locator, with the scan and ignore actions.
 */

import { test, expect } from "../../fixtures/frigate-test";
import type { Page } from "@playwright/test";

const NETWORK = {
  cameras: {
    entrada: {
      ip: "192.168.1.213",
      mac: "dc:29:19:e0:38:d0",
      vendor: "AltoBeam (Xiamen) Technology Ltd, Co.",
      status: "moved",
      last_seen: 1791500000,
    },
    cocina: {
      ip: "192.168.1.6",
      mac: "b4:fb:e3:37:3f:3d",
      status: "ok",
      last_seen: 1791500000,
    },
    salida_pieza: { ip: "192.168.1.12", status: "not_seen" },
  },
  discovered: {
    "aa:bb:cc:00:11:22": {
      ip: "192.168.1.40",
      vendor: "Hikvision",
      first_seen: 1791500000,
      last_seen: 1791500000,
    },
  },
  ignored: [] as string[],
  events: [
    {
      time: 1791500000,
      kind: "moved",
      text: "La cámara «entrada» cambió de IP: 192.168.1.10 → 192.168.1.213. Orbi360 la actualizó solo.",
    },
  ],
  last_scan: 1791500000,
  factory_ips: ["192.168.1.10"],
  supported: true,
};

async function installNetworkRoutes(page: Page) {
  const calls = { scan: 0, ignored: null as string | null };
  let state = structuredClone(NETWORK);
  await page.route("**/api/orbi360/network", (route) =>
    route.fulfill({ json: state }),
  );
  await page.route("**/api/orbi360/network/scan", (route) => {
    calls.scan += 1;
    return route.fulfill({ json: state });
  });
  await page.route("**/api/orbi360/network/ignore", (route) => {
    calls.ignored = route.request().postDataJSON().mac;
    state = { ...state, discovered: {}, ignored: [calls.ignored!] };
    return route.fulfill({ json: { success: true } });
  });
  return calls;
}

test.describe("Orbi360 camera network @medium", () => {
  test("shows each camera followed by MAC and its status", async ({
    frigateApp,
  }) => {
    await installNetworkRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=cameraNetwork");

    await expect(
      frigateApp.page.getByText("192.168.1.213", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("IP updated", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("On the network", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("Not seen", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText(/192\.168\.1\.10 → 192\.168\.1\.213/),
    ).toBeVisible();
  });

  test("scans on demand and ignores a new device", async ({ frigateApp }) => {
    const calls = await installNetworkRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=cameraNetwork");

    await frigateApp.page.getByRole("button", { name: "Scan now" }).click();
    await expect.poll(() => calls.scan).toBe(1);

    await expect(frigateApp.page.getByText("192.168.1.40")).toBeVisible();
    await frigateApp.page.getByRole("button", { name: "Ignore" }).click();
    await expect.poll(() => calls.ignored).toBe("aa:bb:cc:00:11:22");
    await expect(frigateApp.page.getByText("No new cameras.")).toBeVisible();
  });
});
