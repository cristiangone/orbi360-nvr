import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import ActivityIndicator from "@/components/indicators/activity-indicator";
import {
  AddCameraResult,
  CameraProbeResult,
  CameraProtocol,
} from "@/types/orbi360";
import axios, { AxiosError } from "axios";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

type AddCameraDialogProps = {
  open: boolean;
  // device found by the locator; without it the IP is typed by hand
  ip?: string;
  mac?: string;
  existing: string[];
  onClose: () => void;
  // called with the camera name once it is saved (the NVR is restarting)
  onAdded: (camera: string) => void;
};

// "Patio Norte" -> "patio_norte" (same rule as frigate/orbi360/camadd.py)
function cameraSlug(text: string): string {
  let name = text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (name && !/^[a-z]/.test(name)) {
    name = `cam_${name}`;
  }
  return name.slice(0, 30);
}

function errorMessage(error: unknown): string {
  return (
    (error as AxiosError<{ message?: string }>).response?.data?.message ??
    String(error)
  );
}

export default function AddCameraDialog({
  open,
  ip: foundIp,
  mac,
  existing,
  onClose,
  onAdded,
}: AddCameraDialogProps) {
  const { t } = useTranslation("views/settings");
  const [ip, setIp] = useState(foundIp ?? "");
  const [friendlyName, setFriendlyName] = useState("");
  const [probe, setProbe] = useState<CameraProbeResult | null>(null);
  const [probing, setProbing] = useState(false);
  const [custom, setCustom] = useState(false);
  const [mainUrl, setMainUrl] = useState("");
  const [subUrl, setSubUrl] = useState("");
  const [toH264, setToH264] = useState(true);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (open) {
      setIp(foundIp ?? "");
      setFriendlyName("");
      setProbe(null);
      setCustom(false);
      setMainUrl("");
      setSubUrl("");
      setToH264(true);
    }
  }, [open, foundIp]);

  const name = useMemo(() => cameraSlug(friendlyName), [friendlyName]);
  const nameTaken = existing.includes(name);
  const protocol: CameraProtocol | null = custom
    ? "custom"
    : (probe?.protocol ?? null);
  const canAdd =
    !!name &&
    name.length >= 2 &&
    !nameTaken &&
    !adding &&
    (custom ? mainUrl.trim().length > 0 : !!probe?.protocol);

  const detect = async () => {
    setProbing(true);
    setProbe(null);
    try {
      const response = await axios.post<CameraProbeResult>(
        "orbi360/network/probe",
        { ip },
      );
      setProbe(response.data);
    } catch (error) {
      setProbe({ protocol: null, ip, message: errorMessage(error) });
    } finally {
      setProbing(false);
    }
  };

  const add = async () => {
    if (!protocol) {
      return;
    }
    setAdding(true);
    try {
      const response = await axios.post<AddCameraResult>(
        "orbi360/network/add",
        {
          name,
          friendly_name: friendlyName.trim(),
          protocol,
          ip,
          mac,
          main_url: mainUrl,
          sub_url: subUrl,
          to_h264: protocol === "dvrip" && probe?.codec === "H.265" && toH264,
        },
      );
      toast.success(
        t("cameraNetwork.add.done", { camera: friendlyName.trim() }),
        { position: "top-center", duration: 8000 },
      );
      response.data.notes?.forEach((note) =>
        toast.info(note, { position: "top-center", duration: 8000 }),
      );
      onAdded(friendlyName.trim() || name);
      onClose();
    } catch (error) {
      toast.error(
        t("cameraNetwork.toast.error", { message: errorMessage(error) }),
        { position: "top-center", closeButton: true },
      );
    } finally {
      setAdding(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("cameraNetwork.add.title")}</DialogTitle>
          <DialogDescription>{t("cameraNetwork.add.desc")}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="add-cam-name">
              {t("cameraNetwork.add.friendlyName")}
            </Label>
            <Input
              id="add-cam-name"
              value={friendlyName}
              placeholder={t("cameraNetwork.add.friendlyNamePlaceholder")}
              onChange={(e) => setFriendlyName(e.target.value)}
            />
            <span className="text-xs text-muted-foreground">
              {nameTaken
                ? t("cameraNetwork.add.nameTaken", { name })
                : t("cameraNetwork.add.internalName", { name: name || "—" })}
            </span>
          </div>

          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="add-cam-custom">
              {t("cameraNetwork.add.custom")}
            </Label>
            <Switch
              id="add-cam-custom"
              checked={custom}
              onCheckedChange={setCustom}
            />
          </div>

          {custom ? (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="add-cam-main">
                  {t("cameraNetwork.add.mainUrl")}
                </Label>
                <Input
                  id="add-cam-main"
                  value={mainUrl}
                  placeholder="rtsp://usuario:{FRIGATE_RTSP_PASSWORD}@IP:554/…"
                  onChange={(e) => setMainUrl(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="add-cam-sub">
                  {t("cameraNetwork.add.subUrl")}
                </Label>
                <Input
                  id="add-cam-sub"
                  value={subUrl}
                  onChange={(e) => setSubUrl(e.target.value)}
                />
                <span className="text-xs text-muted-foreground">
                  {t("cameraNetwork.add.customHint")}
                </span>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="add-cam-ip">{t("cameraNetwork.add.ip")}</Label>
                <div className="flex gap-2">
                  <Input
                    id="add-cam-ip"
                    value={ip}
                    disabled={!!foundIp}
                    placeholder="192.168.1.50"
                    onChange={(e) => {
                      setIp(e.target.value);
                      setProbe(null);
                    }}
                  />
                  <Button onClick={detect} disabled={!ip || probing}>
                    {probing && <ActivityIndicator className="mr-2 size-4" />}
                    {t("cameraNetwork.add.detect")}
                  </Button>
                </div>
              </div>
              {probe && (
                <div
                  className={
                    probe.protocol
                      ? "rounded-md border border-green-500 p-3 text-sm"
                      : "rounded-md border border-destructive p-3 text-sm text-destructive"
                  }
                >
                  {probe.protocol
                    ? t(`cameraNetwork.add.detected.${probe.protocol}`)
                    : probe.message}
                  {probe.protocol === "dvrip" && probe.codec === "H.265" && (
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <Label htmlFor="add-cam-h264" className="font-normal">
                        {t("cameraNetwork.add.toH264")}
                      </Label>
                      <Switch
                        id="add-cam-h264"
                        checked={toH264}
                        onCheckedChange={setToH264}
                      />
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button onClick={onClose}>{t("cameraNetwork.add.cancel")}</Button>
          <Button variant="select" onClick={add} disabled={!canAdd}>
            {adding && <ActivityIndicator className="mr-2 size-4" />}
            {t("cameraNetwork.add.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
