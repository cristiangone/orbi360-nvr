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
ID="$(basename "$CONF" .conf)"
NAME="${NAME:-$ID}"
# Estado en vivo que lee la interfaz (Ajustes > Mosaico SRT): <id>.srt, <id>.enc y
# <id>.cams, con una linea "estado desde [reinicios | camaras sin senal]"
STATE_DIR="${STATE_DIR:-/run/orbi360-mosaico}"
# Avisos por Telegram: archivo generado por la interfaz (TELEGRAM_*, ALERT_AFTER)
NOTIFY_ENV="${NOTIFY_ENV:-/config/orbi360/telegram.env}"
FLAP_LIMIT="${FLAP_LIMIT:-5}"   # reinicios del encoder en una hora que generan aviso

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
# Salida pareja: ffmpeg reparte los paquetes en el tiempo (bitrate/burst_bits de la salida
# UDP) en vez de soltar cada cuadro de golpe. Las rafagas de los keyframes superaban por
# un instante la subida y se perdian paquetes (11 % recuperado por SRT con 2500 ms).
# El ritmo queda 30 % sobre el bitrate (audio, MPEG-TS y margen) para no atrasarse nunca.
PACE_KBPS="${PACE_KBPS:-$(( BITRATE * 13 / 10 + 150 ))}"
UDP_OUT="${UDP}?pkt_size=1316&bitrate=$(( PACE_KBPS * 1000 ))&burst_bits=$(( 1316 * 8 * 4 ))"
# Buffer del encoder de 1 s: cuadros de tamano mas parejo que con 2 s
BUFSIZE="${BUFSIZE:-$BITRATE}"
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

# Streams de go2rtc de cada cuadro
STREAMS=()
for cam in "${CAMS[@]}"; do
  [[ "$SOURCE" == sub ]] && cam="${cam}_sub"
  STREAMS+=("$cam")
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

# Camara caida: su cuadro se reemplaza por uno gris con "SIN SENAL" y las demas siguen
# transmitiendo. El texto necesita el filtro drawtext y una fuente; si no estan, el
# cuadro queda gris sin texto.
FFPROBE="${FFPROBE:-$(dirname "$FFMPEG")/ffprobe}"
FONT="${FONT:-/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf}"
DRAWTEXT=0
if [[ -f "$FONT" ]] && "$FFMPEG" -hide_banner -filters 2>/dev/null | grep -q ' drawtext '; then
  DRAWTEXT=1
fi

# 0 si go2rtc entrega video de ese stream (es decir, la camara responde)
stream_alive() {
  timeout 15 "$FFPROBE" -v error -rtsp_transport tcp -timeout 8000000 -select_streams v:0 \
    -show_entries stream=codec_type -of csv=p=0 "${RTSP_BASE}/$1" 2>/dev/null | grep -q video
}

# Arma INPUTS y FILTER segun ALIVE (1/0 por cuadro).
#  - timeout: si la camara deja de mandar datos 10 s, ffmpeg falla y se reintenta.
#  - use_wallclock_as_timestamps: cuando go2rtc se reconecta a la camara, los tiempos
#    RTP vuelven a cero; con los de la camara ffmpeg descartaba los cuadros nuevos y
#    repetia el ultimo para siempre (imagen congelada con el servicio "activo").
#  - setpts=PTS-STARTPTS: camaras y cuadros "sin senal" parten de 0 dentro del filtro, y
#    la salida se desplaza con -output_ts_offset a la hora del sistema al arrancar. Asi,
#    tras reiniciar el encoder el tiempo de la senal sigue avanzando: si volviera a cero,
#    el transcoder que la toma veria el tiempo retroceder y entregaria video gris.
#    (Con -copyts y la hora del sistema dentro del filtro, ffmpeg 8 desincroniza xstack
#    y llega a generar cuadros repetidos a toda velocidad.)
build_pipeline() {
  local i label tiles="" positions=()
  INPUTS=(); LAYOUT=""
  for (( i = 0; i < N; i++ )); do
    if (( ALIVE[i] )); then
      INPUTS+=(-rtsp_transport tcp -timeout 10000000 -use_wallclock_as_timestamps 1
               -thread_queue_size 1024 -fflags +discardcorrupt+genpts -i "${RTSP_BASE}/${STREAMS[i]}")
      LAYOUT+="[${i}:v]setpts=PTS-STARTPTS,scale=${TW}:${TH}:force_original_aspect_ratio=decrease,"
      LAYOUT+="pad=${TW}:${TH}:(ow-iw)/2:(oh-ih)/2,setsar=1[t${i}];"
    else
      INPUTS+=(-re -f lavfi -i "color=c=0x262626:s=${TW}x${TH}:r=${FPS}")
      LAYOUT+="[${i}:v]setpts=PTS-STARTPTS,setsar=1"
      if (( DRAWTEXT )); then
        label="${STREAMS[i]%_sub}"
        LAYOUT+=",drawtext=fontfile=${FONT}:text='${label^^}':fontcolor=white@0.6"
        LAYOUT+=":fontsize=$(( TH / 16 )):x=(w-text_w)/2:y=h/2-text_h*1.6"
        LAYOUT+=",drawtext=fontfile=${FONT}:text='SIN SEÑAL':fontcolor=white"
        LAYOUT+=":fontsize=$(( TH / 9 )):x=(w-text_w)/2:y=(h-text_h)/2+text_h*0.4"
      fi
      LAYOUT+="[t${i}];"
    fi
    tiles+="[t${i}]"
    positions+=("$(( i % COLS * TW ))_$(( i / COLS * TH ))")
  done
  if (( N == 1 )); then
    LAYOUT+="[t0]null"
  else
    # shortest=1: si una camara se corta, termina y se rearma con su cuadro "sin senal"
    LAYOUT+="${tiles}xstack=inputs=${N}:layout=$(IFS='|'; echo "${positions[*]}"):fill=black:shortest=1"
  fi
  # completa el lienzo si la division no fue exacta y fija los fps de salida
  LAYOUT+=",pad=${OUT_W}:${OUT_H}:(ow-iw)/2:(oh-ih)/2,fps=${FPS}"
  if [[ "$ENCODER" == vaapi ]]; then
    FILTER="${LAYOUT},format=nv12,hwupload[v]"
  else
    FILTER="${LAYOUT},format=yuv420p[v]"
  fi
}

if [[ "$ENCODER" == vaapi ]]; then
  # Codificacion por hardware en la iGPU Intel: casi no usa CPU
  HW=(-vaapi_device "$VAAPI_DEVICE")
  # -rc_mode CBR: sin esto h264_vaapi puede elegir calidad constante e ignorar el bitrate
  VIDEO=(-c:v h264_vaapi -rc_mode CBR -b:v "${BITRATE}k" -maxrate "${BITRATE}k" -bufsize "${BUFSIZE}k"
         -g "$GOP" -bf 0 -aud 1)
else
  HW=()
  VIDEO=(-c:v libx264 -preset veryfast -g "$GOP" -keyint_min "$GOP" -sc_threshold 0
         -x264opts repeat-headers=1:aud=1
         -b:v "${BITRATE}k" -maxrate "${BITRATE}k" -bufsize "${BUFSIZE}k")
fi

echo "[mosaico] Camaras ($N, grilla ${COLS}x${ROWS}): ${CAMS[*]} | ${OUT_W}x${OUT_H} | encoder: $ENCODER | ${BITRATE}k @ ${FPS} fps"
CIFRADO="$([[ -n "$SRT_PASSPHRASE" ]] && echo " (cifrado AES-128 con contrasena)")"
if [[ "$MODE" == caller ]]; then
  echo "[mosaico] Enviando a srt://${TARGET_HOST}:${TARGET_PORT}${STREAM_ID:+ stream ID ${STREAM_ID}}${CIFRADO}"
else
  echo "[mosaico] Publicando en srt://<IP>:${SRT_PORT}?mode=caller&latency=${SRT_LATENCY}${CIFRADO}"
fi

mkdir -p "$STATE_DIR"
# al detener el servicio, termina todos los procesos y borra su estado
# (se desarma primero: "kill 0" tambien le llega a este shell y lo volveria a disparar)
trap 'trap - TERM INT EXIT; rm -f "$STATE_DIR/$ID".*; kill 0' TERM INT EXIT

# Escribe "<estado> <desde>[ <extra>]" en <id>.<tipo>; "desde" solo cambia con el estado
set_state() {
  local file="$STATE_DIR/$ID.$1" state="$2" extra="${3:-}" since old old_since
  since="$(date +%s)"
  if [[ -f "$file" ]]; then
    read -r old old_since _ < "$file"
    [[ "$old" == "$state" ]] && since="$old_since"
  fi
  echo "$state $since${extra:+ $extra}" > "$file.tmp" && mv -f "$file.tmp" "$file"
}

# 1) Relay SRT persistente, independiente del encoder:
#    - listener: si el cliente se desconecta, vuelve a esperar. Un cliente a la vez; lo normal
#      es que lo tome un transcoder y ese reparta.
#    - caller: si el servidor no responde o corta, reintenta cada 3 segundos.
#    Con -v srt-live-transmit informa la conexion; de ahi sale el estado real.
if [[ "$MODE" == caller ]]; then IDLE=connecting; else IDLE=waiting; fi
( while true; do
    set_state srt "$IDLE"
    srt-live-transmit -v "${UDP}?mode=listener" "$SRT_DEST" 2>&1 |
      while IFS= read -r line; do
        case "$line" in
          *"SRT target connected"*|*"Accepted SRT target connection"*)
            set_state srt connected; echo "[srt] conectado" ;;
          *"SRT target disconnected"*)
            set_state srt "$IDLE"; echo "[srt] desconectado" ;;
          # ruido de -v y estadisticas periodicas
          *"bytes lost"*|*"SRT parameters"*|*"Media path"*|*"Opening SRT"*|*"Connecting to"*|\
          *"SrtCommon"*|*"Binding a server"*|*"listen..."*|*"accept..."*|*"connected."*|*" = '"*|"") ;;
          *) echo "[srt] $line" ;;
        esac
      done
    if [[ "$MODE" == caller ]]; then sleep 3; else sleep 1; fi
  done ) &

# 2) Encoder: si una camara se cae y ffmpeg sale, reintenta sin tumbar el SRT.
#    - anullsrc: pista de audio muda (muchos transcoders exigen audio). Es infinita, por
#      eso -shortest: sin el, ffmpeg seguia vivo cuando el video terminaba.
#    - cabeceras repetidas en cada keyframe: un cliente que entra a mitad de stream decodifica enseguida
#    - vigilancia: si ffmpeg deja de producir video por STALL_SECS (sigue vivo pero
#      trabado), se lo detiene para que el ciclo lo vuelva a lanzar.
STALL_SECS="${STALL_SECS:-20}"
REJOIN_EVERY="${REJOIN_EVERY:-30}"   # cada cuantos segundos se prueba si volvio una camara caida
PROGRESS="${TMPDIR:-/tmp}/orbi360-mosaico-${UDP_PORT}.progress"
RESTARTS_LOG="$STATE_DIR/$ID.restarts"
( restarts=0
  while true; do
    # Que camaras responden. Las caidas van como cuadro "sin senal"
    # (en paralelo: una camara caida tarda hasta el timeout y no debe demorar a las demas)
    ALIVE=(); missing=(); probes=()
    for (( i = 0; i < N; i++ )); do
      ( stream_alive "${STREAMS[i]}" && echo 1 || echo 0 ) > "$STATE_DIR/$ID.probe$i" &
      probes+=($!)
    done
    wait "${probes[@]}"
    for (( i = 0; i < N; i++ )); do
      read -r ALIVE[i] < "$STATE_DIR/$ID.probe$i" || ALIVE[i]=0
      rm -f "$STATE_DIR/$ID.probe$i"
      (( ALIVE[i] )) || missing+=("${STREAMS[i]}")
    done
    if (( ${#missing[@]} )); then
      echo "[enc] sin senal: ${missing[*]}"
      set_state cams missing "$(IFS=,; echo "${missing[*]}")"
    else
      set_state cams ok
    fi
    build_pipeline

    rm -f "$PROGRESS"
    set_state enc starting "$restarts"
    "$FFMPEG" -hide_banner -loglevel warning -nostdin -progress "$PROGRESS" "${HW[@]}" \
      "${INPUTS[@]}" \
      -re -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
      -filter_complex "$FILTER" -map "[v]" -map "${N}:a" -shortest \
      "${VIDEO[@]}" \
      -c:a aac -b:a 64k -ac 2 -output_ts_offset "$(date +%s.%N)" \
      -f mpegts "$UDP_OUT" 2> >(sed -u 's/^/[enc] /' >&2) &
    ENC_PID=$!
    rejoin=0; next_check=$(( $(date +%s) + REJOIN_EVERY ))
    prev_size=-1; flood=0
    while kill -0 "$ENC_PID" 2>/dev/null; do
      sleep 1
      [[ -f "$PROGRESS" ]] || continue
      # Seguro contra torrentes: si la salida supera 4 veces el bitrate configurado
      # durante 5 s seguidos (p. ej. cuadros repetidos a toda velocidad), se reinicia
      # el encoder antes de saturar la subida y el servidor
      size=$(tail -c 4000 "$PROGRESS" | sed -n 's/^total_size=\([0-9]\+\)$/\1/p' | tail -1)
      if [[ -n "$size" ]] && (( prev_size >= 0 )); then
        if (( (size - prev_size) * 8 / 1000 > BITRATE * 4 + 500 )); then
          flood=$((flood + 1))
        else
          flood=0
        fi
        if (( flood >= 5 )); then
          echo "[enc] salida anormal: $(( (size - prev_size) * 8 / 1000 )) kbit/s (config ${BITRATE}), reinicio el encoder"
          set_state enc stalled "$restarts"
          kill "$ENC_PID" 2>/dev/null; sleep 1; kill -9 "$ENC_PID" 2>/dev/null
          break
        fi
      fi
      [[ -n "$size" ]] && prev_size=$size
      age=$(( $(date +%s) - $(stat -c %Y "$PROGRESS") ))
      if (( age > STALL_SECS )); then
        echo "[enc] sin video hace mas de ${STALL_SECS}s, reinicio el encoder"
        set_state enc stalled "$restarts"
        kill "$ENC_PID" 2>/dev/null; sleep 1; kill -9 "$ENC_PID" 2>/dev/null
        break
      elif (( age <= 10 )); then
        set_state enc ok "$restarts"
      fi
      # Camara que vuelve: se rearma el mosaico para incluirla
      if (( ${#missing[@]} && $(date +%s) >= next_check )); then
        for stream in "${missing[@]}"; do
          if stream_alive "$stream"; then
            echo "[enc] volvio la senal de $stream, rearmo el mosaico"
            rejoin=1
          fi
        done
        if (( rejoin )); then
          kill "$ENC_PID" 2>/dev/null; sleep 1; kill -9 "$ENC_PID" 2>/dev/null
          break
        fi
        next_check=$(( $(date +%s) + REJOIN_EVERY ))
      fi
    done
    wait "$ENC_PID" 2>/dev/null
    if (( rejoin )); then
      continue
    fi
    restarts=$((restarts + 1))
    date +%s >> "$RESTARTS_LOG"
    set_state enc restarting "$restarts"
    echo "[enc] ffmpeg salio, reintento"; sleep 1
  done ) &

# 3) Avisos por Telegram. Solo se avisa si el problema dura ALERT_AFTER segundos
#    (por defecto 60), para no mandar mensajes por cortes de unos segundos, y se
#    avisa de nuevo cuando se recupera.
# Devuelve 0 solo si el mensaje salio: con los avisos apagados o sin conexion a
# Telegram, el problema sigue pendiente y se avisa cuando se pueda.
notify() {
  [[ -f "$NOTIFY_ENV" ]] || return 1
  ( # shellcheck source=/dev/null
    source "$NOTIFY_ENV"
    [[ "${TELEGRAM_ENABLED:-0}" == 1 && -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] || exit 1
    # la URL (con el token) va por stdin y no queda a la vista en la lista de procesos
    if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TELEGRAM_BOT_TOKEN" |
        curl -fsS --max-time 15 -K - --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
          --data-urlencode "text=$1" -o /dev/null; then
      echo "[aviso] enviado a Telegram"
    else
      echo "[aviso] no se pudo enviar a Telegram"
      exit 1
    fi )
}

alert_after() {
  local value=60
  [[ -f "$NOTIFY_ENV" ]] && value="$(sed -n 's/^ALERT_AFTER=\([0-9]\+\)$/\1/p' "$NOTIFY_ENV")"
  echo "${value:-60}"
}

( bad_since=0; alerted=0; flap_alerted=0; last_try=0
  TITLE="Orbi360 NVR ($(hostname)) · mosaico «$NAME»"
  while true; do
    sleep 10
    now=$(date +%s)
    read -r enc _ 2>/dev/null < "$STATE_DIR/$ID.enc" || enc=starting
    read -r srt _ 2>/dev/null < "$STATE_DIR/$ID.srt" || srt=unknown
    read -r cams _ lost 2>/dev/null < "$STATE_DIR/$ID.cams" || cams=ok
    problem=""
    if [[ "$enc" != ok ]]; then
      problem="sin video (${STREAMS[*]})"
    elif [[ "$MODE" == caller && "$srt" != connected ]]; then
      problem="sin conexión con el servidor ${TARGET_HOST}:${TARGET_PORT}"
    elif [[ "$cams" == missing ]]; then
      problem="sin señal de ${lost//,/, } (se transmite el resto, con su cuadro en gris)"
    fi

    if [[ -n "$problem" ]]; then
      (( bad_since == 0 )) && bad_since=$now
      # el envio se reintenta cada minuto hasta que salga
      if (( !alerted && now - bad_since >= $(alert_after) && now - last_try >= 60 )); then
        last_try=$now
        if notify "⚠️ $TITLE: $problem desde las $(date -d "@$bad_since" +%H:%M)."; then
          alerted=1
        fi
      fi
    else
      if (( alerted )); then
        notify "✅ $TITLE: recuperado, estuvo con problemas $(( (now - bad_since + 59) / 60 )) min."
      fi
      bad_since=0; alerted=0; last_try=0
    fi

    # Reinicios frecuentes: senal de una camara o red inestable aunque se recupere sola
    if [[ -f "$RESTARTS_LOG" ]]; then
      awk -v from=$((now - 3600)) '$1 >= from' "$RESTARTS_LOG" > "$RESTARTS_LOG.tmp" &&
        mv -f "$RESTARTS_LOG.tmp" "$RESTARTS_LOG"
      count=$(wc -l < "$RESTARTS_LOG")
      if (( count >= FLAP_LIMIT && now - flap_alerted >= 3600 )); then
        notify "🔁 $TITLE: el video se reinició $count veces en la última hora. Revisar la cámara o la red." &&
          flap_alerted=$now
      fi
    fi
  done ) &

wait
