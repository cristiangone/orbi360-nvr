#!/bin/bash
# ============================================================================
#  orbi360-mosaico: mosaico 2x2 de camaras publicado como SRT listener
#
#  Basado en mosaico.sh de Jorge Garay. Flujo:
#    4 streams del restream de go2rtc (rtsp://127.0.0.1:8554/<camara>)
#      --> ffmpeg (grilla 2x2, H.264 + audio mudo) --> UDP local
#      --> srt-live-transmit --> SRT listener :SRT_PORT
#
#  El cliente (transcoder/Nimble/etc.) hace PULL con:
#    srt://<IP-del-NVR>:<SRT_PORT>?mode=caller&latency=<SRT_LATENCY>
#
#  Configuracion: /etc/orbi360-mosaico.conf (ver orbi360/mosaico/orbi360-mosaico.conf)
#  Servicio:      systemctl {start|stop|status} orbi360-mosaico
# ============================================================================
set -u

CONF="${CONF:-/etc/orbi360-mosaico.conf}"
# shellcheck source=/dev/null
[[ -f "$CONF" ]] && source "$CONF"

# Valores por defecto (los del script original de Jorge)
CAMS=(${CAMS:-})                     # nombres de streams de go2rtc, en orden: arriba-izq, arriba-der, abajo-izq, abajo-der
SOURCE="${SOURCE:-sub}"              # sub: stream secundario (liviano) | main: stream principal
RTSP_BASE="${RTSP_BASE:-rtsp://127.0.0.1:8554}"
SRT_PORT="${SRT_PORT:-9999}"         # UDP; abrirlo/mapearlo como UDP
SRT_LATENCY="${SRT_LATENCY:-5000}"   # ms. Mas alto = tolera mas perdida de red, mas delay
BITRATE="${BITRATE:-2500}"           # kbit/s de video del mosaico
FPS="${FPS:-15}"
TILE_W="${TILE_W:-960}"; TILE_H="${TILE_H:-540}"   # 960x540 por cuadro -> canvas 1920x1080
UDP_PORT="${UDP_PORT:-1234}"         # puerto UDP interno encoder -> relay (solo localhost)
ENCODER="${ENCODER:-auto}"           # auto | vaapi | x264
VAAPI_DEVICE="${VAAPI_DEVICE:-/dev/dri/renderD128}"
FFMPEG="${FFMPEG:-/usr/lib/ffmpeg/8.0/bin/ffmpeg}"

if [[ ${#CAMS[@]} -ne 4 ]]; then
  echo "[mosaico] Se necesitan exactamente 4 camaras en CAMS (hay ${#CAMS[@]}). Editar $CONF" >&2
  exit 1
fi
for bin in "$FFMPEG" srt-live-transmit; do
  command -v "$bin" >/dev/null || { echo "[mosaico] Falta '$bin'" >&2; exit 1; }
done

if [[ "$ENCODER" == auto ]]; then
  [[ -e "$VAAPI_DEVICE" ]] && ENCODER=vaapi || ENCODER=x264
fi

UDP="udp://127.0.0.1:${UDP_PORT}"
GOP=$((FPS * 2))

# Opciones por input: TCP para RTSP y tolerancia a frames corruptos (camaras WiFi)
INPUTS=()
for cam in "${CAMS[@]}"; do
  [[ "$SOURCE" == sub ]] && cam="${cam}_sub"
  INPUTS+=(-rtsp_transport tcp -thread_queue_size 1024 -fflags +discardcorrupt+genpts -i "${RTSP_BASE}/${cam}")
done

# Grilla 2x2
LAYOUT="[0:v]scale=${TILE_W}:${TILE_H},setsar=1[a];\
[1:v]scale=${TILE_W}:${TILE_H},setsar=1[b];\
[2:v]scale=${TILE_W}:${TILE_H},setsar=1[c];\
[3:v]scale=${TILE_W}:${TILE_H},setsar=1[d];\
[a][b][c][d]xstack=inputs=4:layout=0_0|${TILE_W}_0|0_${TILE_H}|${TILE_W}_${TILE_H},fps=${FPS}"

if [[ "$ENCODER" == vaapi ]]; then
  # Codificacion por hardware en la iGPU Intel: casi no usa CPU
  HW=(-vaapi_device "$VAAPI_DEVICE")
  FILTER="${LAYOUT},format=nv12,hwupload[v]"
  VIDEO=(-c:v h264_vaapi -b:v "${BITRATE}k" -maxrate "${BITRATE}k" -bufsize "$((BITRATE * 2))k"
         -g "$GOP" -bf 0 -aud 1)
else
  HW=()
  FILTER="${LAYOUT},format=yuv420p[v]"
  VIDEO=(-c:v libx264 -preset veryfast -g "$GOP" -keyint_min "$GOP" -sc_threshold 0
         -x264opts repeat-headers=1:aud=1
         -b:v "${BITRATE}k" -maxrate "${BITRATE}k" -bufsize "$((BITRATE * 2))k")
fi

echo "[mosaico] Camaras: ${CAMS[*]} (stream $SOURCE) | encoder: $ENCODER | ${BITRATE}k @ ${FPS} fps"
echo "[mosaico] Publicando en srt://<IP>:${SRT_PORT}?mode=caller&latency=${SRT_LATENCY}"

trap 'kill 0' TERM INT EXIT   # al detener el servicio, termina ambos procesos

# 1) Relay SRT persistente: si el cliente se desconecta, se reinicia solo sin tocar el encoder.
#    Acepta un solo cliente a la vez; lo normal es que lo tome un transcoder y ese reparta.
( while true; do
    srt-live-transmit "${UDP}?mode=listener" \
      "srt://:${SRT_PORT}?mode=listener&latency=${SRT_LATENCY}" 2>&1 | sed -u 's/^/[srt] /'
    sleep 1
  done ) &

# 2) Encoder: si una camara se cae y ffmpeg sale, reintenta sin tumbar el SRT.
#    - anullsrc: pista de audio muda (muchos transcoders exigen audio)
#    - cabeceras repetidas en cada keyframe: un cliente que entra a mitad de stream decodifica enseguida
( while true; do
    "$FFMPEG" -hide_banner -loglevel warning -nostdin "${HW[@]}" \
      "${INPUTS[@]}" \
      -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
      -filter_complex "$FILTER" -map "[v]" -map 4:a \
      "${VIDEO[@]}" \
      -c:a aac -b:a 64k -ac 2 \
      -f mpegts "${UDP}?pkt_size=1316" 2>&1 | sed -u 's/^/[enc] /'
    echo "[enc] ffmpeg salio, reintento en 2s"; sleep 2
  done ) &

wait
