export type SrtMosaicResolution = "1920x1080" | "1280x720";
export type SrtMosaicMode = "listener" | "caller";
export type SrtMosaicEncoder = "auto" | "vaapi" | "x264";

export type SrtMosaic = {
  id: string;
  name: string;
  enabled: boolean;
  streams: string[];
  srt_port: number;
  latency_ms: number;
  bitrate_kbps: number;
  fps: number;
  resolution: SrtMosaicResolution;
  encoder: SrtMosaicEncoder;
  passphrase?: string | null;
  mode?: SrtMosaicMode;
  target_host?: string | null;
  target_port?: number | null;
  stream_id?: string | null;
};

// Live state reported by the running mosaic service
export type SrtMosaicRuntime = {
  srt: "connected" | "connecting" | "waiting" | "unknown";
  srt_since: number | null;
  encoder: "ok" | "starting" | "restarting" | "stalled" | "unknown";
  encoder_since: number | null;
  restarts: number;
  // streams shown as "no signal" while the rest keeps streaming
  missing?: string[];
};

export type SrtMosaicsResponse = {
  mosaics: SrtMosaic[];
  status: Record<string, string>;
  runtime?: Record<string, SrtMosaicRuntime | null>;
  streams: string[];
  supported: boolean;
};

export type TelegramSettings = {
  enabled: boolean;
  chat_id: string | null;
  alert_after_s: number;
  token_set: boolean;
};

// Camera network locator (Ajustes > Red de cámaras)
export type CameraNetworkStatus =
  | "ok"
  | "moved"
  | "not_seen"
  | "shared_ip"
  | "factory_ip";

export type CameraNetworkCamera = {
  ip?: string;
  mac?: string;
  vendor?: string;
  status?: CameraNetworkStatus;
  last_seen?: number;
  moved_at?: number;
};

export type DiscoveredDevice = {
  ip: string;
  vendor?: string;
  first_seen: number;
  last_seen: number;
};

export type CameraNetworkEvent = {
  time: number;
  kind: "moved" | "new";
  text: string;
};

export type CameraNetworkResponse = {
  cameras: Record<string, CameraNetworkCamera>;
  discovered: Record<string, DiscoveredDevice>;
  ignored: string[];
  events: CameraNetworkEvent[];
  last_scan: number | null;
  factory_ips: string[];
  supported: boolean;
};
