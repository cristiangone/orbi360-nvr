import Heading from "@/components/ui/heading";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import ActivityIndicator from "@/components/indicators/activity-indicator";
import { cn } from "@/lib/utils";
import {
  SrtMosaic,
  SrtMosaicEncoder,
  SrtMosaicResolution,
  SrtMosaicsResponse,
} from "@/types/orbi360";
import axios, { AxiosError } from "axios";
import copy from "copy-to-clipboard";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  LuCopy,
  LuEye,
  LuEyeOff,
  LuLock,
  LuPencil,
  LuPlus,
  LuRotateCw,
  LuTrash2,
} from "react-icons/lu";
import { toast } from "sonner";
import useSWR from "swr";

const MAX_STREAMS = 9;
const COUNTS = Array.from({ length: MAX_STREAMS }, (_, i) => i + 1);

// Same grid as orbi360-mosaico.sh: 1 full screen, 2 side by side, 3-4 in 2x2,
// 5-6 in 3x2 and 7-9 in 3x3. Cells without a stream are black.
function gridFor(count: number): { cols: number; rows: number } {
  if (count <= 1) return { cols: 1, rows: 1 };
  if (count === 2) return { cols: 2, rows: 1 };
  if (count <= 4) return { cols: 2, rows: 2 };
  if (count <= 6) return { cols: 3, rows: 2 };
  return { cols: 3, rows: 3 };
}

const GRID_COLS = ["grid-cols-1", "grid-cols-2", "grid-cols-3"];

function GridPreview({ streams }: { streams: string[] }) {
  const { cols, rows } = gridFor(streams.length);
  return (
    <div className={cn("grid gap-1 text-xs", GRID_COLS[cols - 1])}>
      {Array.from({ length: cols * rows }, (_, i) => (
        <div
          key={i}
          className={cn(
            "h-6 truncate rounded px-2 py-1",
            i < streams.length ? "bg-background_alt" : "bg-black/80",
          )}
          title={streams[i]}
        >
          {streams[i] ?? ""}
        </div>
      ))}
    </div>
  );
}
const RESOLUTIONS: SrtMosaicResolution[] = ["1920x1080", "1280x720"];
const ENCODERS: SrtMosaicEncoder[] = ["auto", "vaapi", "x264"];

function slugify(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
}

// The copied address includes the passphrase so it can be pasted as is in a
// player; the one shown on the card masks it
function srtUrl(mosaic: SrtMosaic, masked = false): string {
  const url = `srt://${window.location.hostname}:${mosaic.srt_port}?mode=caller&latency=${mosaic.latency_ms}`;
  if (!mosaic.passphrase) {
    return url;
  }
  const passphrase = masked ? "\u2022".repeat(8) : mosaic.passphrase;
  return `${url}&passphrase=${passphrase}&pbkeylen=16`;
}

const PASSPHRASE_CHARS =
  "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";

function generatePassphrase(length = 20): string {
  const bytes = new Uint32Array(length);
  crypto.getRandomValues(bytes);
  return Array.from(
    bytes,
    (b) => PASSPHRASE_CHARS[b % PASSPHRASE_CHARS.length],
  ).join("");
}

export default function SrtMosaicsSettingsView() {
  const { t } = useTranslation("views/settings");
  const { data, mutate } = useSWR<SrtMosaicsResponse>("orbi360/mosaics");
  const [editing, setEditing] = useState<SrtMosaic | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [deleting, setDeleting] = useState<SrtMosaic | null>(null);
  const [busy, setBusy] = useState(false);

  const mosaics = useMemo(() => data?.mosaics ?? [], [data]);
  const streams = useMemo(() => data?.streams ?? [], [data]);

  const save = useCallback(
    async (next: SrtMosaic[]) => {
      setBusy(true);
      try {
        const response = await axios.put<SrtMosaicsResponse>(
          "orbi360/mosaics",
          { mosaics: next },
        );
        await mutate(response.data, false);
        toast.success(t("srtMosaics.toast.saved"), { position: "top-center" });
        return true;
      } catch (error) {
        const message =
          (error as AxiosError<{ message?: string }>).response?.data?.message ??
          String(error);
        toast.error(t("srtMosaics.toast.error", { message }), {
          position: "top-center",
          closeButton: true,
        });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [mutate, t],
  );

  const restart = useCallback(
    async (mosaic: SrtMosaic) => {
      try {
        await axios.post(`orbi360/mosaics/${mosaic.id}/restart`);
        toast.success(t("srtMosaics.toast.restarted", { name: mosaic.name }), {
          position: "top-center",
        });
        mutate();
      } catch {
        toast.error(t("srtMosaics.toast.restartError"), {
          position: "top-center",
        });
      }
    },
    [mutate, t],
  );

  const openNew = useCallback(() => {
    const used = new Set(mosaics.map((m) => m.srt_port));
    let port = 9999;
    while (used.has(port) || used.has(port - 10000)) {
      port = port === 9999 ? 9000 : port + 1;
    }
    const subStreams = streams.filter((s) => s.endsWith("_sub"));
    const pool = subStreams.length >= 4 ? subStreams : streams;
    setIsNew(true);
    setEditing({
      id: "",
      name: "",
      enabled: true,
      streams: [0, 1, 2, 3].map((i) => pool[i] ?? ""),
      srt_port: port,
      latency_ms: 5000,
      bitrate_kbps: 2500,
      fps: 15,
      resolution: "1920x1080",
      encoder: "auto",
      passphrase: null,
    });
  }, [mosaics, streams]);

  const submitEdit = useCallback(async () => {
    if (!editing) {
      return;
    }
    const mosaic = {
      ...editing,
      id: isNew ? slugify(editing.name) : editing.id,
    };
    if (!mosaic.id) {
      toast.error(t("srtMosaics.form.nameRequired"), {
        position: "top-center",
      });
      return;
    }
    if (mosaic.streams.some((s) => !s)) {
      toast.error(t("srtMosaics.form.streamsRequired"), {
        position: "top-center",
      });
      return;
    }
    const next = isNew
      ? [...mosaics, mosaic]
      : mosaics.map((m) => (m.id === mosaic.id ? mosaic : m));
    if (await save(next)) {
      setEditing(null);
    }
  }, [editing, isNew, mosaics, save, t]);

  if (!data) {
    return <ActivityIndicator />;
  }

  return (
    <div className="flex size-full flex-col">
      <div className="scrollbar-container flex h-full w-full flex-col overflow-y-auto px-2">
        <Heading as="h4" className="mb-2 hidden md:block">
          {t("srtMosaics.title")}
        </Heading>
        <p className="mb-4 max-w-4xl text-sm text-muted-foreground">
          {t("srtMosaics.desc")}
        </p>

        {!data.supported && (
          <div className="mb-4 max-w-4xl rounded-lg border border-destructive p-3 text-sm text-destructive">
            {t("srtMosaics.unsupported")}
          </div>
        )}

        <div className="mb-4">
          <Button variant="select" onClick={openNew} disabled={busy}>
            <LuPlus className="mr-2 size-4" />
            {t("srtMosaics.add")}
          </Button>
        </div>

        {mosaics.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t("srtMosaics.empty")}
          </p>
        )}

        <div className="grid max-w-5xl grid-cols-1 gap-4 pb-6 lg:grid-cols-2">
          {mosaics.map((mosaic) => {
            const status = data.status[mosaic.id] ?? "unknown";
            return (
              <div
                key={mosaic.id}
                className="flex flex-col gap-3 rounded-lg bg-secondary p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{mosaic.name}</span>
                    <Badge
                      variant="outline"
                      className={cn(
                        status === "active" &&
                          "border-green-500 text-green-500",
                        status === "failed" &&
                          "border-destructive text-destructive",
                      )}
                    >
                      {t(`srtMosaics.status.${status}`, {
                        defaultValue: status,
                      })}
                    </Badge>
                    {mosaic.passphrase && (
                      <Badge variant="outline" className="gap-1">
                        <LuLock className="size-3" />
                        {t("srtMosaics.encrypted")}
                      </Badge>
                    )}
                  </div>
                  <Switch
                    checked={mosaic.enabled}
                    disabled={busy}
                    aria-label={t("srtMosaics.form.enabled")}
                    onCheckedChange={(enabled) =>
                      save(
                        mosaics.map((m) =>
                          m.id === mosaic.id ? { ...m, enabled } : m,
                        ),
                      )
                    }
                  />
                </div>

                <GridPreview streams={mosaic.streams} />

                <div className="flex items-center gap-2">
                  <code className="flex-1 truncate rounded bg-background_alt px-2 py-1 text-xs">
                    {srtUrl(mosaic, true)}
                  </code>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t("srtMosaics.copy")}
                    onClick={() => {
                      copy(srtUrl(mosaic));
                      toast.success(t("srtMosaics.toast.copied"), {
                        position: "top-center",
                      });
                    }}
                  >
                    <LuCopy className="size-4" />
                  </Button>
                </div>

                <div className="text-xs text-muted-foreground">
                  {t("srtMosaics.summary", {
                    count: mosaic.streams.length,
                    layout: t(`srtMosaics.layouts.${mosaic.streams.length}`),
                    resolution: mosaic.resolution,
                    fps: mosaic.fps,
                    bitrate: mosaic.bitrate_kbps,
                    encoder: t(`srtMosaics.encoders.${mosaic.encoder}`),
                  })}
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={busy}
                    onClick={() => {
                      setIsNew(false);
                      setEditing({ ...mosaic });
                    }}
                  >
                    <LuPencil className="mr-2 size-4" />
                    {t("srtMosaics.edit")}
                  </Button>
                  <Button
                    size="sm"
                    disabled={busy || !mosaic.enabled || !data.supported}
                    onClick={() => restart(mosaic)}
                  >
                    <LuRotateCw className="mr-2 size-4" />
                    {t("srtMosaics.restart")}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={busy}
                    onClick={() => setDeleting(mosaic)}
                  >
                    <LuTrash2 className="mr-2 size-4" />
                    {t("srtMosaics.delete")}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <Dialog
        open={editing != null}
        onOpenChange={(open) => !open && setEditing(null)}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {isNew
                ? t("srtMosaics.form.titleNew")
                : t("srtMosaics.form.titleEdit")}
            </DialogTitle>
            <DialogDescription>{t("srtMosaics.form.desc")}</DialogDescription>
          </DialogHeader>

          {editing && (
            <div className="flex flex-col gap-4">
              <div className="space-y-1">
                <Label htmlFor="mosaic-name">{t("srtMosaics.form.name")}</Label>
                <Input
                  id="mosaic-name"
                  value={editing.name}
                  maxLength={64}
                  onChange={(e) =>
                    setEditing({ ...editing, name: e.target.value })
                  }
                />
              </div>

              <div className="space-y-1">
                <Label>{t("srtMosaics.form.count")}</Label>
                <Select
                  value={String(editing.streams.length)}
                  onValueChange={(value) => {
                    const count = parseInt(value, 10);
                    const unused = streams.filter(
                      (s) => s.endsWith("_sub") && !editing.streams.includes(s),
                    );
                    const next = editing.streams.slice(0, count);
                    while (next.length < count) {
                      next.push(unused.shift() ?? "");
                    }
                    setEditing({ ...editing, streams: next });
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COUNTS.map((count) => (
                      <SelectItem key={count} value={String(count)}>
                        {t("srtMosaics.form.countOption", {
                          count,
                          layout: t(`srtMosaics.layouts.${count}`),
                        })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <Label>{t("srtMosaics.form.streams")}</Label>
                <div
                  className={cn(
                    "grid gap-2",
                    GRID_COLS[gridFor(editing.streams.length).cols - 1],
                  )}
                >
                  {editing.streams.map((value, i) => (
                    <div key={i} className="min-w-0 space-y-1">
                      <span className="text-xs text-muted-foreground">
                        {t("srtMosaics.form.tile", { n: i + 1 })}
                      </span>
                      <Select
                        value={value || undefined}
                        onValueChange={(selected) => {
                          const next = [...editing.streams];
                          next[i] = selected;
                          setEditing({ ...editing, streams: next });
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue
                            placeholder={t("srtMosaics.form.pickStream")}
                          />
                        </SelectTrigger>
                        <SelectContent>
                          {streams.map((stream) => (
                            <SelectItem key={stream} value={stream}>
                              {stream}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {t("srtMosaics.form.streamsHint")}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <NumberField
                  id="mosaic-port"
                  label={t("srtMosaics.form.port")}
                  value={editing.srt_port}
                  onChange={(srt_port) => setEditing({ ...editing, srt_port })}
                />
                <NumberField
                  id="mosaic-latency"
                  label={t("srtMosaics.form.latency")}
                  value={editing.latency_ms}
                  onChange={(latency_ms) =>
                    setEditing({ ...editing, latency_ms })
                  }
                />
                <NumberField
                  id="mosaic-bitrate"
                  label={t("srtMosaics.form.bitrate")}
                  value={editing.bitrate_kbps}
                  onChange={(bitrate_kbps) =>
                    setEditing({ ...editing, bitrate_kbps })
                  }
                />
                <NumberField
                  id="mosaic-fps"
                  label={t("srtMosaics.form.fps")}
                  value={editing.fps}
                  onChange={(fps) => setEditing({ ...editing, fps })}
                />
                <div className="space-y-1">
                  <Label>{t("srtMosaics.form.resolution")}</Label>
                  <Select
                    value={editing.resolution}
                    onValueChange={(value) =>
                      setEditing({
                        ...editing,
                        resolution: value as SrtMosaicResolution,
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {RESOLUTIONS.map((r) => (
                        <SelectItem key={r} value={r}>
                          {r}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>{t("srtMosaics.form.encoder")}</Label>
                  <Select
                    value={editing.encoder}
                    onValueChange={(value) =>
                      setEditing({
                        ...editing,
                        encoder: value as SrtMosaicEncoder,
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ENCODERS.map((e) => (
                        <SelectItem key={e} value={e}>
                          {t(`srtMosaics.encoders.${e}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <PassphraseField
                value={editing.passphrase ?? ""}
                onChange={(passphrase) =>
                  setEditing({ ...editing, passphrase: passphrase || null })
                }
              />

              <div className="flex items-center justify-between">
                <Label htmlFor="mosaic-enabled">
                  {t("srtMosaics.form.enabled")}
                </Label>
                <Switch
                  id="mosaic-enabled"
                  checked={editing.enabled}
                  onCheckedChange={(enabled) =>
                    setEditing({ ...editing, enabled })
                  }
                />
              </div>
            </div>
          )}

          <DialogFooter className="gap-2">
            <Button onClick={() => setEditing(null)} disabled={busy}>
              {t("button.cancel", { ns: "common" })}
            </Button>
            <Button variant="select" onClick={submitEdit} disabled={busy}>
              {busy && <ActivityIndicator className="mr-2 size-4" />}
              {t("button.save", { ns: "common" })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleting != null}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("srtMosaics.deleteConfirm.title")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("srtMosaics.deleteConfirm.desc", { name: deleting?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t("button.cancel", { ns: "common" })}
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={() => {
                if (deleting) {
                  save(mosaics.filter((m) => m.id !== deleting.id));
                }
                setDeleting(null);
              }}
            >
              {t("srtMosaics.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

type PassphraseFieldProps = {
  value: string;
  onChange: (value: string) => void;
};

function PassphraseField({ value, onChange }: PassphraseFieldProps) {
  const { t } = useTranslation("views/settings");
  const [visible, setVisible] = useState(false);
  return (
    <div className="space-y-1">
      <Label htmlFor="mosaic-passphrase">
        {t("srtMosaics.form.passphrase")}
      </Label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Input
            id="mosaic-passphrase"
            type={visible ? "text" : "password"}
            autoComplete="new-password"
            maxLength={79}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          <button
            type="button"
            className="absolute inset-y-0 right-2 flex items-center text-muted-foreground"
            aria-label={t("srtMosaics.form.togglePassphrase")}
            onClick={() => setVisible(!visible)}
          >
            {visible ? (
              <LuEyeOff className="size-4" />
            ) : (
              <LuEye className="size-4" />
            )}
          </button>
        </div>
        <Button
          type="button"
          onClick={() => {
            onChange(generatePassphrase());
            setVisible(true);
          }}
        >
          {t("srtMosaics.form.generate")}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("srtMosaics.form.passphraseHint")}
      </p>
    </div>
  );
}

type NumberFieldProps = {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
};

function NumberField({ id, label, value, onChange }: NumberFieldProps) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) => onChange(parseInt(e.target.value, 10))}
      />
    </div>
  );
}
