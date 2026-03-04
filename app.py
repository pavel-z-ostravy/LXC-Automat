"""
monitor-public — config-driven homelab dashboard
If config.json doesn't exist yet, serves the installer wizard.
Otherwise serves the full dashboard.
"""
import os
import importlib.util

INSTALL_PATH = os.environ.get("INSTALL_PATH", "/opt/monitor-public")
CONFIG_FILE = os.path.join(INSTALL_PATH, "config.json")


def _load_installer_app():
    spec = importlib.util.spec_from_file_location(
        "installer", os.path.join(INSTALL_PATH, "installer.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def _load_dashboard_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from starlette.middleware.base import BaseHTTPMiddleware
    import subprocess
    import re
    import json
    import time
    import secrets
    import hashlib
    import hmac
    from datetime import datetime
    import httpx
    import wakeonlan
    import threading as _threading
    import uuid as _uuid
    import shlex

    # ── Config load ─────────────────────────────────────────────────────────
    with open(CONFIG_FILE) as f:
        config = json.load(f)

    AUTH = config["auth"]
    PROXMOX = config["proxmox"]
    MODULES = config["modules"]
    SERVICES_CFG = config.get("services", [])
    WOL_DEVICES = config.get("wol_devices", [])
    DASHBOARD_NAME = config.get("dashboard_name", "Homelab")

    HISTORY_FILE = os.path.join(INSTALL_PATH, "temp_history.json")
    STATS_HISTORY_FILE = os.path.join(INSTALL_PATH, "stats_history.json")
    SPEED_HISTORY_FILE = os.path.join(INSTALL_PATH, "speed_history.json")
    MAX_HISTORY = 1440

    # ── SSH helpers ──────────────────────────────────────────────────────────

    def _ssh_cmd(ip, user, auth, password, key_path, port=22):
        if auth == "password":
            return ["sshpass", "-p", password, "ssh",
                    "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                    f"-p{port}", f"{user}@{ip}"]
        else:
            return ["ssh", "-i", key_path,
                    "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                    "-p", str(port), f"{user}@{ip}"]

    def proxmox_ssh():
        p = PROXMOX
        return _ssh_cmd(p["ip"], p["ssh_user"], p["ssh_auth"],
                        p.get("ssh_password", ""), p.get("ssh_key_path", ""), p.get("ssh_port", 22))

    def ha_ssh():
        ha = MODULES["home_assistant"]
        return _ssh_cmd(ha["ip"], ha["ssh_user"], "password",
                        ha.get("ssh_password", ""), "", ha.get("ssh_port", 22))

    def router_ssh():
        r = MODULES["router"]
        return _ssh_cmd(r["ip"], r["ssh_user"], r.get("ssh_auth", "key"),
                        r.get("ssh_password", ""), r.get("ssh_key_path", ""), r.get("ssh_port", 22))

    # ── Auth middleware ──────────────────────────────────────────────────────

    valid_tokens: set = set()

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if path in ("/login", "/setup") or path.startswith("/static"):
                return await call_next(request)
            token = request.cookies.get("session")
            if not token or token not in valid_tokens:
                if path.startswith("/api"):
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                return RedirectResponse("/login")
            return await call_next(request)

    dashboard = FastAPI()
    dashboard.add_middleware(AuthMiddleware)
    dashboard.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @dashboard.get("/locales/{filename}")
    def serve_locale(filename: str):
        import re as _re
        if not _re.match(r'^dashboard-(en|cs)\.json$', filename):
            return JSONResponse({"error": "Not found"}, status_code=404)
        path = os.path.join(INSTALL_PATH, "locales", filename)
        if not os.path.exists(path):
            return JSONResponse({"error": "Not found"}, status_code=404)
        with open(path) as f:
            return JSONResponse(json.load(f))

    # ── Helpers ──────────────────────────────────────────────────────────────

    def parse_stats(ssh_prefix=[]):
        try:
            cpu = subprocess.run(ssh_prefix + ["top", "-bn1"], capture_output=True, text=True, timeout=5).stdout
            cpu_line = [l for l in cpu.split("\n") if "Cpu(s)" in l or "%Cpu" in l]
            cpu_pct = 0
            if cpu_line:
                m = re.search(r"(\d+\.?\d*)\s*us", cpu_line[0])
                if m:
                    cpu_pct = float(m.group(1))
            mem = subprocess.run(ssh_prefix + ["free", "-b"], capture_output=True, text=True, timeout=5).stdout
            mem_vals = mem.strip().split("\n")[1].split()
            mem_total, mem_used = int(mem_vals[1]), int(mem_vals[2])
            mem_pct = round(mem_used / mem_total * 100, 1)
            disk = subprocess.run(ssh_prefix + ["df", "-B1", "/"], capture_output=True, text=True, timeout=5).stdout
            disk_vals = disk.strip().split("\n")[1].split()
            disk_total, disk_used = int(disk_vals[1]), int(disk_vals[2])
            disk_pct = round(disk_used / disk_total * 100, 1)
            proc = subprocess.run(ssh_prefix + ["ps", "aux", "--sort=-%cpu"], capture_output=True, text=True, timeout=5).stdout
            processes = []
            for line in proc.strip().split("\n")[1:11]:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    processes.append({"pid": parts[1], "cpu": parts[2], "mem": parts[3], "name": parts[10][:50]})
            uptime = subprocess.run(ssh_prefix + ["uptime", "-p"], capture_output=True, text=True, timeout=5).stdout.strip()
            hostname = subprocess.run(ssh_prefix + ["hostname"], capture_output=True, text=True, timeout=3).stdout.strip()
            return {"online": True, "cpu": cpu_pct,
                    "mem": {"total": mem_total, "used": mem_used, "pct": mem_pct},
                    "disk": {"total": disk_total, "used": disk_used, "pct": disk_pct},
                    "processes": processes, "uptime": uptime, "hostname": hostname}
        except Exception as e:
            return {"online": False, "error": str(e)}

    def load_history(path):
        if not os.path.exists(path):
            return {"history": []}
        with open(path) as f:
            return json.load(f)

    def save_history(path, entry):
        data = load_history(path)
        history = data.get("history", [])
        entry["time"] = datetime.now().strftime("%H:%M:%S")
        history.append(entry)
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        with open(path, "w") as f:
            json.dump({"history": history}, f)

    def fmt_bytes(b):
        for unit in ["B", "K", "M", "G", "T"]:
            if b < 1024:
                return f"{b:.1f}{unit}"
            b /= 1024
        return f"{b:.1f}P"

    def parse_smart(smart_output, host, dev):
        d = {"host": host, "dev": dev, "reallocated": 0, "pending": 0, "uncorrectable": 0}
        for pattern, key in [
            (r"Device Model:\s+(.+)", "model"), (r"Model Number:\s+(.+)", "model"),
            (r"User Capacity.*?\[(.+?)\]", "size"),
        ]:
            m = re.search(pattern, smart_output)
            if m and key not in d:
                d[key] = m.group(1).strip()
        m = re.search(r"SMART overall-health.*?:\s+(\w+)", smart_output)
        if not m:
            m = re.search(r"SMART Health Status:\s+(\w+)", smart_output)
        if m:
            d["health"] = m.group(1).strip()
        for pattern, key in [
            (r"Temperature_Celsius\s+\S+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+(\d+)", "temp"),
            (r"Temperature:\s+(\d+)", "temp"),
            (r"Power_On_Hours\s+\S+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+([\d,]+)", "hours"),
            (r"Power On Hours:\s+([\d,]+)", "hours"),
        ]:
            if key not in d:
                m = re.search(pattern, smart_output)
                if m:
                    d[key] = int(m.group(1).replace(",", ""))
        for pattern, key in [
            (r"Reallocated_Sector_Ct\s+\S+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+(\d+)", "reallocated"),
            (r"Current_Pending_Sector\s+\S+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+(\d+)", "pending"),
            (r"Offline_Uncorrectable\s+\S+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+(\d+)", "uncorrectable"),
        ]:
            m = re.search(pattern, smart_output)
            if m:
                d[key] = int(m.group(1))
        return d

    # ── Auth endpoints ───────────────────────────────────────────────────────

    LOGIN_HTML = """<!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Přihlášení</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{background:#0d1b2a;color:#eee;font-family:monospace;display:flex;align-items:center;justify-content:center;min-height:100vh}}.box{{background:#16213e;border:1px solid #0f3460;border-radius:12px;padding:36px 40px;width:320px}}h2{{color:#00d4ff;margin-bottom:24px;font-size:18px;text-align:center}}label{{font-size:12px;color:#888;display:block;margin-bottom:4px}}input{{width:100%;padding:10px 12px;background:#0d1b2a;border:1px solid #0f3460;border-radius:6px;color:#eee;font-family:monospace;font-size:14px;margin-bottom:16px}}button{{width:100%;padding:11px;background:#0f3460;color:#00d4ff;border:1px solid #00d4ff;border-radius:6px;font-family:monospace;font-size:14px;cursor:pointer}}.err{{color:#ff6b6b;font-size:12px;margin-top:12px;text-align:center}}</style>
</head><body><div class="box"><h2>🖥️ Dashboard</h2>
<form method="post" action="/login">
<label>Uživatelské jméno</label><input type="text" name="username" autofocus autocomplete="username">
<label>Heslo</label><input type="password" name="password" autocomplete="current-password">
<button type="submit">Přihlásit se</button></form>{err}</div></body></html>"""

    @dashboard.get("/login", response_class=HTMLResponse)
    def login_page():
        return LOGIN_HTML.format(err='<div class="err" id="err"></div>')

    @dashboard.post("/login")
    async def login(request: Request):
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")
        pass_hash = hashlib.sha256(password.encode()).hexdigest()
        if (hmac.compare_digest(username, AUTH["username"]) and
                hmac.compare_digest(pass_hash, AUTH["password_hash"])):
            token = secrets.token_hex(32)
            valid_tokens.add(token)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie("session", token, httponly=True, samesite="lax")
            return resp
        return HTMLResponse(LOGIN_HTML.format(err='<div class="err">Špatné jméno nebo heslo.</div>'), status_code=401)

    @dashboard.post("/logout")
    def logout(request: Request):
        token = request.cookies.get("session")
        if token:
            valid_tokens.discard(token)
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie("session")
        return resp

    # ── Config API ───────────────────────────────────────────────────────────

    @dashboard.get("/api/config/modules")
    def get_modules():
        return {
            "dashboard_name": DASHBOARD_NAME,
            "home_assistant": MODULES["home_assistant"]["enabled"],
            "router": MODULES["router"]["enabled"],
            "cloudflare": MODULES["cloudflare"]["enabled"],
            "nextdns": MODULES["nextdns"]["enabled"],
            "wol": len(WOL_DEVICES) > 0,
            "services": len(SERVICES_CFG) > 0,
        }

    @dashboard.get("/api/wol/devices")
    def get_wol_devices():
        return {"devices": WOL_DEVICES}

    # ── Stats ────────────────────────────────────────────────────────────────

    @dashboard.get("/api/stats")
    def get_stats():
        result = parse_stats(proxmox_ssh())
        try:
            net_raw = open("/proc/net/dev").read()
            net_data = {}
            for line in net_raw.strip().split("\n")[2:]:
                parts = line.split()
                if len(parts) >= 10:
                    iface = parts[0].rstrip(":")
                    if iface != "lo":
                        net_data[iface] = {"rx": int(parts[1]), "tx": int(parts[9])}
            result["net"] = net_data
        except Exception:
            result["net"] = {}
        return result

    @dashboard.get("/api/vm_stats")
    def get_vm_stats():
        return parse_stats()

    @dashboard.get("/api/sensors")
    def get_sensors():
        result = subprocess.run(proxmox_ssh() + ["sensors"], capture_output=True, text=True)
        return {"output": result.stdout}

    # ── History ──────────────────────────────────────────────────────────────

    @dashboard.get("/api/temp_history")
    def get_temp_history():
        return load_history(HISTORY_FILE)

    @dashboard.post("/api/temp_history/save")
    def save_temp_history(entry: dict):
        save_history(HISTORY_FILE, entry)
        return {"ok": True}

    @dashboard.get("/api/stats_history")
    def get_stats_history():
        return load_history(STATS_HISTORY_FILE)

    @dashboard.post("/api/stats_history/save")
    def save_stats_history(entry: dict):
        save_history(STATS_HISTORY_FILE, entry)
        return {"ok": True}

    # ── Services ─────────────────────────────────────────────────────────────

    @dashboard.get("/api/services")
    def get_services():
        results = []
        for svc in SERVICES_CFG:
            try:
                if "url" in svc:
                    r = httpx.get(svc["url"], timeout=3, follow_redirects=True)
                    online = r.status_code < 500
                else:
                    import socket
                    s = socket.create_connection((svc["host"], svc["port"]), timeout=3)
                    s.close()
                    online = True
            except Exception:
                online = False
            results.append({"name": svc["name"], "online": online, "icon": svc.get("icon", "")})
        return {"services": results}

    # ── WoL ──────────────────────────────────────────────────────────────────

    @dashboard.get("/api/wol/ping")
    def wol_ping():
        result = {}
        for dev in WOL_DEVICES:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", dev["ip"]], capture_output=True, timeout=3)
            result[dev["ip"]] = r.returncode == 0
        return result

    @dashboard.post("/api/wol")
    def send_wol(data: dict):
        try:
            mac = data.get("mac")
            wakeonlan.send_magic_packet(mac)
            return {"ok": True, "message": f"WoL paket odeslán na {mac}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Network ───────────────────────────────────────────────────────────────

    @dashboard.get("/api/network")
    def get_network():
        try:
            result = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=5)
            devices = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 5:
                    devices.append({"ip": parts[0], "mac": parts[4] if len(parts) > 4 else "",
                                     "state": parts[-1], "iface": parts[2] if len(parts) > 2 else ""})
            return {"devices": devices}
        except Exception as e:
            return {"devices": [], "error": str(e)}

    @dashboard.get("/api/ping")
    def ping_host(ip: str):
        try:
            result = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, timeout=3)
            return {"online": result.returncode == 0}
        except Exception:
            return {"online": False}

    # ── Storage / SMART ───────────────────────────────────────────────────────

    @dashboard.get("/api/smart")
    def get_smart():
        try:
            ssh = proxmox_ssh()
            node = PROXMOX["node"]
            usage = []
            disks = []

            df_local = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5).stdout
            for line in df_local.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 6:
                    usage.append({"host": "local", "mount": "Systémový disk",
                                   "size": parts[1], "used": parts[2], "pct": parts[4].rstrip("%")})

            if MODULES["home_assistant"]["enabled"]:
                df_ha = subprocess.run(ha_ssh() + ["df -h /data"], capture_output=True, text=True, timeout=8).stdout
                for line in df_ha.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 6:
                        usage.append({"host": "Home Assistant", "mount": "HA disk",
                                       "size": parts[1], "used": parts[2], "pct": parts[4].rstrip("%")})

            if PROXMOX["ip"]:
                df_prox = subprocess.run(ssh + ["df -h /"], capture_output=True, text=True, timeout=10).stdout
                for line in df_prox.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 6:
                        usage.append({"host": "Proxmox", "mount": "Systém",
                                       "size": parts[1], "used": parts[2], "pct": parts[4].rstrip("%")})

                pvd_out = subprocess.run(
                    ssh + [f"pvesh get /nodes/{node}/storage/local-lvm/status --output-format json"],
                    capture_output=True, text=True, timeout=10
                ).stdout.strip()
                if pvd_out:
                    pvd = json.loads(pvd_out)
                    pvd_total = pvd.get("total", 0)
                    pvd_used = pvd.get("used", 0)
                    pvd_pct = round(pvd_used / pvd_total * 100, 1) if pvd_total else 0
                    usage.append({"host": "Proxmox", "mount": "local-lvm",
                                   "size": fmt_bytes(pvd_total), "used": fmt_bytes(pvd_used), "pct": str(int(pvd_pct))})

                smart_out = subprocess.run(ssh + ["smartctl -a /dev/sda"], capture_output=True, text=True, timeout=15).stdout
                disks.append(parse_smart(smart_out, "Proxmox", "/dev/sda"))

            return {"disks": disks, "usage": usage}
        except Exception as e:
            return {"error": str(e), "disks": [], "usage": []}

    @dashboard.get("/api/storage")
    def get_storage():
        try:
            ssh = proxmox_ssh()
            node = PROXMOX["node"]
            vms = []

            for line in subprocess.run(["df", "-B1", "/"], capture_output=True, text=True, timeout=5).stdout.strip().split("\n")[1:]:
                p = line.split()
                if len(p) >= 4:
                    total, used, free = int(p[1]), int(p[2]), int(p[3])
                    vms.append({"name": "local", "label": "Lokální disk",
                                 "total": total, "used": used, "free": free, "pct": round(used/total*100, 1)})

            if MODULES["home_assistant"]["enabled"]:
                for line in subprocess.run(ha_ssh() + ["df -B1 /data"], capture_output=True, text=True, timeout=5).stdout.strip().split("\n")[1:]:
                    p = line.split()
                    if len(p) >= 4:
                        total, used, free = int(p[1]), int(p[2]), int(p[3])
                        vms.append({"name": "Home Assistant", "label": "HA disk",
                                     "total": total, "used": used, "free": free, "pct": round(used/total*100, 1)})

            server = []
            pools = []
            if PROXMOX["ip"]:
                r = subprocess.run(ssh + ["lsblk -b -J -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,FSUSE%,MODEL"],
                                    capture_output=True, text=True, timeout=10)
                server = json.loads(r.stdout).get("blockdevices", []) if r.stdout.strip() else []

                pvd_out = subprocess.run(
                    ssh + [f"pvesh get /nodes/{node}/storage/local-lvm/status --output-format json"],
                    capture_output=True, text=True, timeout=10
                ).stdout.strip()
                if pvd_out:
                    pvd = json.loads(pvd_out)
                    pvd_total = pvd.get("total", 0)
                    pvd_used = pvd.get("used", 0)
                    pct = round(pvd_used / pvd_total * 100, 1) if pvd_total else 0
                    pools.append({"name": "pve-data", "label": "VM/kontejnery",
                                   "total": pvd_total, "used": pvd_used, "free": pvd_total - pvd_used, "pct": pct})

            r2 = subprocess.run(["lsblk", "-b", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,FSUSE%,MODEL"],
                                 capture_output=True, text=True, timeout=5)
            all_local = json.loads(r2.stdout).get("blockdevices", []) if r2.stdout.strip() else []
            external = [d for d in all_local if d.get("type") == "disk" and d.get("name") not in ("sda", "sr0")]
            return {"server": server, "external": external, "vms": vms, "pools": pools}
        except Exception as e:
            return {"error": str(e), "server": [], "external": [], "vms": []}

    @dashboard.get("/api/storage/external")
    def get_storage_external():
        try:
            r = subprocess.run(["lsblk", "-b", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,FSUSE%,MODEL"],
                                capture_output=True, text=True, timeout=5)
            all_local = json.loads(r.stdout).get("blockdevices", []) if r.stdout.strip() else []
            return {"external": [d for d in all_local if d.get("type") == "disk" and d.get("name") not in ("sda", "sr0")]}
        except Exception as e:
            return {"error": str(e), "external": []}

    # ── Backups ───────────────────────────────────────────────────────────────

    @dashboard.get("/api/backups")
    def get_backups():
        try:
            ssh = proxmox_ssh()
            node = PROXMOX["node"]
            r = subprocess.run(ssh + [f"pvesh get /nodes/{node}/storage/local/content --content backup --output-format json"],
                                capture_output=True, text=True, timeout=15)
            backups = sorted([b for b in (json.loads(r.stdout) if r.stdout.strip() else []) if b.get("content") == "backup"],
                             key=lambda x: x.get("ctime", 0))
            r2 = subprocess.run(ssh + [f"pvesh get /nodes/{node}/qemu --output-format json"], capture_output=True, text=True, timeout=10)
            r3 = subprocess.run(ssh + [f"pvesh get /nodes/{node}/lxc --output-format json"], capture_output=True, text=True, timeout=10)
            vms = json.loads(r2.stdout) if r2.stdout.strip() else []
            lxc = json.loads(r3.stdout) if r3.stdout.strip() else []
            all_vms = sorted([{"vmid": v["vmid"], "name": v.get("name", str(v["vmid"]))} for v in vms + lxc], key=lambda x: x["vmid"])
            return {"backups": backups, "vms": all_vms}
        except Exception as e:
            return {"backups": [], "vms": [], "error": str(e)}

    @dashboard.delete("/api/backups/delete")
    def delete_backup(volid: str):
        if not re.match(r'^[\w\-:.]+$', volid):
            return JSONResponse({"error": "Invalid volid"}, status_code=400)
        try:
            ssh = proxmox_ssh()
            node = PROXMOX["node"]
            r = subprocess.run(ssh + [f"pvesh delete /nodes/{node}/storage/local/content/{volid}"],
                                capture_output=True, text=True, timeout=30)
            return {"ok": True} if r.returncode == 0 else {"error": r.stderr}
        except Exception as e:
            return {"error": str(e)}

    @dashboard.post("/api/backups/run")
    def run_backup(vmid: str, mode: str = "stop"):
        if not re.match(r'^\d+$', vmid):
            return JSONResponse({"error": "Invalid vmid"}, status_code=400)
        if mode not in {"stop", "suspend", "snapshot"}:
            return JSONResponse({"error": "Invalid mode"}, status_code=400)
        try:
            ssh = proxmox_ssh()
            proc = subprocess.Popen(ssh + [f"vzdump {vmid} --storage local --mode {mode} --compress zstd"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            return {"ok": True, "pid": proc.pid}
        except Exception as e:
            return {"error": str(e)}

    @dashboard.get("/api/backups/schedule")
    def get_backup_schedule():
        try:
            ssh = proxmox_ssh()
            r = subprocess.run(ssh + ["pvesh get /cluster/backup --output-format json"], capture_output=True, text=True, timeout=10)
            jobs = json.loads(r.stdout) if r.stdout.strip() else []
            if not jobs:
                return {}
            job = jobs[0]
            return {"schedule": f"{job.get('dow','sun')} {job.get('starttime','02:00')}",
                    "vmids": job.get("vmid", ""), "maxfiles": job.get("maxfiles", 1), "raw": job}
        except Exception as e:
            return {"error": str(e)}

    @dashboard.post("/api/backups/schedule")
    def save_backup_schedule(vmids: str, hour: int, minute: int, dow: str = "sun", maxfiles: int = 1):
        if not re.match(r'^[\d,]+$', vmids):
            return JSONResponse({"error": "Invalid vmids"}, status_code=400)
        if dow not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
            return JSONResponse({"error": "Invalid dow"}, status_code=400)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return JSONResponse({"error": "Invalid time"}, status_code=400)
        if not (1 <= maxfiles <= 999):
            return JSONResponse({"error": "Invalid maxfiles"}, status_code=400)
        try:
            ssh = proxmox_ssh()
            starttime = f"{hour:02d}:{minute:02d}"
            r = subprocess.run(ssh + ["pvesh get /cluster/backup --output-format json"], capture_output=True, text=True, timeout=10)
            jobs = json.loads(r.stdout) if r.stdout.strip() else []
            if jobs:
                job_id = jobs[0].get("id")
                cmd = f"pvesh set /cluster/backup/{job_id} --vmid {vmids} --starttime {starttime} --dow {dow} --maxfiles {maxfiles}"
            else:
                cmd = f"pvesh create /cluster/backup --vmid {vmids} --starttime {starttime} --dow {dow} --maxfiles {maxfiles} --storage local --mode stop --compress zstd --enabled 1"
            r2 = subprocess.run(ssh + [cmd], capture_output=True, text=True, timeout=10)
            return {"ok": True} if r2.returncode == 0 else {"error": r2.stderr}
        except Exception as e:
            return {"error": str(e)}

    # ── Conditional: Home Assistant ───────────────────────────────────────────

    if MODULES["home_assistant"]["enabled"]:
        @dashboard.get("/api/ha_stats")
        def get_ha_stats():
            return parse_stats(ha_ssh())

    # ── Conditional: Router ───────────────────────────────────────────────────

    if MODULES["router"]["enabled"]:
        _prev_conntrack = {}
        _prev_conntrack_time = 0.0
        _router_subnet = MODULES["router"].get("subnet", "10.0.")

        @dashboard.get("/api/network/speeds")
        def get_network_speeds():
            nonlocal _prev_conntrack, _prev_conntrack_time
            try:
                out = subprocess.run(
                    router_ssh() + ["cat /proc/net/nf_conntrack 2>/dev/null || cat /proc/net/ip_conntrack 2>/dev/null"],
                    capture_output=True, text=True, timeout=5
                ).stdout
                now = time.time()
                curr = {}
                router_ip = MODULES["router"]["ip"]
                for line in out.strip().split("\n"):
                    if _router_subnet not in line:
                        continue
                    srcs = re.findall(r"src=([\d.]+)", line)
                    bytes_vals = re.findall(r"bytes=(\d+)", line)
                    dsts = re.findall(r"dst=([\d.]+)", line)
                    if len(srcs) < 1 or len(bytes_vals) < 2:
                        continue
                    if srcs[0].startswith(_router_subnet) and srcs[0] != router_ip:
                        local_ip = srcs[0]
                        tx_b, rx_b = int(bytes_vals[0]), int(bytes_vals[1])
                    elif dsts and dsts[0].startswith(_router_subnet) and dsts[0] != router_ip:
                        local_ip = dsts[0]
                        rx_b, tx_b = int(bytes_vals[0]), int(bytes_vals[1])
                    else:
                        continue
                    if local_ip not in curr:
                        curr[local_ip] = {"rx": 0, "tx": 0}
                    curr[local_ip]["rx"] += rx_b
                    curr[local_ip]["tx"] += tx_b

                speeds = {}
                dt = now - _prev_conntrack_time
                if _prev_conntrack and dt > 0.5:
                    for ip, data in curr.items():
                        prev = _prev_conntrack.get(ip, {"rx": 0, "tx": 0})
                        rx_diff = max(0, data["rx"] - prev["rx"])
                        tx_diff = max(0, data["tx"] - prev["tx"])
                        speeds[ip] = {"rx_kbps": round(rx_diff / dt / 1024, 1),
                                       "tx_kbps": round(tx_diff / dt / 1024, 1)}
                _prev_conntrack = curr
                _prev_conntrack_time = now
                return {"speeds": speeds}
            except Exception as e:
                return {"speeds": {}, "error": str(e)}

    # ── Conditional: Cloudflare ───────────────────────────────────────────────

    if MODULES["cloudflare"]["enabled"]:
        _CF = MODULES["cloudflare"]

        @dashboard.get("/api/cloudflare")
        def get_cloudflare():
            try:
                headers = {"Authorization": f"Bearer {_CF['token']}"}
                tunnel_r = httpx.get(
                    f"https://api.cloudflare.com/client/v4/accounts/{_CF['account_id']}/cfd_tunnel/{_CF['tunnel_id']}",
                    headers=headers, timeout=5)
                dns_r = httpx.get(
                    f"https://api.cloudflare.com/client/v4/zones/{_CF['zone_id']}/dns_records?per_page=100",
                    headers=headers, timeout=5)
                tunnel = tunnel_r.json().get("result", {})
                dns = dns_r.json().get("result", [])
                connections = tunnel.get("connections", [])
                return {
                    "tunnel_name": tunnel.get("name"),
                    "status": tunnel.get("status"),
                    "connections": len(connections),
                    "colos": list(set(c["colo_name"] for c in connections)),
                    "domains": [{"name": r["name"], "proxied": r["proxied"], "modified": r["modified_on"]}
                                 for r in dns if r.get("type") == "CNAME" and "cfargotunnel" in r.get("content", "")],
                    "version": connections[0].get("client_version") if connections else None,
                }
            except Exception as e:
                return {"error": str(e)}

        @dashboard.get("/api/cloudflare/metrics")
        def get_cloudflare_metrics():
            try:
                r = httpx.get("http://127.0.0.1:20241/metrics", timeout=3)
                vals = {}
                for line in r.text.splitlines():
                    if not line.startswith("#"):
                        parts = line.split(" ")
                        if len(parts) >= 2:
                            vals[parts[0]] = parts[1]
                errors = int(float(vals.get("cloudflared_tunnel_request_errors", 0)))
                for key, val in vals.items():
                    if key.startswith("cloudflared_tunnel_response_by_code{"):
                        m = re.search(r'status_code="(\d+)"', key)
                        if m and int(m.group(1)) >= 400:
                            errors += int(float(val))
                return {"concurrent": int(float(vals.get("cloudflared_tunnel_concurrent_requests_per_tunnel", 0))),
                         "ha_connections": int(float(vals.get("cloudflared_tunnel_ha_connections", 0))),
                         "total_requests": int(float(vals.get("cloudflared_tunnel_total_requests", 0))),
                         "errors": errors}
            except Exception as e:
                return {"error": str(e), "concurrent": 0, "ha_connections": 0, "total_requests": 0, "errors": 0}

    # ── Conditional: NextDNS ─────────────────────────────────────────────────

    if MODULES["nextdns"]["enabled"]:
        _NDNS = MODULES["nextdns"]

        @dashboard.get("/api/nextdns")
        def get_nextdns():
            try:
                headers = {"X-Api-Key": _NDNS["api_key"]}
                r1 = httpx.get(f"https://api.nextdns.io/profiles/{_NDNS['profile_id']}/analytics/status?from=-1d",
                                headers=headers, timeout=5)
                r2 = httpx.get(f"https://api.nextdns.io/profiles/{_NDNS['profile_id']}/analytics/devices?from=-1d&limit=10",
                                headers=headers, timeout=5)
                return {"status": r1.json().get("data", []), "devices": r2.json().get("data", [])}
            except Exception as e:
                return {"error": str(e)}

    # ── Speedtest ─────────────────────────────────────────────────────────────

    speed_jobs = {}

    @dashboard.get("/api/speedtest/history")
    def get_speed_history():
        return load_history(SPEED_HISTORY_FILE)

    @dashboard.get("/api/speedtest/servers")
    def get_speedtest_servers():
        try:
            result = subprocess.run(proxmox_ssh() + ["/root/go/bin/speedtest-go --list"],
                                    capture_output=True, text=True, timeout=30)
            servers = []
            for line in result.stdout.strip().split("\n"):
                m = re.match(r"\[(\d+)\]\s+([\d.]+km)\s+(\d+ms)\s+(.+?)\s+by\s+(.+)", line.strip())
                if m:
                    servers.append({"id": m.group(1), "distance": m.group(2), "ping": m.group(3),
                                     "location": m.group(4).strip(), "name": m.group(5).strip()})
            return {"servers": servers[:20]}
        except Exception as e:
            return {"error": str(e)}

    @dashboard.get("/api/speedtest/start")
    def start_speedtest_job(server_id: str = None):
        if server_id is not None and not re.match(r'^\d+$', server_id):
            return JSONResponse({"error": "Invalid server_id"}, status_code=400)
        job_id = str(_uuid.uuid4())[:8]
        speed_jobs[job_id] = {"lines": [], "done": False, "result": None}

        def run():
            remote_cmd = "/root/go/bin/speedtest-go"
            if server_id:
                remote_cmd += f" --server {server_id}"
            proc = subprocess.Popen(proxmox_ssh() + [remote_cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output_lines = []
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
                if clean:
                    speed_jobs[job_id]["lines"].append("\n" + clean)
                    output_lines.append(clean)
            proc.wait()
            dm = um = pm = sm = None
            for cl in output_lines:
                if not dm:
                    m = re.search(r"Download:\s+([\d.]+)\s+Mbps", cl)
                    if m: dm = m
                if not um:
                    m = re.search(r"Upload:\s+([\d.]+)\s+Mbps", cl)
                    if m: um = m
                if not pm:
                    m = re.search(r"Latency:\s+([\d.]+)ms", cl)
                    if m: pm = m
                if not sm:
                    m = re.search(r"Test Server:.*?\[\d+\]\s+[\d.]+km\s+(.+?)\s+by\s+(.+)", cl)
                    if m: sm = m
            if dm and um:
                entry = {"time": datetime.now().strftime("%d.%m %H:%M"),
                          "download": round(float(dm.group(1)), 1),
                          "upload": round(float(um.group(1)), 1),
                          "ping": round(float(pm.group(1)) if pm else 0, 1),
                          "server": (sm.group(1).strip() + " by " + sm.group(2).strip()) if sm else "N/A"}
                save_history(SPEED_HISTORY_FILE, entry)
                speed_jobs[job_id]["result"] = entry
            speed_jobs[job_id]["done"] = True

        _threading.Thread(target=run, daemon=True).start()
        return {"job_id": job_id}

    @dashboard.get("/api/speedtest/poll/{job_id}")
    def poll_speedtest_job(job_id: str):
        job = speed_jobs.get(job_id)
        if not job:
            return {"error": "Job not found"}
        lines = job["lines"][:]
        job["lines"] = []
        return {"lines": lines, "done": job["done"], "result": job.get("result")}

    # ── LXC wizard ────────────────────────────────────────────────────────────

    lxc_jobs = {}

    def lxc_generate_script(params):
        ct_id = params.get("ct_id", "202")
        hostname = params.get("hostname", "webdev-new")
        ip = params.get("ip", "10.0.1.X")
        git_name = params.get("git_name", "")
        git_email = params.get("git_email", "")
        ssh_key = params.get("ssh_key", "").strip()
        pkgs = params.get("packages", [])
        L = [
            "#!/bin/bash",
            f"# LXC Setup — CT{ct_id} | {hostname}",
            "set -e",
            "export DEBIAN_FRONTEND=noninteractive",
            "log() { echo -e \"\\033[1;33m>>> $1\\033[0m\"; }",
            "ok()  { echo -e \"\\033[0;32m✓ $1\\033[0m\"; }",
            "",
            "log \"Aktualizace systému...\"",
            "apt-get update -qq && apt-get upgrade -y -q",
            "apt-get install -y -q curl wget git nano unzip build-essential lsb-release",
            "ok \"Základní balíčky nainstalovány\"",
            "",
        ]
        if "docker" in pkgs:
            L += [
                "log \"Instalace Dockeru...\"",
                "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg",
                "echo \"deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] "
                "https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable\" "
                "| tee /etc/apt/sources.list.d/docker.list > /dev/null",
                "apt-get update -qq && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin",
                "systemctl stop docker && rm -rf /var/lib/docker && mkdir -p /etc/docker",
                "printf '{\\n  \"storage-driver\": \"overlay2\"\\n}\\n' > /etc/docker/daemon.json",
                "systemctl start docker && systemctl enable docker",
                f"docker run --rm hello-world > /dev/null 2>&1 && ok \"Docker funguje\" "
                f"|| echo \"VAROVÁNÍ: Docker test selhal — zkontroluj /etc/pve/lxc/{ct_id}.conf\"",
                "",
            ]
        if "node" in pkgs:
            L += [
                "log \"Instalace NVM a Node.js LTS...\"",
                "export NVM_DIR=\"$HOME/.nvm\"",
                "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash",
                r'[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"',
                "echo 'export NVM_DIR=\"$HOME/.nvm\"' >> ~/.bashrc",
                r'echo "[ -s \"$NVM_DIR/nvm.sh\" ] && \. \"$NVM_DIR/nvm.sh\"" >> ~/.bashrc',
                "nvm install --lts && nvm use --lts && nvm alias default node",
                "ok \"Node.js $(node --version) nainstalován\"",
                "",
            ]
        if "pnpm" in pkgs:
            L += [
                "log \"Instalace pnpm...\"",
                "npm install -g pnpm",
                "ok \"pnpm $(pnpm --version) nainstalován\"",
                "",
            ]
        if "vercel" in pkgs:
            L += [
                "log \"Instalace Vercel CLI...\"",
                "npm install -g vercel",
                "ok \"Vercel CLI nainstalován\"",
                "",
            ]
        if "claude" in pkgs:
            L += [
                "log \"Instalace Claude Code...\"",
                "npm install -g @anthropic-ai/claude-code",
                "ok \"Claude Code nainstalován\"",
                "",
            ]
        if "micro" in pkgs:
            L += [
                "log \"Instalace micro editoru...\"",
                "apt-get install -y micro",
                "ok \"micro nainstalován\"",
                "",
            ]
        if "supabase" in pkgs:
            L += [
                "log \"Instalace Supabase CLI...\"",
                "npm install -g supabase",
                "ok \"Supabase CLI $(supabase --version) nainstalován\"",
                "",
            ]
        if git_name:
            L.append(f"git config --global user.name {shlex.quote(git_name)}")
        if git_email:
            L.append(f"git config --global user.email {shlex.quote(git_email)}")
        if git_name or git_email:
            L += ["git config --global init.defaultBranch main", "ok \"Git nakonfigurován\"", ""]
        if ssh_key:
            L += [
                "mkdir -p ~/.ssh && chmod 700 ~/.ssh",
                f"printf '%s\\n' {shlex.quote(ssh_key)} >> ~/.ssh/authorized_keys",
                "chmod 600 ~/.ssh/authorized_keys",
                "ok \"SSH klíč přidán do authorized_keys\"",
                "",
            ]
        else:
            eml = git_email or "webdev@lxc"
            L += [
                f"ssh-keygen -t ed25519 -C {shlex.quote(eml)} -f ~/.ssh/id_ed25519 -N \"\"",
                "echo \"\" && echo \"══ Přidej tento klíč na GitHub → Settings → SSH Keys ══\"",
                "cat ~/.ssh/id_ed25519.pub",
                "echo \"══ Po přidání: ssh -T git@github.com ══\"",
                "",
            ]
        if "supabase" in pkgs:
            L += [
                "# ── Supabase — per-projekt instrukce ────────────────────────────────",
                "# Předpoklad: Docker musí běžet (supabase start ho interně využívá)",
                "#",
                "# Nový projekt:",
                "#   mkdir muj-projekt && cd muj-projekt",
                "#   supabase init          # vytvoří adresář supabase/ s konfigurací",
                "#   supabase start         # spustí lokální PG, Auth, Storage, Studio...",
                "#   supabase status        # zobrazí API URL, anon klíč, service_role klíč",
                "#",
                "# Propojení se Supabase Cloud:",
                "#   supabase login                        # přihlášení do Supabase Cloud",
                "#   supabase link --project-ref <ref>     # ref je v URL dashboardu",
                "#   supabase db push                      # sync schématu do cloudu",
                "#   supabase db pull                      # stáhni schéma z cloudu",
                "#   supabase stop                         # zastavení lokálního stacku",
                "",
            ]
        L += [
            "echo \"\"",
            f"echo -e \"\\033[0;32m══ Setup dokončen! {hostname} je připraven. ══\\033[0m\"",
            "echo \"\"",
        ]
        if "docker" in pkgs:
            L.append("echo \"  Docker:  $(docker --version)\"")
        if "node" in pkgs:
            L.append("echo \"  Node.js: $(node --version)\"")
        L.append(f"echo \"  SSH:     ssh root@{ip}\"")
        return "\n".join(L)

    def lxc_worker(job_id, params):
        job = lxc_jobs[job_id]
        ssh = proxmox_ssh()
        node = PROXMOX["node"]

        def log(msg): job["lines"].append(msg)
        def run_ssh(cmd, timeout=60):
            r = subprocess.run(ssh + [cmd], capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout + r.stderr).strip()

        try:
            ct_id = str(params["ct_id"])
            if not re.match(r'^\d+$', ct_id):
                raise Exception("Neplatné CT ID")
            hostname = params.get("hostname", "new-lxc")
            if not re.match(r'^[a-zA-Z0-9\-]{1,63}$', hostname):
                raise Exception("Neplatný hostname")
            ip = params.get("ip", "10.0.1.X")
            if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
                raise Exception("Neplatná IP adresa")
            ram = int(params.get("ram", 2048))
            cores = int(params.get("cores", 2))
            disk = int(params.get("disk", 8))
            password = params.get("password", "changeme123")
            gw = params.get("gateway", "10.0.1.1")
            if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', gw):
                raise Exception("Neplatná gateway")

            log(f"[1/9] Checking CT ID {ct_id}...")
            rc, out = run_ssh(f"pvesh get /nodes/{node}/lxc --output-format json")
            existing = json.loads(out) if rc == 0 and out else []
            if ct_id in [str(v.get("vmid", "")) for v in existing]:
                raise Exception(f"CT ID {ct_id} is taken!")
            log(f"  OK — CT ID {ct_id} free")

            log("[2/9] Finding Ubuntu 22.04 template...")
            rc, out = run_ssh(f"pvesh get /nodes/{node}/storage/local/content --content vztmpl --output-format json")
            templates = json.loads(out) if rc == 0 and out else []
            tmpl = next((t["volid"] for t in templates if "ubuntu-22.04" in t.get("volid", "").lower()), None)
            if not tmpl:
                raise Exception("Ubuntu 22.04 template not found!")
            log(f"  Template: {tmpl}")

            log(f"[3/9] Creating LXC {ct_id}...")
            create_cmd = (f"pvesh create /nodes/{node}/lxc --vmid {ct_id} --hostname {hostname} --ostemplate {shlex.quote(tmpl)} "
                          f"--rootfs local-lvm:{disk} --memory {ram} --cores {cores} "
                          f"--net0 name=eth0,bridge=vmbr0,ip={ip}/24,gw={gw} "
                          f"--unprivileged 0 --features nesting=1 --password {shlex.quote(password)} --start 0")
            rc, out = run_ssh(create_cmd, timeout=120)
            if rc != 0:
                raise Exception(f"pvesh create failed: {out}")

            log("[4/9] Applying Docker config...")
            docker_conf = "lxc.apparmor.profile: unconfined\\nlxc.cgroup2.devices.allow: a\\nlxc.cap.drop:"
            run_ssh(f"printf '{docker_conf}\\n' >> /etc/pve/lxc/{ct_id}.conf")

            log(f"[5/9] Starting LXC {ct_id}...")
            rc, out = run_ssh(f"pvesh post /nodes/{node}/lxc/{ct_id}/status/start", timeout=30)
            if rc != 0:
                raise Exception(f"Start failed: {out}")

            log("[6/9] Waiting for boot (max 90s)...")
            booted = False
            for attempt in range(18):
                time.sleep(5)
                rc, _ = run_ssh(f"pct exec {ct_id} -- echo ok", timeout=10)
                if rc == 0:
                    booted = True
                    log(f"  Boot OK ({(attempt+1)*5}s)")
                    break
            if not booted:
                raise Exception("Container did not boot in 90s!")

            log("[7/9] Generating setup.sh...")
            script = lxc_generate_script(params)
            script_path = os.path.join(INSTALL_PATH, "setup.sh")
            with open(script_path, "w") as f:
                f.write(script)

            log("[8/9] Copying setup.sh to LXC...")
            scp_cmd = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
            if PROXMOX["ssh_auth"] == "key":
                scp_cmd += ["-i", PROXMOX["ssh_key_path"]]
            scp_cmd += [script_path, f"root@{PROXMOX['ip']}:/tmp/setup-lxc.sh"]
            scp = subprocess.run(scp_cmd, capture_output=True, timeout=15)
            if scp.returncode != 0:
                raise Exception("SCP failed")
            run_ssh(f"pct push {ct_id} /tmp/setup-lxc.sh /root/setup.sh && chmod +x /root/setup.sh", timeout=20)

            log("[9/9] Running setup.sh...")
            log("=" * 48)
            proc = subprocess.Popen(ssh + [f"pct exec {ct_id} -- bash /root/setup.sh"],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
                if clean:
                    job["lines"].append(clean)
            proc.wait()
            log("=" * 48)
            log(f"DONE! CT{ct_id} ({hostname}) ready. SSH: ssh root@{ip}")
            job["done"] = True
        except Exception as e:
            job["lines"].append(f"ERROR: {e}")
            job["error"] = str(e)
            job["done"] = True

    @dashboard.post("/api/lxc/create")
    def lxc_create(data: dict):
        ct_id = data.get("ct_id")
        if not ct_id or not re.match(r'^\d+$', str(ct_id)):
            return JSONResponse({"error": "ct_id must be a number"}, status_code=400)
        job_id = str(_uuid.uuid4())[:8]
        lxc_jobs[job_id] = {"lines": [], "done": False, "error": None, "ct_id": str(ct_id)}
        _threading.Thread(target=lxc_worker, args=(job_id, data), daemon=True).start()
        return {"job_id": job_id}

    @dashboard.get("/api/lxc/poll/{job_id}")
    def lxc_poll(job_id: str):
        job = lxc_jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        lines = job["lines"][:]
        job["lines"] = []
        return {"lines": lines, "done": job["done"], "error": job.get("error")}

    # ── Main page ─────────────────────────────────────────────────────────────

    @dashboard.get("/", response_class=HTMLResponse)
    def index():
        with open(os.path.join(INSTALL_PATH, "index.html")) as f:
            return f.read()

    @dashboard.get("/setup", response_class=HTMLResponse)
    def setup_redirect():
        return RedirectResponse("/")

    return dashboard


# ── Entry point ───────────────────────────────────────────────────────────────

if os.path.exists(CONFIG_FILE):
    app = _load_dashboard_app()
else:
    app = _load_installer_app()
