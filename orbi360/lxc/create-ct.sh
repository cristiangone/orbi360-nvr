#!/bin/bash
# ============================================================================
#  create-ct.sh: crea el contenedor LXC de Orbi360 NVR en Proxmox
#
#  Se ejecuta en la consola del NODO Proxmox (no dentro de un contenedor):
#    bash -c "$(wget -qO- https://raw.githubusercontent.com/cristiangone/orbi360-nvr/orbi360/orbi360/lxc/create-ct.sh)"
#
#  Las variables se pueden sobreescribir al llamarlo, por ejemplo:
#    CTID=241 IP=192.168.1.241/24 GW=192.168.1.254 MEDIA_SIZE=55 bash create-ct.sh
# ============================================================================
set -euo pipefail

CTID="${CTID:-241}"
HOSTNAME_CT="${HOSTNAME_CT:-orbi360-nvr}"
CORES="${CORES:-4}"
MEMORY="${MEMORY:-8192}"            # MB
SWAP="${SWAP:-1024}"                # MB
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-192.168.1.241/24}"
GW="${GW:-192.168.1.254}"
STORAGE="${STORAGE:-local-lvm}"     # donde van el disco del sistema y el de grabaciones
ROOTFS_SIZE="${ROOTFS_SIZE:-32}"    # GB: sistema, Python, modelos
MEDIA_SIZE="${MEDIA_SIZE:-55}"      # GB: grabaciones y snapshots (/media/frigate)

if ! command -v pct >/dev/null; then
  echo "Este script se ejecuta en el nodo Proxmox (no se encontro 'pct')." >&2
  exit 1
fi

if pct status "$CTID" >/dev/null 2>&1; then
  echo "Ya existe un contenedor con ID $CTID. Usa otro CTID=..." >&2
  exit 1
fi

echo "==> Buscando la plantilla Debian 12..."
pveam update >/dev/null
TEMPLATE="$(pveam available --section system | awk '/debian-12-standard/ {print $2}' | sort -V | tail -1)"
if [[ -z "$TEMPLATE" ]]; then
  echo "No se encontro la plantilla debian-12-standard en 'pveam available'." >&2
  exit 1
fi
if ! pveam list local | grep -q "$TEMPLATE"; then
  echo "==> Descargando $TEMPLATE..."
  pveam download local "$TEMPLATE"
fi

echo "==> Creando CT $CTID ($HOSTNAME_CT) en $IP..."
pct create "$CTID" "local:vztmpl/$TEMPLATE" \
  --hostname "$HOSTNAME_CT" \
  --cores "$CORES" \
  --memory "$MEMORY" \
  --swap "$SWAP" \
  --rootfs "$STORAGE:$ROOTFS_SIZE" \
  --mp0 "$STORAGE:$MEDIA_SIZE,mp=/media/frigate,backup=0" \
  --net0 "name=eth0,bridge=$BRIDGE,ip=$IP,gw=$GW" \
  --features nesting=1 \
  --unprivileged 1 \
  --onboot 1 \
  --timezone host \
  --ostype debian

# Si el host tiene GPU Intel (iGPU), se la pasamos al CT para decodificar video por hardware
if [[ -e /dev/dri/renderD128 ]]; then
  echo "==> Se detecto /dev/dri/renderD128: pasando la iGPU al CT"
  pct set "$CTID" --dev0 /dev/dri/renderD128,gid=104
fi

pct start "$CTID"
echo
echo "Listo. Ahora establece la contrasena de root del CT y entra a el:"
echo "  pct exec $CTID -- passwd"
echo "  pct enter $CTID"
