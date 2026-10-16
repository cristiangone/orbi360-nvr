#!/bin/bash
# ============================================================================
#  create-ct.sh: crea el contenedor LXC de Orbi360 NVR en Proxmox
#
#  Se ejecuta en la consola del NODO Proxmox (no dentro de un contenedor):
#    bash -c "$(wget -qO- https://raw.githubusercontent.com/cristiangone/orbi360-nvr/orbi360/orbi360/lxc/create-ct.sh)"
#
#  Las variables se pueden sobreescribir al llamarlo, por ejemplo:
#    CTID=241 IP=192.168.1.241/24 GW=192.168.1.254 MEDIA_SIZE=55 bash create-ct.sh
#
#  Sin MEMORY, CPULIMIT ni MEDIA_SIZE se ajusta al equipo: toda la CPU, la RAM
#  menos 4 GB para Proxmox, y ~75 % del espacio libre del storage para grabaciones
#  (pensado para un equipo dedicado, p. ej. un mini PC N150 de 16 GB / 512 GB).
# ============================================================================
set -euo pipefail

CTID="${CTID:-241}"
HOSTNAME_CT="${HOSTNAME_CT:-orbi360-nvr}"
# Limite de CPU por tiempo de uso (cpulimit) y no por cantidad de nucleos (cores): con
# "cores" Proxmox entrega hilos sueltos (p. ej. 0,2,4,7) y OpenVINO corrompe memoria
# al leer esa topologia incompleta. Asi el CT ve todos los hilos del host.
CPULIMIT="${CPULIMIT:-auto}"        # auto: todos los hilos del equipo
MEMORY="${MEMORY:-auto}"            # MB; auto: RAM del equipo menos 4 GB
SWAP="${SWAP:-1024}"                # MB
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-192.168.1.241/24}"
GW="${GW:-192.168.1.254}"
# DNS propios: si el nodo usa Tailscale MagicDNS (100.100.100.100), el CT lo heredaria
# y no podria resolver nombres, porque no corre Tailscale
NAMESERVER="${NAMESERVER:-1.1.1.1 8.8.8.8}"
STORAGE="${STORAGE:-local-lvm}"     # donde van el disco del sistema y el de grabaciones
ROOTFS_SIZE="${ROOTFS_SIZE:-32}"    # GB: sistema, Python, modelos
MEDIA_SIZE="${MEDIA_SIZE:-auto}"    # GB: grabaciones y snapshots (/media/frigate)

if ! command -v pct >/dev/null; then
  echo "Este script se ejecuta en el nodo Proxmox (no se encontro 'pct')." >&2
  exit 1
fi

# Tamanos automaticos segun el equipo
if [[ "$CPULIMIT" == auto ]]; then
  CPULIMIT="$(nproc)"
fi
if [[ "$MEMORY" == auto ]]; then
  total_mb=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 ))
  MEMORY=$(( total_mb - 4096 ))
  (( MEMORY < 4096 )) && MEMORY=4096
fi
if [[ "$MEDIA_SIZE" == auto ]]; then
  # pvesm status: Name Type Status Total Used Available % (en KiB)
  avail_gb=$(pvesm status --storage "$STORAGE" 2>/dev/null | awk 'NR==2 {print int($6/1024/1024)}')
  MEDIA_SIZE=$(( ${avail_gb:-0} * 3 / 4 - ROOTFS_SIZE ))
  if (( MEDIA_SIZE < 20 )); then
    echo "Poco espacio libre en $STORAGE (${avail_gb:-?} GB). Indica MEDIA_SIZE=..." >&2
    exit 1
  fi
fi
echo "==> CT $CTID: ${CPULIMIT} hilos, ${MEMORY} MB de RAM, ${ROOTFS_SIZE} GB sistema, ${MEDIA_SIZE} GB grabaciones"

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
  --cpulimit "$CPULIMIT" \
  --memory "$MEMORY" \
  --swap "$SWAP" \
  --rootfs "$STORAGE:$ROOTFS_SIZE" \
  --mp0 "$STORAGE:$MEDIA_SIZE,mp=/media/frigate,backup=0" \
  --net0 "name=eth0,bridge=$BRIDGE,ip=$IP,gw=$GW" \
  --nameserver "$NAMESERVER" \
  --searchdomain local \
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
