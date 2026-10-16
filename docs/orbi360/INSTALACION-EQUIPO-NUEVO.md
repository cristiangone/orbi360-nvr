# Instalar Orbi360 NVR en un equipo nuevo

Guía para un mini PC dedicado (probada para el Machenike Mini N TL24: Intel N150,
16 GB, 512 GB, 2 puertos LAN). El equipo lleva **Proxmox VE** como sistema
operativo y Orbi360 NVR dentro de un contenedor (CT), igual que el laboratorio.

> Proxmox VE no se instala sobre Ubuntu: es un sistema operativo completo
> (basado en Debian) que se instala directo en el equipo desde su ISO.

## 0. Antes de empezar

- Un pendrive de 8 GB o más.
- Cable de red al router (puerto LAN de la izquierda).
- Elegir dos IP libres de la red, por ejemplo `192.168.1.170` para Proxmox y
  `192.168.1.242` para el CT. Comprobar que nadie las use (desde el CT actual):
  `arp-scan --localnet | grep -wE "192.168.1.170|192.168.1.242"` (sin resultado = libres).

## 1. Instalar Proxmox VE

1. Descargar el ISO de la última versión de **Proxmox VE** desde
   https://www.proxmox.com/en/downloads (sección *Proxmox Virtual Environment*).
2. Grabarlo en el pendrive con **balenaEtcher** o **Rufus** (en Rufus, modo *DD*).
3. Conectar el pendrive, un monitor y un teclado al mini PC. Encenderlo y abrir el
   menú de arranque (en estos equipos suele ser **F7**, **F11** o **Supr/Del**).
   Elegir el pendrive.
4. *Install Proxmox VE (Graphical)*:
   - Disco: el SSD de 512 GB, sistema de archivos **ext4** (por defecto).
   - País, zona horaria **America/Santiago** y teclado **Latin American**.
   - Contraseña de root y un correo.
   - Red: la interfaz conectada, **hostname** (ej. `orbi360-n150.local`), IP
     `192.168.1.170/24`, gateway `192.168.1.254`, DNS `1.1.1.1`.
5. Al terminar, retirar el pendrive. Desde otro PC abrir `https://192.168.1.170:8006`
   (usuario `root`, la contraseña elegida; aceptar la advertencia del certificado).

### Repositorios (sin suscripción)

En el nodo: *Actualizaciones → Repositorios*: deshabilitar los repositorios
**enterprise** (PVE y Ceph) y agregar **No-Subscription**. Luego en la consola del nodo:

```bash
apt update && apt full-upgrade -y && reboot
```

## 2. Crear el contenedor de Orbi360

En la **consola del nodo** (Proxmox → nodo → *Consola*). Sin `MEMORY`, `CPULIMIT`
ni `MEDIA_SIZE` el script se ajusta al equipo (todos los hilos, la RAM menos 4 GB
para Proxmox y ~75 % del espacio libre para grabaciones). Pasa la iGPU al CT.

```bash
CTID=241 IP=192.168.1.242/24 GW=192.168.1.254 bash -c "$(wget -qO- https://raw.githubusercontent.com/cristiangone/orbi360-nvr/orbi360/orbi360/lxc/create-ct.sh)"
```

## 3. Instalar Orbi360 NVR

```bash
pct enter 241
bash -c "$(wget -qO- https://raw.githubusercontent.com/cristiangone/orbi360-nvr/orbi360/orbi360/lxc/install.sh)"
```

Tarda 20-40 minutos la primera vez (compila la interfaz). Al final muestra la
dirección `https://192.168.1.242:8971`. Para ver la clave inicial de `admin`:

```bash
grep -A2 -i password /dev/shm/logs/frigate/current
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

| Qué | Esperado en un N150 |
|---|---|
| Inferencia OpenVINO | ~15 ms |
| GPU | < 70 % |
| RAM usada | < 60 % del CT |
| `NRestarts` | no sube |

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
