import Heading from "@/components/ui/heading";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import ActivityIndicator from "@/components/indicators/activity-indicator";
import { cn } from "@/lib/utils";
import { CameraNetworkResponse, CameraNetworkStatus } from "@/types/orbi360";
import axios, { AxiosError } from "axios";
import copy from "copy-to-clipboard";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { LuCopy, LuEyeOff, LuPlus, LuRadar, LuRotateCcw } from "react-icons/lu";
import { toast } from "sonner";
import useSWR from "swr";
import AddCameraDialog from "./components/AddCameraDialog";
import CameraPasswordCard from "./components/CameraPasswordCard";

const STATUS_CLASSES: Record<CameraNetworkStatus, string> = {
  ok: "border-green-500 text-green-500",
  moved: "border-sky-500 text-sky-500",
  not_seen: "border-destructive text-destructive",
  shared_ip: "border-amber-500 text-amber-500",
  factory_ip: "border-amber-500 text-amber-500",
  bridged: "border-amber-500 text-amber-500",
};

function formatDateTime(epoch?: number | null): string {
  if (!epoch) {
    return "—";
  }
  return new Date(epoch * 1000).toLocaleString([], {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CameraNetworkSettingsView() {
  const { t } = useTranslation("views/settings");
  // the locator scans every 3 minutes on the NVR; refresh to show its findings
  const { data, error, mutate } = useSWR<CameraNetworkResponse>(
    "orbi360/network",
    { refreshInterval: 30000 },
  );
  const [scanning, setScanning] = useState(false);
  // undefined: closed; {}: add by IP; {ip, mac}: add a discovered device
  const [adding, setAdding] = useState<{ ip?: string; mac?: string }>();
  // name of the camera just added while the NVR restarts to load it
  const [restarting, setRestarting] = useState<string>();

  // Adding a camera restarts the NVR (--no-block): wait until its API answers
  // again (twice in a row, after the old process has stopped), then reload the
  // page data so the camera shows as configured and the next one can be added
  useEffect(() => {
    if (!restarting) {
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const started = Date.now();
    let answers = 0;
    const tick = async () => {
      if (cancelled) {
        return;
      }
      const elapsed = Date.now() - started;
      if (elapsed > 8000) {
        try {
          await axios.get("version", { timeout: 3000 });
          answers += 1;
        } catch {
          answers = 0;
        }
        if (answers >= 2 || elapsed > 240000) {
          await mutate();
          if (!cancelled) {
            setRestarting(undefined);
          }
          return;
        }
      }
      timer = setTimeout(tick, 3000);
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [restarting, mutate]);

  const showError = useCallback(
    (error: unknown) => {
      const message =
        (error as AxiosError<{ message?: string }>).response?.data?.message ??
        String(error);
      toast.error(t("cameraNetwork.toast.error", { message }), {
        position: "top-center",
        closeButton: true,
      });
    },
    [t],
  );

  const scan = useCallback(async () => {
    setScanning(true);
    try {
      const response = await axios.post<CameraNetworkResponse>(
        "orbi360/network/scan",
      );
      await mutate(response.data, false);
      toast.success(t("cameraNetwork.toast.scanned"), {
        position: "top-center",
      });
    } catch (error) {
      showError(error);
    } finally {
      setScanning(false);
    }
  }, [mutate, showError, t]);

  const ignore = useCallback(
    async (mac: string) => {
      try {
        await axios.post("orbi360/network/ignore", { mac });
        await mutate();
        toast.success(t("cameraNetwork.toast.ignored"), {
          position: "top-center",
        });
      } catch (error) {
        showError(error);
      }
    },
    [mutate, showError, t],
  );

  const forget = useCallback(
    async (camera: string) => {
      try {
        await axios.post("orbi360/network/forget", { camera });
        await mutate();
        toast.success(t("cameraNetwork.toast.forgotten", { camera }), {
          position: "top-center",
        });
      } catch (error) {
        showError(error);
      }
    },
    [mutate, showError, t],
  );

  if (!data) {
    if (error) {
      // without this the page kept spinning after one failed load
      return (
        <div className="flex flex-col items-start gap-3 p-4 text-sm">
          <span className="text-destructive">
            {t("cameraNetwork.loadError", {
              message:
                (error as AxiosError<{ message?: string }>).response?.data
                  ?.message ?? String(error),
            })}
          </span>
          <Button onClick={() => mutate()}>{t("cameraNetwork.retry")}</Button>
        </div>
      );
    }
    return <ActivityIndicator />;
  }

  const cameras = Object.entries(data.cameras).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  const discovered = Object.entries(data.discovered);

  return (
    <div className="flex size-full flex-col">
      <div className="scrollbar-container flex h-full w-full flex-col overflow-y-auto px-2 pb-6">
        <Heading as="h4" className="mb-2 hidden md:block">
          {t("cameraNetwork.title")}
        </Heading>
        <p className="mb-4 max-w-4xl text-sm text-muted-foreground">
          {t("cameraNetwork.desc", { factory: data.factory_ips.join(", ") })}
        </p>

        {!data.supported && (
          <div className="mb-4 max-w-4xl rounded-lg border border-destructive p-3 text-sm text-destructive">
            {t("cameraNetwork.unsupported")}
          </div>
        )}

        <CameraPasswordCard />

        {restarting && (
          <div className="mb-4 flex max-w-4xl items-center gap-3 rounded-lg border border-sky-500 p-3 text-sm">
            <ActivityIndicator className="size-4" />
            {t("cameraNetwork.add.restarting", { camera: restarting })}
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Button
            variant="select"
            onClick={scan}
            disabled={scanning || !data.supported}
          >
            {scanning ? (
              <ActivityIndicator className="mr-2 size-4" />
            ) : (
              <LuRadar className="mr-2 size-4" />
            )}
            {scanning ? t("cameraNetwork.scanning") : t("cameraNetwork.scan")}
          </Button>
          <Button onClick={() => setAdding({})} disabled={!!restarting}>
            <LuPlus className="mr-2 size-4" />
            {t("cameraNetwork.add.byIp")}
          </Button>
          <span className="text-xs text-muted-foreground">
            {t("cameraNetwork.lastScan", {
              time: formatDateTime(data.last_scan),
            })}
          </span>
        </div>

        <Heading as="h4" className="mb-2 text-base">
          {t("cameraNetwork.cameras.title")}
        </Heading>
        {cameras.length === 0 ? (
          <p className="mb-6 text-sm text-muted-foreground">
            {t("cameraNetwork.cameras.empty")}
          </p>
        ) : (
          <div className="mb-6 max-w-5xl overflow-x-auto rounded-lg bg-secondary">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="p-3">{t("cameraNetwork.cameras.name")}</th>
                  <th className="p-3">{t("cameraNetwork.cameras.ip")}</th>
                  <th className="p-3">{t("cameraNetwork.cameras.mac")}</th>
                  <th className="p-3">{t("cameraNetwork.cameras.status")}</th>
                  <th className="p-3">{t("cameraNetwork.cameras.lastSeen")}</th>
                </tr>
              </thead>
              <tbody>
                {cameras.map(([name, cam]) => {
                  const status = cam.status ?? "not_seen";
                  return (
                    <tr key={name} className="border-t border-background">
                      <td className="p-3 font-medium">{name}</td>
                      <td className="p-3 font-mono text-xs">{cam.ip ?? "—"}</td>
                      <td className="p-3 font-mono text-xs">
                        {cam.mac ?? "—"}
                        {cam.vendor && (
                          <span className="block font-sans text-muted-foreground">
                            {cam.vendor}
                          </span>
                        )}
                        {cam.mac && (
                          <button
                            type="button"
                            className="mt-1 flex items-center gap-1 font-sans text-xs text-muted-foreground underline-offset-2 hover:underline"
                            title={t("cameraNetwork.cameras.forgetHint")}
                            onClick={() => forget(name)}
                          >
                            <LuRotateCcw className="size-3" />
                            {t("cameraNetwork.cameras.forget")}
                          </button>
                        )}
                      </td>
                      <td className="p-3">
                        <Badge
                          variant="outline"
                          className={STATUS_CLASSES[status]}
                          title={t(`cameraNetwork.statusHint.${status}`)}
                        >
                          {t(`cameraNetwork.status.${status}`)}
                        </Badge>
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {t(`cameraNetwork.statusHint.${status}`)}
                        </span>
                      </td>
                      <td className="p-3 text-xs text-muted-foreground">
                        {formatDateTime(cam.last_seen)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <Heading as="h4" className="mb-2 text-base">
          {t("cameraNetwork.discovered.title")}
        </Heading>
        <p className="mb-3 max-w-4xl text-xs text-muted-foreground">
          {t("cameraNetwork.discovered.desc")}
        </p>
        {discovered.length === 0 ? (
          <p className="mb-6 text-sm text-muted-foreground">
            {t("cameraNetwork.discovered.empty")}
          </p>
        ) : (
          <div className="mb-6 grid max-w-5xl grid-cols-1 gap-3 lg:grid-cols-2">
            {discovered.map(([mac, device]) => (
              <div
                key={mac}
                className="flex flex-col gap-2 rounded-lg bg-secondary p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm font-medium">
                    {device.ip}
                  </span>
                  <Badge
                    variant="outline"
                    className="border-sky-500 text-sky-500"
                  >
                    {t("cameraNetwork.discovered.new")}
                  </Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  <span className="font-mono">{mac.split("@")[0]}</span>
                  {device.vendor && ` · ${device.vendor}`}
                  {device.bridged && (
                    <span className="block text-amber-500">
                      {t("cameraNetwork.discovered.bridged")}
                    </span>
                  )}
                  <span className="block">
                    {t("cameraNetwork.discovered.firstSeen", {
                      time: formatDateTime(device.first_seen),
                    })}
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="select"
                    disabled={!!restarting}
                    onClick={() => setAdding({ ip: device.ip, mac })}
                  >
                    <LuPlus className="mr-2 size-4" />
                    {t("cameraNetwork.discovered.add")}
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => {
                      copy(device.ip);
                      toast.success(t("cameraNetwork.toast.copied"), {
                        position: "top-center",
                      });
                    }}
                  >
                    <LuCopy className="mr-2 size-4" />
                    {t("cameraNetwork.discovered.copyIp")}
                  </Button>
                  <Button size="sm" onClick={() => ignore(mac)}>
                    <LuEyeOff className="mr-2 size-4" />
                    {t("cameraNetwork.discovered.ignore")}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        <Heading as="h4" className="mb-2 text-base">
          {t("cameraNetwork.events.title")}
        </Heading>
        {data.events.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("cameraNetwork.events.empty")}
          </p>
        ) : (
          <ul className="max-w-4xl space-y-1 text-sm">
            {data.events.slice(0, 10).map((event, i) => (
              <li key={i} className="flex gap-3">
                <span
                  className={cn(
                    "shrink-0 text-xs text-muted-foreground",
                    "w-24 font-mono",
                  )}
                >
                  {formatDateTime(event.time)}
                </span>
                <span>{event.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <AddCameraDialog
        open={adding !== undefined}
        ip={adding?.ip}
        mac={adding?.mac}
        existing={Object.keys(data.cameras)}
        onClose={() => setAdding(undefined)}
        onAdded={(camera) => setRestarting(camera)}
      />
    </div>
  );
}
