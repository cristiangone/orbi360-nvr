export type SrtMosaicResolution = "1920x1080" | "1280x720";
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
};

export type SrtMosaicsResponse = {
  mosaics: SrtMosaic[];
  status: Record<string, string>;
  streams: string[];
  supported: boolean;
};
