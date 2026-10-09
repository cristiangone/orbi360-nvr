"""Camera network locator: follow cameras by MAC and spot new ones.

Cameras get their address from a DHCP server we do not control, so an IP in
config.yml can start pointing at another device. Every few minutes
(orbi360-camlocator.timer) this module scans the LAN with arp-scan and:

* learns the MAC behind each configured camera address;
* when a known MAC shows up at a different address, rewrites that camera's
  URLs in config.yml and restarts go2rtc (and the NVR if the camera reads the
  device directly);
* reports devices with RTSP (port 554) that no camera uses yet.

Addresses answered by several MACs are never trusted: Xiongmai cameras keep
their factory address 192.168.1.10 as an alias, so every one of them answers
there. Findings are kept in /config/orbi360/camera-network.json and sent to
Telegram when alerts are enabled.

Usage::

    python3 -m frigate.orbi360.camlocator run [--dry-run]
"""

import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from ruamel.yaml import YAML

from frigate.const import CONFIG_DIR
from frigate.orbi360 import telegram

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(CONFIG_DIR) / "config.yml"
STATE_FILE = Path(CONFIG_DIR) / "orbi360" / "camera-network.json"
LOCK_FILE = Path("/run/orbi360-camlocator.lock")
FACTORY_IPS = {"192.168.1.10"}
RTSP_PORT = 554
MAX_EVENTS = 50

# Host of an RTSP/HTTP URL: preceded by "//" or "user:pass@", followed by ":" or "/"
URL_IP = re.compile(r"(?<=[/@])(\d{1,3}(?:\.\d{1,3}){3})(?=[:/])")
ARP_LINE = re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\s*(.*)$"
)
MAC_PATTERN = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
DUP_SUFFIX = re.compile(r"\s*\(DUP: \d+\)\s*$")
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
# MAC prefixes of virtual machines and containers (Proxmox, QEMU/KVM, Docker):
# never a camera, even when a guest holds an address the router also leased
VIRTUAL_OUIS = ("bc:24:11", "52:54:00", "02:42:")


def is_virtual(mac: str) -> bool:
    return mac.lower().startswith(VIRTUAL_OUIS)


def forget(state: dict, names: list[str]) -> list[str]:
    """Drop the learned MAC of these cameras so the next scan learns it again."""
    forgotten = []
    for name in names:
        rec = state["cameras"].get(name)
        if rec and rec.pop("mac", None):
            rec["status"] = "not_seen"
            forgotten.append(name)
    return forgotten


def ip_key(ip: str) -> tuple:
    return tuple(int(p) for p in ip.split("."))


def parse_arp_scan(text: str) -> list[tuple[str, str, str]]:
    """(ip, mac, vendor) for every reply line of arp-scan, duplicates included."""
    found = []
    for line in text.splitlines():
        match = ARP_LINE.match(line.strip())
        if not match:
            continue
        ip, mac, vendor = match.groups()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        found.append((ip, mac.lower(), DUP_SUFFIX.sub("", vendor).strip()))
    return found


def scan_network() -> list[tuple[str, str, str]]:
    result = subprocess.run(
        ["arp-scan", "--localnet", "--retry=3"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(result.stderr.strip() or "arp-scan failed")
    return parse_arp_scan(result.stdout)


def port_open(ip: str, port: int = RTSP_PORT, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _base_name(stream: str) -> str:
    return stream[: -len("_sub")] if stream.endswith("_sub") else stream


def _urls(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    return []


def camera_hosts(cfg: dict) -> dict[str, set[str]]:
    """Device addresses used by each camera, from go2rtc streams and direct inputs.

    "entrada" and "entrada_sub" both belong to camera "entrada". Inputs that
    read the local go2rtc restream are ignored.
    """
    hosts: dict[str, set[str]] = {}
    streams = ((cfg.get("go2rtc") or {}).get("streams")) or {}
    for name, sources in streams.items():
        for url in _urls(sources):
            for ip in URL_IP.findall(url):
                if ip not in LOCAL_HOSTS:
                    hosts.setdefault(_base_name(str(name)), set()).add(ip)
    for name, cam in (cfg.get("cameras") or {}).items():
        inputs = ((cam or {}).get("ffmpeg") or {}).get("inputs") or []
        for inp in inputs:
            for ip in URL_IP.findall(str((inp or {}).get("path", ""))):
                if ip not in LOCAL_HOSTS:
                    hosts.setdefault(str(name), set()).add(ip)
    return hosts


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            if isinstance(state, dict):
                state.setdefault("cameras", {})
                state.setdefault("discovered", {})
                state.setdefault("ignored", [])
                state.setdefault("events", [])
                return state
        except ValueError:
            logger.warning("camera-network.json is corrupt, starting over")
    return {
        "cameras": {},
        "discovered": {},
        "ignored": [],
        "events": [],
        "last_scan": None,
    }


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(STATE_FILE)


def _event(state: dict, kind: str, text: str, now: int) -> None:
    state["events"] = ([{"time": now, "kind": kind, "text": text}] + state["events"])[
        :MAX_EVENTS
    ]


def _replace_ip(url: str, old: str, new: str) -> str:
    return re.sub(rf"(?<=[/@]){re.escape(old)}(?=[:/])", new, url)


def apply_moves(cfg, moves: dict[str, tuple[str, str]]) -> bool:
    """Rewrite the URLs of moved cameras in a round-trip loaded config.

    Returns True when a camera input reads the device directly, which needs an
    NVR restart; go2rtc streams only need go2rtc restarted.
    """
    direct = False
    streams = ((cfg.get("go2rtc") or {}).get("streams")) or {}
    for name in list(streams):
        base = _base_name(str(name))
        if base not in moves:
            continue
        old, new = moves[base]
        value = streams[name]
        if isinstance(value, str):
            streams[name] = _replace_ip(value, old, new)
        else:
            for i, url in enumerate(value):
                if isinstance(url, str):
                    value[i] = _replace_ip(url, old, new)
    for name, cam in (cfg.get("cameras") or {}).items():
        if name not in moves:
            continue
        old, new = moves[name]
        for inp in ((cam or {}).get("ffmpeg") or {}).get("inputs") or []:
            path = str(inp.get("path", ""))
            replaced = _replace_ip(path, old, new)
            if replaced != path:
                inp["path"] = replaced
                direct = True
    return direct


def _notify(text: str) -> None:
    try:
        settings = telegram.load()
        if settings.enabled:
            error = telegram.send(settings, text)
            if error:
                logger.warning("Telegram: %s", error)
    except Exception as e:  # never let an alert break the scan
        logger.warning("Telegram: %s", e)


def _systemctl(*args: str) -> None:
    if shutil.which("systemctl") and Path("/run/systemd/system").is_dir():
        subprocess.run(["systemctl", *args], capture_output=True, timeout=120)


def locate(
    state: dict,
    hosts: dict[str, set[str]],
    entries: list[tuple[str, str, str]],
    now: int,
    probe=port_open,
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Update state from one scan. Returns (camera moves, messages to send)."""
    by_ip: dict[str, set[str]] = {}
    by_mac: dict[str, set[str]] = {}
    vendors: dict[str, str] = {}
    for ip, mac, vendor in entries:
        by_ip.setdefault(ip, set()).add(mac)
        by_mac.setdefault(mac, set()).add(ip)
        if vendor:
            vendors[mac] = vendor

    def own_ips(mac: str) -> list[str]:
        """Addresses only this MAC answers, factory alias excluded."""
        return sorted(
            (
                ip
                for ip in by_mac.get(mac, ())
                if ip not in FACTORY_IPS and len(by_ip[ip]) == 1
            ),
            key=ip_key,
        )

    moves: dict[str, tuple[str, str]] = {}
    messages: list[str] = []
    cameras = state["cameras"]
    for name in list(cameras):
        if name not in hosts:
            del cameras[name]

    for name, ips in sorted(hosts.items()):
        rec = cameras.setdefault(name, {})
        current = sorted(ips, key=ip_key)[0] if len(ips) == 1 else None
        rec["ip"] = current or ", ".join(sorted(ips, key=ip_key))
        mac = rec.get("mac")
        if mac and is_virtual(mac):
            # learned by an older version from a Proxmox guest sharing the address
            del rec["mac"]
            mac = None
        # Learn the MAC only from an address a single, non-virtual device answers
        # and that serves RTSP: a VM or another gadget may hold the camera's old IP
        if (
            not mac
            and current
            and current not in FACTORY_IPS
            and len(by_ip.get(current, ())) == 1
            and not is_virtual(next(iter(by_ip[current])))
            and probe(current)
        ):
            mac = next(iter(by_ip[current]))
            rec["mac"] = mac
        if not mac:
            rec["status"] = (
                "factory_ip"
                if current in FACTORY_IPS
                else (
                    "shared_ip" if len(by_ip.get(current or "", ())) > 1 else "not_seen"
                )
            )
            continue
        rec["vendor"] = vendors.get(mac, rec.get("vendor", ""))
        if mac not in by_mac:
            rec["status"] = "not_seen"
            continue
        rec["last_seen"] = now
        own = own_ips(mac)
        if current and current in own:
            rec["status"] = "ok"
        elif current and own:
            new = own[0]
            moves[name] = (current, new)
            rec["ip"] = new
            rec["status"] = "moved"
            rec["moved_at"] = now
            text = f"La cámara «{name}» cambió de IP: {current} → {new}. Orbi360 la actualizó solo."
            _event(state, "moved", text, now)
            messages.append(f"📷 Orbi360 NVR: {text}")
        else:
            rec["status"] = "shared_ip"

    # Devices with RTSP that no camera uses yet
    known_macs = {rec.get("mac") for rec in cameras.values() if rec.get("mac")}
    used_ips = set().union(*hosts.values()) if hosts else set()
    ignored = set(state["ignored"])
    discovered = state["discovered"]
    for mac, ips in by_mac.items():
        if mac in known_macs or mac in ignored or ips & used_ips or is_virtual(mac):
            continue
        candidates = own_ips(mac) or sorted(ips, key=ip_key)
        ip = candidates[0]
        if not probe(ip):
            continue
        entry = discovered.get(mac)
        if entry is None:
            entry = discovered[mac] = {"first_seen": now}
            vendor = vendors.get(mac, "")
            text = f"Cámara nueva detectada en {ip} (MAC {mac}{', ' + vendor if vendor else ''})."
            _event(state, "new", text, now)
            messages.append(f"🆕 Orbi360 NVR: {text} Agrégala desde Ajustes.")
        entry.update({"ip": ip, "vendor": vendors.get(mac, ""), "last_seen": now})
    for mac in list(discovered):
        if mac in known_macs or mac in ignored:
            del discovered[mac]

    state["last_scan"] = now
    return moves, messages


def forget_saved(names: list[str]) -> list[str]:
    """forget() on the saved state, under the same lock as a scan."""
    import fcntl

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state()
        done = forget(state, names)
        save_state(state)
        return done


def run(dry_run: bool = False) -> dict:
    """One scan: update state, fix moved cameras, notify. Serialized by a lock."""
    import fcntl  # Linux only; imported here so the logic stays testable elsewhere

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)  # same style as config.yml
        cfg = yaml.load(CONFIG_FILE.read_text()) or {}
        state = load_state()
        moves, messages = locate(
            state, camera_hosts(cfg), scan_network(), int(time.time())
        )
        if moves and not dry_run:
            backup = CONFIG_FILE.with_name(f"config.yml.bak-locator-{int(time.time())}")
            shutil.copy(CONFIG_FILE, backup)
            direct = apply_moves(cfg, moves)
            tmp = CONFIG_FILE.with_suffix(".yml.tmp")
            with tmp.open("w") as f:
                yaml.dump(cfg, f)
            tmp.replace(CONFIG_FILE)
            logger.info("cameras moved: %s (backup %s)", moves, backup.name)
            _systemctl("restart", "orbi360-go2rtc.service")
            if direct:
                _systemctl("restart", "orbi360-nvr.service")
        if not dry_run:
            save_state(state)
            for text in messages:
                _notify(text)
        return state


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(argv) >= 3 and argv[1] == "forget":
        done = forget_saved(argv[2:])
        print("MAC olvidada:", ", ".join(done) or "ninguna (sin MAC aprendida)")
        return 0
    if len(argv) < 2 or argv[1] != "run":
        print(
            "usage: python3 -m frigate.orbi360.camlocator run [--dry-run]\n"
            "       python3 -m frigate.orbi360.camlocator forget <camara> [...]",
            file=sys.stderr,
        )
        return 2
    state = run(dry_run="--dry-run" in argv)
    for name, rec in sorted(state["cameras"].items()):
        print(
            f"{name:20} {rec.get('ip', '?'):16} {rec.get('mac', '?'):18} {rec.get('status')}"
        )
    for mac, entry in state["discovered"].items():
        print(f"NUEVA {entry['ip']:16} {mac:18} {entry.get('vendor', '')}")
    return 0


if __name__ == "__main__":
    os.umask(0o022)
    sys.exit(main(sys.argv))
