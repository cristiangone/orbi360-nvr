#!/bin/bash
# ============================================================================
#  orbi360-respaldo: guarda la configuracion de este NVR para restaurarla en
#  otro equipo con orbi360-restaurar (por ejemplo al cambiar de mini PC).
#
#  Incluye: config.yml, /config/orbi360 (mosaicos, Telegram, red de camaras),
#  las variables FRIGATE_* (clave de las camaras) y la base de datos (usuarios,
#  eventos, ajustes). No incluye las grabaciones.
#
#    orbi360-respaldo [archivo.tar.gz]
# ============================================================================
set -euo pipefail

OUT="${1:-/root/orbi360-respaldo-$(hostname)-$(date +%Y%m%d-%H%M).tar.gz}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
umask 077

mkdir -p "$TMP/config" "$TMP/etc"
cp -a /config/config.yml "$TMP/config/"
if [[ -d /config/orbi360 ]]; then
  cp -a /config/orbi360 "$TMP/config/"
fi
grep '^FRIGATE_' /etc/orbi360-nvr.env > "$TMP/etc/frigate-vars.env" || true

# Copia consistente de la base de datos aunque el NVR siga grabando
if [[ -f /config/frigate.db ]]; then
  python3 - "$TMP/config/frigate.db" <<'EOF'
import sqlite3, sys
src = sqlite3.connect("file:/config/frigate.db?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[1])
src.backup(dst)
dst.close()
src.close()
EOF
fi

date -Is > "$TMP/RESPALDO_ORBI360"
tar czf "$OUT" -C "$TMP" .
chmod 600 "$OUT"
echo "Respaldo listo: $OUT ($(du -h "$OUT" | cut -f1))"
echo "Contiene la clave de las camaras y el token de Telegram: guardalo en un lugar seguro."
