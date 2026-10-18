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
  const calls = {
    scan: 0,
    ignored: null as string | null,
    forgotten: null as string | null,
    added: null as Record<string, unknown> | null,
    password: null as string | null,
  };
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
  await page.route("**/api/orbi360/network/forget", (route) => {
    calls.forgotten = route.request().postDataJSON().camera;
    return route.fulfill({
      json: { success: true, forgotten: [calls.forgotten] },
    });
  });
  await page.route("**/api/orbi360/network/probe", (route) =>
    route.fulfill({
      json: {
        success: true,
        protocol: "dvrip",
        ip: route.request().postDataJSON().ip,
        codec: "H.265",
      },
    }),
  );
  await page.route("**/api/orbi360/network/add", (route) => {
    calls.added = route.request().postDataJSON();
    return route.fulfill({
      json: { success: true, name: "north_yard", backup: "config.yml.bak" },
    });
  });
  await page.route("**/api/orbi360/camera-password", (route) => {
    if (route.request().method() === "PUT") {
      calls.password = route.request().postDataJSON().password;
      return route.fulfill({ json: { success: true } });
    }
    return route.fulfill({ json: { set: calls.password !== null } });
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

  test("forgets a wrongly learned MAC", async ({ frigateApp }) => {
    const calls = await installNetworkRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=cameraNetwork");
    await frigateApp.page
      .getByRole("button", { name: "Forget MAC" })
      .first()
      .click();
    await expect.poll(() => calls.forgotten).toBe("cocina");
  });

  test("adds a discovered camera over DVRIP", async ({ frigateApp }) => {
    const calls = await installNetworkRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=cameraNetwork");
    const page = frigateApp.page;

    await page.getByRole("button", { name: "Add", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Camera name").fill("North Yard");
    await expect(dialog.getByText("Internal name: north_yard")).toBeVisible();
    await dialog.getByRole("button", { name: "Detect" }).click();
    await expect(dialog.getByText(/iCSee camera over DVRIP/)).toBeVisible();
    await expect(dialog.getByLabel(/switch it to H.264/)).toBeChecked();
    await dialog.getByRole("button", { name: "Add", exact: true }).click();

    await expect
      .poll(() => calls.added)
      .toMatchObject({
        name: "north_yard",
        friendly_name: "North Yard",
        protocol: "dvrip",
        ip: "192.168.1.40",
        mac: "aa:bb:cc:00:11:22",
        to_h264: true,
      });

    // the NVR restarts to load the camera: wait for it, then refresh the page data
    await page.route("**/api/version", (route) =>
      route.fulfill({ body: "0.18.0-test" }),
    );
    const banner = page.getByText(
      /Restarting the NVR with camera “North Yard”/,
    );
    await expect(banner).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Add camera by IP" }),
    ).toBeDisabled();
    await expect(banner).toBeHidden({ timeout: 30000 });
    await expect(
      page.getByRole("button", { name: "Add camera by IP" }),
    ).toBeEnabled();
  });

  test("marks cameras behind a Wi-Fi repeater", async ({ frigateApp }) => {
    const rep = "10:27:f5:09:a5:67";
    await frigateApp.page.route("**/api/orbi360/network", (route) =>
      route.fulfill({
        json: {
          ...NETWORK,
          cameras: { patio_pieza: { ip: "192.168.1.111", status: "bridged" } },
          discovered: {
            [`${rep}@192.168.1.102`]: {
              ip: "192.168.1.102",
              bridged: true,
              first_seen: 1791500000,
              last_seen: 1791500000,
            },
          },
        },
      }),
    );
    await frigateApp.goto("/settings?page=cameraNetwork");
    await expect(
      frigateApp.page.getByText("Behind repeater", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText(
        /Behind a Wi-Fi repeater: it cannot be followed/,
      ),
    ).toBeVisible();
    await expect(frigateApp.page.getByText(rep, { exact: true })).toBeVisible();
  });

  test("sets the camera password without showing it back", async ({
    frigateApp,
  }) => {
    const calls = await installNetworkRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=cameraNetwork");
    const page = frigateApp.page;
    await expect(page.getByText("Not set", { exact: true })).toBeVisible();
    await page.getByPlaceholder("Camera password").fill("clave.Cam-1");
    await page.getByRole("button", { name: "Save password" }).click();
    await expect.poll(() => calls.password).toBe("clave.Cam-1");
    await expect(page.getByText("Set", { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder(/New password/)).toHaveValue("");
  });

  test("shows an error with retry instead of spinning", async ({
    frigateApp,
  }) => {
    await frigateApp.page.route("**/api/orbi360/network", (route) =>
      route.fulfill({ status: 500, json: { message: "boom" } }),
    );
    await frigateApp.goto("/settings?page=cameraNetwork");
    await expect(
      frigateApp.page.getByText(/Could not load the camera network: boom/),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByRole("button", { name: "Retry" }),
    ).toBeVisible();
  });
});

test.describe("Orbi360 camera network — mobile @medium @mobile", () => {
  test.skip(({ frigateApp }) => !frigateApp.isMobile, "Mobile-only");

  test("add camera dialog fits the phone screen", async ({ frigateApp }) => {
    await installNetworkRoutes(frigateApp.page);
    await frigateApp.goto("/settings?page=cameraNetwork");
    await frigateApp.page
      .getByRole("button", { name: "Add camera by IP" })
      .click();
    const dialog = frigateApp.page.getByRole("dialog");
    await expect(dialog.getByLabel("Camera IP")).toBeInViewport();
    await expect(
      dialog.getByRole("button", { name: "Add", exact: true }),
    ).toBeInViewport();
  });
});
