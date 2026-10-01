#!/bin/bash
# ============================================================================
#  install.sh: instala (o actualiza) Orbi360 NVR sin Docker en un LXC Debian 12
#
#  Se ejecuta DENTRO del contenedor, como root:
#    bash -c "$(wget -qO- https://raw.githubusercontent.com/cristiangone/orbi360-nvr/orbi360/orbi360/lxc/install.sh)"
#
#  Para actualizar a la ultima version de la rama, se vuelve a ejecutar el mismo
#  comando. Los pasos pesados (compilar nginx, modelos, etc.) solo se repiten
#  si cambiaron; FORCE=1 obliga a rehacer todo.
#
#  Replica la receta de docker/main/Dockerfile: mismas rutas (/opt/frigate,
#  /config, /media/frigate) para no divergir del proyecto original, pero los
#  servicios de s6-overlay se reemplazan por unidades de systemd.
# ============================================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/cristiangone/orbi360-nvr.git}"
BRANCH="${BRANCH:-orbi360}"
SRC=/opt/orbi360-src
STAMPS=/var/lib/orbi360-install
NODE_MAJOR=22

export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8
export TARGETARCH=amd64
export PIP_BREAK_SYSTEM_PACKAGES=1   # contenedor dedicado: paquetes de Python a nivel sistema, igual que la imagen Docker
export PIP_ROOT_USER_ACTION=ignore

LOG=/var/log/orbi360-install.log
exec > >(tee -a "$LOG") 2>&1

msg() { echo -e "\n\033[1;36m==> $*\033[0m"; }
die() { echo -e "\n\033[1;31mERROR: $*\033[0m" >&2; exit 1; }

# Ejecuta un paso solo si no se hizo antes con la misma "llave"
step() {
  local name="$1" key="$2"; shift 2
  local stamp="$STAMPS/$name"
  if [[ "${FORCE:-0}" != 1 && -f "$stamp" && "$(cat "$stamp")" == "$key" ]]; then
    echo "--- $name: ya hecho, se omite"
    return 0
  fi
  msg "$name"
  "$@"
  echo "$key" > "$stamp"
}

# Ejecuta un script del repo en un directorio temporal limpio (los scripts descargan al cwd)
run_in_tmp() {
  local dir; dir="$(mktemp -d)"
  (cd "$dir" && bash "$@")
  rm -rf "$dir"
}

file_hash() { cat "$@" | sha256sum | cut -c1-16; }

# ---------------------------------------------------------------------------
[[ $EUID -eq 0 ]] || die "Ejecutar como root"
[[ "$(dpkg --print-architecture)" == "amd64" ]] || die "Solo se soporta amd64"
source /etc/os-release
[[ "$VERSION_ID" == "12" ]] || die "Se requiere Debian 12 (bookworm); este sistema es $PRETTY_NAME"
mkdir -p "$STAMPS"

# Los scripts de Frigate editan /etc/apt/sources.list.d/debian.sources (formato deb822),
# pero la plantilla de Proxmox usa el viejo /etc/apt/sources.list.
reset_apt_sources() {
  cat > /etc/apt/sources.list.d/debian.sources <<'EOF'
Types: deb
URIs: http://deb.debian.org/debian
Suites: bookworm bookworm-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: bookworm-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
  if [[ -s /etc/apt/sources.list ]]; then
    mv /etc/apt/sources.list /etc/apt/sources.list.orbi360-bak
  fi
}

# ---------------------------------------------------------------------------
msg "Preparando sistema base"
reset_apt_sources
apt-get -qq update
apt-get -qq install -y --no-install-recommends \
  git ca-certificates curl wget gnupg xz-utils unzip rsync jq procps \
  build-essential pkg-config cmake gfortran \
  python3.11 python3.11-dev python3.11-venv \
  libopenblas-dev liblapack-dev libssl-dev libsqlite3-dev tclsh openssl

msg "Descargando codigo de $REPO_URL ($BRANCH)"
if [[ -d "$SRC/.git" ]]; then
  git -C "$SRC" fetch --depth 1 origin "$BRANCH"
  git -C "$SRC" reset --hard FETCH_HEAD
else
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC"
fi
COMMIT="$(git -C "$SRC" rev-parse --short HEAD)"
DOCKER="$SRC/docker/main"
echo "Commit: $COMMIT"

# --- Compilaciones nativas (etapas "nginx" y "sqlite-vec" del Dockerfile) ---
build_nginx() {
  rm -rf /tmp/nginx /tmp/nginx-vod-module /tmp/nginx-secure-token-module /tmp/ngx_devel_kit /tmp/nginx-set-misc-module
  run_in_tmp "$DOCKER/build_nginx.sh"
  rm -rf /tmp/nginx /tmp/nginx-vod-module /tmp/nginx-secure-token-module /tmp/ngx_devel_kit /tmp/nginx-set-misc-module
  reset_apt_sources
}
step nginx "$(file_hash "$DOCKER/build_nginx.sh")" build_nginx

build_sqlite_vec() {
  rm -rf /tmp/sqlite_vec
  run_in_tmp "$DOCKER/build_sqlite_vec.sh"
  rm -rf /tmp/sqlite_vec
  reset_apt_sources
}
step sqlite-vec "$(file_hash "$DOCKER/build_sqlite_vec.sh")" build_sqlite_vec

# --- Dependencias de Python (etapa "wheels") ---
install_python() {
  update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
  wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py
  sed -i 's/args.append("setuptools")/args.append("setuptools==77.0.3")/' /tmp/get-pip.py
  python3 /tmp/get-pip.py "pip"
  rm -f /tmp/get-pip.py
  pip3 install -r "$DOCKER/requirements.txt"
  rm -rf /wheels
  run_in_tmp "$DOCKER/build_pysqlite3.sh"
  pip3 install -r "$DOCKER/requirements-wheels.txt"
  pip3 install -U /wheels/*.whl
  rm -rf /wheels
}
step python "$(file_hash "$DOCKER/requirements.txt" "$DOCKER/requirements-wheels.txt" "$DOCKER/build_pysqlite3.sh")" install_python

# --- Librerias de ejecucion, ffmpeg y drivers (install_deps.sh) ---
install_runtime() {
  run_in_tmp "$DOCKER/install_deps.sh"
  reset_apt_sources
  apt-get -qq update
  apt-get -qq install -y --no-install-recommends gnupg xz-utils
}
step runtime "$(file_hash "$DOCKER/install_deps.sh")" install_runtime

# --- Driver VA-API para iGPU Intel (Gen9 a Gen12, por ejemplo Iris Xe) ---
# La imagen Docker compila intel-media-driver 25.x para soportar Battlemage; para
# iGPUs de 6a a 12a generacion alcanza el paquete non-free de Debian 12.
HAS_IGPU=0
[[ -e /dev/dri/renderD128 ]] && HAS_IGPU=1
install_intel_gpu() {
  sed -i -E "/^Components: main$/s/main/main contrib non-free non-free-firmware/" /etc/apt/sources.list.d/debian.sources
  apt-get -qq update
  apt-get -qq install -y --no-install-recommends intel-media-va-driver-non-free
  reset_apt_sources
  apt-get -qq update
  for grp in render video; do
    getent group "$grp" >/dev/null && usermod -aG "$grp" root
  done
  vainfo --display drm --device /dev/dri/renderD128 2>&1 | head -5 || true
}
if [[ $HAS_IGPU == 1 ]]; then
  step intel-gpu "1" install_intel_gpu
fi

# --- go2rtc y tempio ---
GO2RTC_URL="$(grep -oP 'https://github.com/AlexxIT/go2rtc/releases/download/[^"]+' "$DOCKER/Dockerfile" | head -1)"
GO2RTC_URL="${GO2RTC_URL//\$\{TARGETARCH\}/amd64}"
install_go2rtc() {
  mkdir -p /usr/local/go2rtc/bin
  wget -q -O /usr/local/go2rtc/bin/go2rtc "$GO2RTC_URL"
  chmod 755 /usr/local/go2rtc/bin/go2rtc
}
step go2rtc "$GO2RTC_URL" install_go2rtc

install_tempio() {
  run_in_tmp "$DOCKER/install_tempio.sh"
  mkdir -p /usr/local/tempio
  cp -a /rootfs/usr/local/tempio/. /usr/local/tempio/
  rm -rf /rootfs
}
step tempio "$(file_hash "$DOCKER/install_tempio.sh")" install_tempio

# --- Modelos de deteccion (etapas "ov-converter" y "models") ---
install_models() {
  local work; work="$(mktemp -d)"
  wget -qO /edgetpu_model.tflite https://github.com/google-coral/test_data/raw/release-frogfish/ssdlite_mobiledet_coco_qat_postprocess_edgetpu.tflite
  wget -qO /cpu_model.tflite https://github.com/google-coral/test_data/raw/release-frogfish/ssdlite_mobiledet_coco_qat_postprocess.tflite
  cp "$SRC/labelmap.txt" /labelmap.txt
  cp "$SRC/audio-labelmap.txt" /audio-labelmap.txt

  # Convertir SSDLite MobileNet v2 a OpenVINO IR en un entorno aislado
  python3 -m venv "$work/venv"
  "$work/venv/bin/pip" install -q -r "$DOCKER/requirements-ov.txt"
  rm -rf /models && mkdir /models
  (cd /models \
    && wget -q http://download.tensorflow.org/models/object_detection/ssdlite_mobilenet_v2_coco_2018_05_09.tar.gz \
    && tar -xf ssdlite_mobilenet_v2_coco_2018_05_09.tar.gz \
    && "$work/venv/bin/python" "$DOCKER/build_ov_model.py")
  mkdir -p /openvino-model
  cp /models/ssdlite_mobilenet_v2.xml /models/ssdlite_mobilenet_v2.bin /openvino-model/
  wget -q https://github.com/openvinotoolkit/open_model_zoo/raw/master/data/dataset_classes/coco_91cl_bkgr.txt -O /openvino-model/coco_91cl_bkgr.txt
  sed -i 's/truck/car/g' /openvino-model/coco_91cl_bkgr.txt

  # Modelo de audio
  (cd "$work" \
    && wget -qO - https://www.kaggle.com/api/v1/models/google/yamnet/tfLite/classification-tflite/1/download | tar xz \
    && mv 1.tflite /cpu_audio_model.tflite)
  rm -rf /models "$work"
}
step models "$(file_hash "$DOCKER/build_ov_model.py" "$DOCKER/requirements-ov.txt")" install_models

# --- Node.js para compilar la interfaz web ---
install_node() {
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
  apt-get -qq install -y nodejs
}
step node "$NODE_MAJOR" install_node

# --- Interfaz web (etapa "web-build") ---
build_web() {
  echo "VITE_GIT_COMMIT_HASH=$COMMIT" > "$SRC/web/.env"
  # vite necesita mas memoria que el limite por defecto de Node (~2 GB)
  (cd "$SRC/web" && npm ci --no-audit --no-fund && NODE_OPTIONS=--max-old-space-size=4096 npm run build)
  mv "$SRC/web/dist/BASE_PATH/monacoeditorwork/"* "$SRC/web/dist/assets/"
  rm -rf "$SRC/web/dist/BASE_PATH"
  mkdir -p /opt/frigate/web
  rsync -a --delete "$SRC/web/dist/" /opt/frigate/web/
}
step web "$COMMIT" build_web

# --- Codigo de la aplicacion y archivos de configuracion del sistema ---
msg "Instalando la aplicacion"
VERSION="$(grep -oP '^VERSION = \K.*' "$SRC/Makefile")"
mkdir -p /opt/frigate /config /media/frigate /tmp/cache
rsync -a --delete "$SRC/frigate/" /opt/frigate/frigate/
rsync -a --delete "$SRC/migrations/" /opt/frigate/migrations/
echo "VERSION = \"$VERSION-$COMMIT\"" > /opt/frigate/frigate/version.py
cp -a "$DOCKER/rootfs/." /
ldconfig

# Scripts de arranque: los mismos run de s6-overlay, sin los comandos propios de s6
mkdir -p /usr/local/orbi360/run /usr/local/orbi360/bin
for svc in frigate go2rtc nginx; do
  sed -e '1s|.*|#!/bin/bash|' \
      -e '/s6-svc -O \./d' \
      -e '/s6-notifyoncheck/d' \
      "$DOCKER/rootfs/etc/s6-overlay/s6-rc.d/$svc/run" > "/usr/local/orbi360/run/$svc"
  chmod 755 "/usr/local/orbi360/run/$svc"
done
install -m 755 "$SRC/orbi360/lxc/orbi360-log.py" /usr/local/orbi360/bin/orbi360-log

# Variables de entorno de la imagen Docker
DEFAULT_FFMPEG_VERSION="$(grep -oP 'ENV DEFAULT_FFMPEG_VERSION="\K[^"]+' "$DOCKER/Dockerfile")"
cat > /etc/orbi360-nvr.env <<EOF
PATH=/usr/local/go2rtc/bin:/usr/local/tempio/bin:/usr/local/nginx/sbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LANG=C.UTF-8
DEFAULT_FFMPEG_VERSION=$DEFAULT_FFMPEG_VERSION
INCLUDED_FFMPEG_VERSIONS=$DEFAULT_FFMPEG_VERSION:7.0:5.0
TOKENIZERS_PARALLELISM=true
TRANSFORMERS_NO_ADVISORY_WARNINGS=1
OPENCV_FFMPEG_LOGLEVEL=8
PYTHONWARNINGS=ignore:::numpy.core.getlimits
HAILORT_LOGGER_PATH=NONE
TF_CPP_MIN_LOG_LEVEL=3
TF_CPP_MIN_VLOG_LEVEL=3
TF_ENABLE_ONEDNN_OPTS=0
AUTOGRAPH_VERBOSITY=0
GLOG_minloglevel=3
GLOG_logtostderr=0
EOF

# Config inicial: si no existe, Frigate genera una con OpenVINO en CPU. Con iGPU Intel
# conviene detectar en la GPU y decodificar el video por VA-API.
if [[ $HAS_IGPU == 1 && ! -e /config/config.yml && ! -e /config/config.yaml ]]; then
  CONFIG_VERSION="$(grep -oP 'CURRENT_CONFIG_VERSION = "\K[^"]+' "$SRC/frigate/util/config.py")"
  cat > /config/config.yml <<EOF
mqtt:
  enabled: false

detectors:
  ov:
    type: openvino
    device: GPU

model:
  width: 300
  height: 300
  input_tensor: nhwc
  input_pixel_format: bgr
  path: /openvino-model/ssdlite_mobilenet_v2.xml
  labelmap_path: /openvino-model/coco_91cl_bkgr.txt

ffmpeg:
  hwaccel_args: preset-vaapi

cameras: {}  # Sin camaras: agregarlas desde la interfaz (Configuracion > Camaras)
version: $CONFIG_VERSION
EOF
fi

# Cache de grabaciones en RAM, como el tmpfs que recomienda la documentacion
if ! grep -q " /tmp/cache " /etc/fstab; then
  echo "tmpfs /tmp/cache tmpfs defaults,nofail,size=1g 0 0" >> /etc/fstab
fi
mountpoint -q /tmp/cache || mount /tmp/cache || echo "Aviso: no se pudo montar tmpfs en /tmp/cache, se usara disco"

# --- Servicios systemd (reemplazan a s6-overlay) ---
msg "Configurando servicios"
LOGGER=/usr/local/orbi360/bin/orbi360-log

cat > /etc/systemd/system/orbi360-go2rtc.service <<EOF
[Unit]
Description=Orbi360 NVR - go2rtc (restream de camaras)
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/etc/orbi360-nvr.env
ExecStartPre=/bin/mkdir -p /tmp/cache /config
ExecStart=/bin/bash -c 'exec /usr/local/orbi360/run/go2rtc 2>&1 | $LOGGER go2rtc'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Frigate regenera la config de go2rtc al arrancar, por eso lo reinicia (como el reinicio
# completo del contenedor en Docker). Wants= y no Requires= para no crear un ciclo.
cat > /etc/systemd/system/orbi360-nvr.service <<EOF
[Unit]
Description=Orbi360 NVR
After=network-online.target orbi360-go2rtc.service
Wants=network-online.target orbi360-go2rtc.service

[Service]
EnvironmentFile=/etc/orbi360-nvr.env
ExecStartPre=/bin/rm -f /dev/shm/.frigate-is-stopping
ExecStartPre=/bin/mkdir -p /tmp/cache /config /media/frigate
ExecStartPre=-/bin/systemctl --no-block restart orbi360-go2rtc.service
ExecStart=/bin/bash -c 'exec /usr/local/orbi360/run/frigate 2>&1 | $LOGGER frigate'
Restart=always
RestartSec=5
TimeoutStopSec=60
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/orbi360-nginx.service <<EOF
[Unit]
Description=Orbi360 NVR - nginx (interfaz web y API)
After=network-online.target orbi360-nvr.service
Wants=network-online.target

[Service]
EnvironmentFile=/etc/orbi360-nvr.env
ExecStart=/bin/bash -c 'exec /usr/local/orbi360/run/nginx 2>&1 | $LOGGER nginx'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

if [[ -d /run/systemd/system ]]; then
  systemctl daemon-reload
  systemctl enable orbi360-go2rtc.service orbi360-nvr.service orbi360-nginx.service
  systemctl restart orbi360-go2rtc.service orbi360-nvr.service orbi360-nginx.service
else
  echo "Aviso: systemd no esta activo; los servicios quedaron instalados pero no se iniciaron"
fi

IP_ADDR="$(hostname -I | awk '{print $1}')"
msg "Orbi360 NVR $VERSION-$COMMIT instalado"
cat <<EOF

  Interfaz web:   https://$IP_ADDR:8971   (certificado autofirmado: aceptar la advertencia)

  El primer arranque tarda 1-2 minutos. La contrasena inicial del usuario
  "admin" aparece en el log; para verla:

    grep -A2 -i password /dev/shm/logs/frigate/current

  Comandos utiles:
    systemctl status orbi360-nvr          estado del servicio
    journalctl -u orbi360-nvr -f          log en vivo
    nano /config/config.yml               configuracion

  Log de esta instalacion: $LOG
EOF
