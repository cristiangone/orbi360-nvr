#!/bin/bash
# ============================================================================
#  orbi360-mosaico: mosaico de 1 a 9 camaras publicado como SRT listener
#
#  Basado en mosaico.sh de Jorge Garay. Flujo:
#    1 a 9 streams del restream de go2rtc (rtsp://127.0.0.1:8554/<camara>)
#      --> ffmpeg (grilla segun la cantidad, H.264 + audio mudo) --> UDP local
#      --> srt-live-transmit --> SRT listener :SRT_PORT
#
#  Dos modos:
#    listener (MODE=listener): espera clientes; el transcoder/Nimble hace PULL con
#      srt://<IP-del-NVR>:<SRT_PORT>?mode=caller&latency=<SRT_LATENCY>
#    caller (MODE=caller): se conecta y EMPUJA la senal a TARGET_HOST:TARGET_PORT,
#      con STREAM_ID opcional (ej. publish:live/cam o #!::r=live/cam,m=publish)
#
#  Configuracion: la genera la interfaz (Ajustes > Mosaico SRT) en
#                 /config/orbi360/mosaics/<id>.conf
#  Servicio:      systemctl {start|stop|status} orbi360-mosaico@<id>
# ============================================================================
set -u

CONF="${CONF:-/etc/orbi360-mosaico.conf}"
# shellcheck source=/dev/null
[[ -f "$CONF" ]] && source "$CONF"

# Valores por defecto (los del script original de Jorge)
CAMS=(${CAMS:-})                     # 1 a 9 streams de go2rtc, en orden de lectura (izquierda a derecha, arriba a abajo)
SOURCE="${SOURCE:-sub}"              # sub: stream secundario (liviano) | main: stream principal
RTSP_BASE="${RTSP_BASE:-rtsp://127.0.0.1:8554}"
SRT_PORT="${SRT_PORT:-9999}"         # UDP; abrirlo/mapearlo como UDP
SRT_LATENCY="${SRT_LATENCY:-5000}"   # ms. Mas alto = tolera mas perdida de red, mas delay
BITRATE="${BITRATE:-2500}"           # kbit/s de video del mosaico
FPS="${FPS:-15}"
# Tamano final del mosaico. Configs viejas indicaban el cuadro de la grilla 2x2 (TILE_W/TILE_H)
OUT_W="${OUT_W:-$(( ${TILE_W:-960} * 2 ))}"; OUT_H="${OUT_H:-$(( ${TILE_H:-540} * 2 ))}"
UDP_PORT="${UDP_PORT:-1234}"         # puerto UDP interno encoder -> relay (solo localhost)
ENCODER="${ENCODER:-auto}"           # auto | vaapi | x264
SRT_PASSPHRASE="${SRT_PASSPHRASE:-}" # vacio: sin cifrado | 10 a 79 caracteres: AES-128
MODE="${MODE:-listener}"             # listener | caller
TARGET_HOST="${TARGET_HOST:-}"; TARGET_PORT="${TARGET_PORT:-}"; STREAM_ID="${STREAM_ID:-}"
VAAPI_DEVICE="${VAAPI_DEVICE:-/dev/dri/renderD128}"
FFMPEG="${FFMPEG:-/usr/lib/ffmpeg/8.0/bin/ffmpeg}"

N=${#CAMS[@]}
if (( N < 1 || N > 9 )); then
  echo "[mosaico] CAMS debe tener entre 1 y 9 camaras (hay $N). Editar $CONF" >&2
  exit 1
fi
for bin in "$FFMPEG" srt-live-transmit; do
  command -v "$bin" >/dev/null || { echo "[mosaico] Falta '$bin'" >&2; exit 1; }
done

if [[ "$ENCODER" == auto ]]; then
  [[ -e "$VAAPI_DEVICE" ]] && ENCODER=vaapi || ENCODER=x264
fi

UDP="udp://127.0.0.1:${UDP_PORT}"
if [[ "$MODE" == caller ]]; then
  if [[ -z "$TARGET_HOST" || -z "$TARGET_PORT" ]]; then
    echo "[mosaico] Modo caller sin TARGET_HOST/TARGET_PORT. Editar $CONF" >&2
    exit 1
  fi
  SRT_DEST="srt://${TARGET_HOST}:${TARGET_PORT}?mode=caller&latency=${SRT_LATENCY}"
  [[ -n "$STREAM_ID" ]] && SRT_DEST+="&streamid=${STREAM_ID}"
else
  SRT_DEST="srt://:${SRT_PORT}?mode=listener&latency=${SRT_LATENCY}"
fi
if [[ -n "$SRT_PASSPHRASE" ]]; then
  SRT_DEST+="&passphrase=${SRT_PASSPHRASE}&pbkeylen=16"
fi
GOP=$((FPS * 2))

# Opciones por input: TCP para RTSP y tolerancia a frames corruptos (camaras WiFi).
#  - timeout: si la camara deja de mandar datos 10 s, ffmpeg falla y se reintenta.
#  - use_wallclock_as_timestamps: cuando go2rtc se reconecta a la camara, los tiempos
#    RTP vuelven a cero; con los de la camara ffmpeg descartaba los cuadros nuevos y
#    repetia el ultimo para siempre (imagen congelada con el servicio "activo").
INPUTS=()
for cam in "${CAMS[@]}"; do
  [[ "$SOURCE" == sub ]] && cam="${cam}_sub"
  INPUTS+=(-rtsp_transport tcp -timeout 10000000 -use_wallclock_as_timestamps 1
           -thread_queue_size 1024 -fflags +discardcorrupt+genpts -i "${RTSP_BASE}/${cam}")
done

# Grilla segun la cantidad de camaras: 1 pantalla completa, 2 lado a lado, 3-4 en 2x2,
# 5-6 en 3x2 y 7-9 en 3x3. Cada camara se escala sin deformarse (bandas negras si su
# formato no coincide con el cuadro) y los cuadros sin camara quedan en negro.
case $N in
  1) COLS=1; ROWS=1 ;;
  2) COLS=2; ROWS=1 ;;
  3|4) COLS=2; ROWS=2 ;;
  5|6) COLS=3; ROWS=2 ;;
  *) COLS=3; ROWS=3 ;;
esac
TW=$(( OUT_W / COLS / 2 * 2 )); TH=$(( OUT_H / ROWS / 2 * 2 ))

LAYOUT=""; TILES=""; POSITIONS=()
for (( i = 0; i < N; i++ )); do
  LAYOUT+="[${i}:v]scale=${TW}:${TH}:force_original_aspect_ratio=decrease,"
  LAYOUT+="pad=${TW}:${TH}:(ow-iw)/2:(oh-ih)/2,setsar=1[t${i}];"
  TILES+="[t${i}]"
  POSITIONS+=("$(( i % COLS * TW ))_$(( i / COLS * TH ))")
done
if (( N == 1 )); then
  LAYOUT+="[t0]null"
else
  # shortest=1: si una camara se corta, termina y se reintenta en vez de congelar su cuadro
  LAYOUT+="${TILES}xstack=inputs=${N}:layout=$(IFS='|'; echo "${POSITIONS[*]}"):fill=black:shortest=1"
fi
# completa el lienzo si la division no fue exacta y fija los fps de salida
LAYOUT+=",pad=${OUT_W}:${OUT_H}:(ow-iw)/2:(oh-ih)/2,fps=${FPS}"

if [[ "$ENCODER" == vaapi ]]; then
  # Codificacion por hardware en la iGPU Intel: casi no usa CPU
  HW=(-vaapi_device "$VAAPI_DEVICE")
  FILTER="${LAYOUT},format=nv12,hwupload[v]"
  # -rc_mode CBR: sin esto h264_vaapi puede elegir calidad constante e ignorar el bitrate
  VIDEO=(-c:v h264_vaapi -rc_mode CBR -b:v "${BITRATE}k" -maxrate "${BITRATE}k" -bufsize "$((BITRATE * 2))k"
         -g "$GOP" -bf 0 -aud 1)
else
  HW=()
  FILTER="${LAYOUT},format=yuv420p[v]"
  VIDEO=(-c:v libx264 -preset veryfast -g "$GOP" -keyint_min "$GOP" -sc_threshold 0
         -x264opts repeat-headers=1:aud=1
         -b:v "${BITRATE}k" -maxrate "${BITRATE}k" -bufsize "$((BITRATE * 2))k")
fi

echo "[mosaico] Camaras ($N, grilla ${COLS}x${ROWS}): ${CAMS[*]} | ${OUT_W}x${OUT_H} | encoder: $ENCODER | ${BITRATE}k @ ${FPS} fps"
CIFRADO="$([[ -n "$SRT_PASSPHRASE" ]] && echo " (cifrado AES-128 con contrasena)")"
if [[ "$MODE" == caller ]]; then
  echo "[mosaico] Enviando a srt://${TARGET_HOST}:${TARGET_PORT}${STREAM_ID:+ stream ID ${STREAM_ID}}${CIFRADO}"
else
  echo "[mosaico] Publicando en srt://<IP>:${SRT_PORT}?mode=caller&latency=${SRT_LATENCY}${CIFRADO}"
fi

trap 'kill 0' TERM INT EXIT   # al detener el servicio, termina ambos procesos

# 1) Relay SRT persistente, independiente del encoder:
#    - listener: si el cliente se desconecta, vuelve a esperar. Un cliente a la vez; lo normal
#      es que lo tome un transcoder y ese reparta.
#    - caller: si el servidor no responde o corta, reintenta cada 3 segundos.
( while true; do
    srt-live-transmit "${UDP}?mode=listener" \
      "$SRT_DEST" 2>&1 | sed -u 's/^/[srt] /'
    if [[ "$MODE" == caller ]]; then sleep 3; else sleep 1; fi
  done ) &

# 2) Encoder: si una camara se cae y ffmpeg sale, reintenta sin tumbar el SRT.
#    - anullsrc: pista de audio muda (muchos transcoders exigen audio). Es infinita, por
#      eso -shortest: sin el, ffmpeg seguia vivo cuando el video terminaba.
#    - cabeceras repetidas en cada keyframe: un cliente que entra a mitad de stream decodifica enseguida
#    - vigilancia: si ffmpeg deja de producir video por STALL_SECS (sigue vivo pero
#      trabado), se lo detiene para que el ciclo lo vuelva a lanzar.
STALL_SECS="${STALL_SECS:-20}"
PROGRESS="${TMPDIR:-/tmp}/orbi360-mosaico-${UDP_PORT}.progress"
( while true; do
    rm -f "$PROGRESS"
    "$FFMPEG" -hide_banner -loglevel warning -nostdin -progress "$PROGRESS" "${HW[@]}" \
      "${INPUTS[@]}" \
      -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
      -filter_complex "$FILTER" -map "[v]" -map "${N}:a" -shortest \
      "${VIDEO[@]}" \
      -c:a aac -b:a 64k -ac 2 \
      -f mpegts "${UDP}?pkt_size=1316" 2> >(sed -u 's/^/[enc] /' >&2) &
    ENC_PID=$!
    while kill -0 "$ENC_PID" 2>/dev/null; do
      sleep 5
      if [[ -f "$PROGRESS" ]] && (( $(date +%s) - $(stat -c %Y "$PROGRESS") > STALL_SECS )); then
        echo "[enc] sin video hace mas de ${STALL_SECS}s, reinicio el encoder"
        kill "$ENC_PID" 2>/dev/null; sleep 3; kill -9 "$ENC_PID" 2>/dev/null
      fi
    done
    wait "$ENC_PID"
    echo "[enc] ffmpeg salio, reintento en 2s"; sleep 2
  done ) &

wait
