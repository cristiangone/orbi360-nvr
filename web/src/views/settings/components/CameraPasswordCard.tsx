import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import ActivityIndicator from "@/components/indicators/activity-indicator";
import axios, { AxiosError } from "axios";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import useSWR from "swr";

// Password every camera is read with (FRIGATE_RTSP_PASSWORD). It is only
// written: the API says whether it is set, never what it is.
export default function CameraPasswordCard() {
  const { t } = useTranslation("views/settings");
  const { data, mutate } = useSWR<{ set: boolean }>("orbi360/camera-password");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await axios.put("orbi360/camera-password", { password });
      setPassword("");
      await mutate({ set: true }, false);
      toast.success(t("cameraNetwork.password.saved"), {
        position: "top-center",
        duration: 8000,
      });
    } catch (error) {
      const message =
        (error as AxiosError<{ message?: string }>).response?.data?.message ??
        String(error);
      toast.error(t("cameraNetwork.toast.error", { message }), {
        position: "top-center",
        closeButton: true,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-6 flex max-w-4xl flex-col gap-3 rounded-lg bg-secondary p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t("cameraNetwork.password.title")}</span>
        {data && (
          <Badge
            variant="outline"
            className={
              data.set
                ? "border-green-500 text-green-500"
                : "border-amber-500 text-amber-500"
            }
          >
            {data.set
              ? t("cameraNetwork.password.isSet")
              : t("cameraNetwork.password.notSet")}
          </Badge>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {t("cameraNetwork.password.desc")}
      </p>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="camera-password" className="sr-only">
          {t("cameraNetwork.password.title")}
        </Label>
        <div className="flex flex-wrap gap-2">
          <Input
            id="camera-password"
            type="password"
            autoComplete="new-password"
            className="max-w-xs"
            value={password}
            placeholder={
              data?.set
                ? t("cameraNetwork.password.changePlaceholder")
                : t("cameraNetwork.password.placeholder")
            }
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button
            variant="select"
            onClick={save}
            disabled={saving || password.length < 4}
          >
            {saving && <ActivityIndicator className="mr-2 size-4" />}
            {t("cameraNetwork.password.save")}
          </Button>
        </div>
      </div>
    </div>
  );
}
