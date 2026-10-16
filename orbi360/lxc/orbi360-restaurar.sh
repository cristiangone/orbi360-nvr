#!/bin/bash
# ============================================================================
#  orbi360-restaurar: carga en este NVR un respaldo hecho con orbi360-respaldo.
#
#    orbi360-restaurar <respaldo.tar.gz> [--sin-mosaicos]
#
#  --sin-mosaicos: los mosaicos quedan configurados pero detenidos. Usalo
#  mientras el equipo anterior siga transmitiendo: dos emisores al mismo canal
#  SRT se pisan. Despues se activan en Ajustes > Mosaico SRT.
#
#  Antes de sobrescribir guarda lo que habia en /root/orbi360-antes-de-restaurar-*.
# ============================================================================
set -euo pipefail

FILE="${1:-}"
NO_MOSAICS=0
[[ "${2:-}" == "--sin-mosaicos" ]] && NO_MOSAICS=1
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "Uso: orbi360-restaurar <respaldo.tar.gz> [--sin-mosaicos]" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
umask 077
tar xzf "$FILE" -C "$TMP"
if [[ ! -f "$TMP/RESPALDO_ORBI360" || ! -f "$TMP/config/config.yml" ]]; then
  echo "$FILE no es un respaldo de Orbi360 (orbi360-respaldo)." >&2
  exit 1
fi

echo "==> Deteniendo los mosaicos y el NVR"
systemctl stop 'orbi360-mosaico@*.service' 2>/dev/null || true
systemctl stop orbi360-nvr orbi360-go2rtc

BEFORE="/root/orbi360-antes-de-restaurar-$(date +%Y%m%d-%H%M).tar.gz"
tar czf "$BEFORE" -C / --ignore-failed-read \
  config/config.yml config/orbi360 config/frigate.db etc/orbi360-nvr.env 2>/dev/null || true
chmod 600 "$BEFORE"
echo "    Lo anterior quedo en $BEFORE"

echo "==> Restaurando configuracion"
cp -a "$TMP/config/config.yml" /config/config.yml
if [[ -d "$TMP/config/orbi360" ]]; then
  rm -rf /config/orbi360
  cp -a "$TMP/config/orbi360" /config/orbi360
fi
# Variables: se conservan las que genera el instalador y se reemplazan las FRIGATE_*
if [[ -f "$TMP/etc/frigate-vars.env" ]]; then
  { grep -v '^FRIGATE_' /etc/orbi360-nvr.env || true; cat "$TMP/etc/frigate-vars.env"; } > /etc/orbi360-nvr.env.new
  install -m 600 /etc/orbi360-nvr.env.new /etc/orbi360-nvr.env
  rm -f /etc/orbi360-nvr.env.new
fi
if [[ -f "$TMP/config/frigate.db" ]]; then
  rm -f /config/frigate.db-wal /config/frigate.db-shm
  cp -a "$TMP/config/frigate.db" /config/frigate.db
fi

cd /opt/frigate
if (( NO_MOSAICS )) && [[ -f /config/orbi360/mosaics.json ]]; then
  echo "==> Mosaicos: configurados pero detenidos (--sin-mosaicos)"
  python3 - <<'EOF'
from frigate.orbi360 import mosaics
lst = mosaics.load()
for m in lst.mosaics:
    m.enabled = False
mosaics.save(lst)
EOF
fi
python3 -m frigate.orbi360.mosaics apply || echo "Aviso: no se pudieron aplicar los mosaicos"

echo "==> Arrancando el NVR"
systemctl start orbi360-go2rtc orbi360-nvr
echo
echo "Listo. En 1-2 minutos el NVR queda con las camaras, los mosaicos y los ajustes del respaldo."
echo "Las grabaciones del equipo anterior no se copian: los eventos antiguos pueden mostrarse sin video."
