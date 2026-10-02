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

export type SrtMosaicsResponse = {
  mosaics: SrtMosaic[];
  status: Record<string, string>;
  streams: string[];
  supported: boolean;
};
