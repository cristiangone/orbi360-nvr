# Instalar Orbi360 NVR en un equipo nuevo

Guía para un mini PC dedicado (probada para el Machenike Mini N TL24: Intel N150,
16 GB, 512 GB, 2 puertos LAN). El equipo lleva **Proxmox VE** como sistema
operativo y Orbi360 NVR dentro de un contenedor (CT), igual que el laboratorio.

> Proxmox VE no se instala sobre Ubuntu: es un sistema operativo completo
> (basado en Debian) que se instala directo en el equipo desde su ISO.

## 0. Antes de empezar

- Un pendrive de 8 GB o más.
- **Un teclado USB y un monitor HDMI** (solo para instalar Proxmox; después todo
  se hace desde el navegador).
- Cable de red al router. El mini PC tiene **dos puertos LAN**: si después de
  instalar no responde, probar el cable en el otro puerto.
- Elegir dos IP libres, por ejemplo `192.168.1.170` para Proxmox y
  `192.168.1.241` para el CT. Comprobar que no respondan: `ping -c2 -W1 192.168.1.170`.

## 1. Instalar Proxmox VE

1. Descargar el ISO de la última versión de **Proxmox VE** (x86-64, no ARM64) desde
   https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso y comprobar
   su SHA256 con el de la página. En Windows:
   `(Get-FileHash .\proxmox-ve_X.Y-Z.iso -Algorithm SHA256).Hash`
2. Grabarlo con **Rufus** en **modo Imagen DD** (o balenaEtcher). Si Rufus da
   “Error de escritura”, limpiar el pendrive con `diskpart` (`list disk`,
   `select disk N` del pendrive, `detail disk` para confirmar que es USB, `clean`)
   y reintentar. Si Windows pide formatearlo después, **no** aceptar.
3. Conectar el pendrive, el teclado, el monitor y la red al mini PC. Encenderlo
   presionando **F7** (o F11 / Supr) y elegir el pendrive.
4. *Install Proxmox VE (Graphical)*:
   - Disco: el SSD, sistema de archivos **ext4** (por defecto).
   - País, zona horaria **America/Santiago** y teclado **Latin American**.
   - Contraseña de root y un correo.
   - Red: **hostname** (ej. `nvr`), IP `192.168.1.170/24`, gateway `192.168.1.254`,
     DNS `1.1.1.1`. Si queda con otra IP, se cambia después:
     `sed -i 's/IP_VIEJA/192.168.1.170/' /etc/network/interfaces /etc/hosts && ifreload -a`
5. Al terminar, retirar el pendrive y abrir `https://192.168.1.170:8006` desde otro
   PC de la misma red (usuario `root`; aceptar la advertencia del certificado).

### Repositorios (sin suscripción) y actualización

Los repositorios *enterprise* exigen suscripción y hacen fallar `apt` (`401
Unauthorized`). En la consola del nodo:

```bash
mv /etc/apt/sources.list.d/pve-enterprise.sources /etc/apt/sources.list.d/ceph.sources /root/
cat > /etc/apt/sources.list.d/pve-no-subscription.sources <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
apt-get update && apt-get -y full-upgrade && reboot
```

`download.proxmox.com` a veces va muy lento: mientras las líneas digan `Get:` se
puede cortar con Ctrl+C y reintentar más tarde.

### Acceso remoto por Tailscale (si el técnico no está en la red del cliente)

En la consola del nodo (se instala sin `|` para escribirlo fácil con el teclado):

```bash
curl -fsSL https://tailscale.com/install.sh -o ts.sh && sh ts.sh
echo net.ipv4.ip_forward=1 > /etc/sysctl.d/99-tailscale.conf && sysctl -p /etc/sysctl.d/99-tailscale.conf
tailscale up --advertise-routes=192.168.1.0/24 --accept-dns=false
```

Abrir el enlace que muestra, iniciar sesión y aprobar la ruta en
login.tailscale.com → *Machines* → el equipo → *Edit route settings*.

> Proxmox VE 9 es Debian 13, que **no lee `/etc/sysctl.conf`**: el reenvío va en
> `/etc/sysctl.d/`. Sin él, por Tailscale se llega al nodo pero no al CT.

## 2. Crear el contenedor de Orbi360

En la **consola del nodo**. Sin `MEMORY`, `CPULIMIT` ni `MEDIA_SIZE` el script se
ajusta al equipo (todos los hilos, la RAM menos 4 GB para Proxmox y ~75 % del
espacio libre para grabaciones) y pasa la iGPU al CT. En el N150 de 16 GB / 512 GB:
4 hilos, 11.667 MB y 228 GB.

```bash
CTID=241 IP=192.168.1.241/24 GW=192.168.1.254 bash -c "$(wget -qO- https://raw.githubusercontent.com/cristiangone/orbi360-nvr/orbi360/orbi360/lxc/create-ct.sh)"
pct exec 241 -- passwd
pct config 241 | grep -E "dev0|memory|cpulimit|mp0"
```

`dev0: /dev/dri/renderD128` confirma que el CT recibió la GPU.

## 3. Instalar Orbi360 NVR

```bash
pct enter 241
bash -c "$(wget -qO- https://raw.githubusercontent.com/cristiangone/orbi360-nvr/orbi360/orbi360/lxc/install.sh)"
```

Tarda 20-40 minutos la primera vez. Instala también los **drivers de GPU de Intel**
recientes (repositorio de Intel para Ubuntu 22.04): los de Debian 12 no reconocen
el N150 y sin ellos la detección no arranca. Al final muestra
`https://192.168.1.241:8971`. Para ver la clave inicial de `admin`:

```bash
grep -A2 -i password /dev/shm/logs/frigate/current
```

Comprobar la GPU dentro del CT:

```bash
python3 -c "import openvino as ov; print(ov.Core().available_devices)"   # ['CPU', 'GPU']
```

Desde aquí, para actualizar basta con `orbi360-actualizar` dentro del CT.

## 4. Configurar desde cero (cliente nuevo)

Todo desde la interfaz `https://IP-del-CT:8971`:

1. **Cambiar la clave de `admin`**: Ajustes → Usuarios.
2. **Clave de las cámaras**: Ajustes → **Red de cámaras** → *Clave de las cámaras*.
   Es la clave con la que Orbi360 entra a todas las cámaras (usuario `admin`). El NVR
   se reinicia al guardarla (1-2 minutos).
3. **Cámaras**: en la misma página, *Escanear ahora*. Las cámaras aparecen en
   *Cámaras nuevas detectadas*; en cada una, **Agregar** → nombre (“Patio”) →
   **Detectar** → **Agregar**. Si una no aparece, *Agregar cámara por IP*.
   - iCSee nuevas (solo DVRIP): si la detección dice que no acepta la clave, en el CT:
     `cd /opt/frigate && python3 -m frigate.orbi360.xmcam passwd <IP>` (clave actual vacía).
     Si son H.265, el diálogo ofrece pasarlas a H.264.
   - Verificar cada cámara por el **nombre sobreimpreso** en la imagen.
4. **Avisos por Telegram**: Ajustes → Mosaico SRT → *Avisos por Telegram* (token del
   bot, ID de chat, *Probar*).
5. **Mosaicos** (si el cliente transmite a la plataforma): Ajustes → Mosaico SRT →
   agregar, elegir cámaras, resolución y destino (*Enviar a*: servidor y puerto SRT).

El equipo ya viene con: detección de personas y autos, grabación de 7 días
(movimiento, alertas y detecciones), localizador de cámaras por MAC cada 3 minutos,
lectura con la hora del NVR y reconexión SRT diaria a las 04:00.

## 5. Validar (primera semana)

En el CT nuevo, con las cámaras funcionando:

```bash
systemctl show orbi360-nvr -p NRestarts
curl -s http://127.0.0.1:5000/api/stats | python3 -c "import sys,json; s=json.load(sys.stdin); print({n: d.get('inference_speed') for n, d in s['detectors'].items()}); print(s.get('gpu_usages'))"
free -m | head -2
```

| Qué | Esperado | Medido en el N150 (17/10/2026, 6 cámaras, 2 mosaicos 1080p) |
|---|---|---|
| Inferencia OpenVINO | < 15 ms | 10,5 ms |
| GPU | < 70 % | 12,7 % |
| Carga de CPU (`uptime`) | < 3,5 de 4 | ~2 |
| RAM usada | < 60 % del CT | 2,2 GB de 11,4 |
| `NRestarts` | no sube | 0 |

## 6. Si reemplaza a otro equipo

1. En el equipo anterior: Ajustes → Mosaico SRT → detener los mosaicos.
2. En el nuevo: Ajustes → Mosaico SRT → activarlos. Revisar que los canales
   lleguen al servidor (panel de Orbitv) y a MiraME.
3. Apagar el CT anterior (`pct shutdown 241` en el nodo anterior) y dejar de
   iniciarlo al arrancar (`pct set 241 --onboot 0`).
4. Opcional: dar al CT nuevo la IP del anterior (`192.168.1.241`) para no cambiar
   accesos ni marcadores: `pct set 241 -net0 name=eth0,bridge=vmbr0,ip=192.168.1.241/24,gw=192.168.1.254` y `pct reboot 241`.

## Anexo: traer la configuración de otro equipo (en lugar del paso 4)

En el **CT del equipo anterior**:

```bash
orbi360-respaldo /root/orbi360-respaldo.tar.gz
```

En el **nodo anterior** (`192.168.1.169` en el laboratorio), sacarlo del CT:

```bash
pct pull 241 /root/orbi360-respaldo.tar.gz /root/orbi360-respaldo.tar.gz
```

En el **nodo nuevo**, traerlo (pide la contraseña de root del nodo anterior) y
pasarlo a su CT:

```bash
scp root@192.168.1.169:/root/orbi360-respaldo.tar.gz /root/
pct push 241 /root/orbi360-respaldo.tar.gz /root/orbi360-respaldo.tar.gz
```

Al terminar, borrar las copias en `/root` de ambos nodos: contienen claves.

En el **CT nuevo**. Mientras el equipo anterior siga transmitiendo, restaurar
**sin mosaicos** (dos emisores al mismo canal SRT se pisan):

```bash
orbi360-restaurar /root/orbi360-respaldo.tar.gz --sin-mosaicos
```

Quedan las cámaras, la clave de las cámaras, los usuarios, Telegram, el
localizador y los mosaicos (detenidos). Las grabaciones no se copian.
