"""
monitor-public installer wizard
Runs only until config.json is created, then redirects to main app.
"""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import re
import sys
import hashlib
import subprocess
import socket
import paramiko
import io

INSTALL_PATH = os.environ.get("INSTALL_PATH", "/opt/monitor-public")
CONFIG_FILE = os.path.join(INSTALL_PATH, "config.json")
KEYS_DIR = os.path.join(INSTALL_PATH, "keys")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── helpers ────────────────────────────────────────────────────────────────

def _read_html() -> str:
    path = os.path.join(INSTALL_PATH, "installer.html")
    with open(path) as f:
        return f.read()


def _ssh_test_password(ip: str, user: str, password: str, port: int = 22) -> dict:
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=port, username=user, password=password, timeout=8)
        _, stdout, _ = client.exec_command("hostname")
        hostname = stdout.read().decode().strip()
        client.close()
        return {"ok": True, "hostname": hostname}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _ssh_test_key(ip: str, user: str, key_path: str, port: int = 22) -> dict:
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=port, username=user, key_filename=key_path, timeout=8)
        _, stdout, _ = client.exec_command("hostname")
        hostname = stdout.read().decode().strip()
        client.close()
        return {"ok": True, "hostname": hostname}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _generate_keypair(name: str) -> dict:
    """Generate an ed25519 keypair, return paths and public key."""
    os.makedirs(KEYS_DIR, exist_ok=True)
    priv = os.path.join(KEYS_DIR, name)
    pub = priv + ".pub"
    if os.path.exists(priv):
        os.remove(priv)
    if os.path.exists(pub):
        os.remove(pub)
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", priv, "-N", "", "-C", f"monitor-public-{name}"],
        capture_output=True, check=True
    )
    os.chmod(priv, 0o600)
    with open(pub) as f:
        pub_key = f.read().strip()
    return {"private": priv, "public": pub_key}


# ── routes ─────────────────────────────────────────────────────────────────

@app.get("/locales/{lang}.json")
def get_locale(lang: str):
    """Serve locale files for the wizard UI."""
    if lang not in {"en", "cs"}:
        return JSONResponse({"error": "Not found"}, status_code=404)
    path = os.path.join(INSTALL_PATH, "locales", f"{lang}.json")
    if not os.path.exists(path):
        return JSONResponse({"error": "Not found"}, status_code=404)
    with open(path) as f:
        return JSONResponse(json.load(f))


@app.get("/setup", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def wizard():
    if os.path.exists(CONFIG_FILE):
        return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Hotovo</title>
<style>body{background:#0d1b2a;color:#eee;font-family:monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{background:#16213e;border:1px solid #0f3460;border-radius:12px;padding:40px;text-align:center;max-width:400px}
h2{color:#6bcb77;margin-bottom:16px}p{color:#888;font-size:13px;line-height:1.6}
code{background:#0d1b2a;padding:6px 12px;border-radius:4px;color:#00d4ff;display:block;margin:12px 0;font-size:12px}
</style></head><body><div class="box">
<h2>✓ Konfigurace uložena!</h2>
<p>Restartuj service a znovu otevři dashboard:</p>
<code>sudo systemctl restart monitor-public</code>
<p style="margin-top:16px">Pokud service není nainstalovaná:</p>
<code>sudo cp /opt/monitor-public/monitor-public.service /etc/systemd/system/<br>sudo systemctl daemon-reload<br>sudo systemctl enable --now monitor-public</code>
</div></body></html>""")
    return _read_html()


@app.get("/api/installer/check")
def check_system():
    """Step 1: System check."""
    issues = []

    # Python version
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 11):
        issues.append(f"Python {py} — doporučena 3.11+")

    # sshpass
    sshpass_ok = subprocess.run(["which", "sshpass"], capture_output=True).returncode == 0

    # paramiko
    try:
        import paramiko as _p
        paramiko_ok = True
    except ImportError:
        paramiko_ok = False
        issues.append("paramiko není nainstalován (pip install paramiko)")

    # Local IP
    try:
        local_ip = subprocess.run(
            ["ip", "route", "get", "1"], capture_output=True, text=True
        ).stdout.split()[6]
    except Exception:
        local_ip = socket.gethostbyname(socket.gethostname())

    return {
        "python": py,
        "sshpass": sshpass_ok,
        "paramiko": paramiko_ok,
        "local_ip": local_ip,
        "issues": issues,
        "ok": len(issues) == 0,
    }


@app.post("/api/installer/generate_key")
async def generate_key(request: Request):
    """Generate SSH keypair for a given role (e.g. 'proxmox', 'router')."""
    data = await request.json()
    name = data.get("name", "id_monitor")
    if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', name):
        return JSONResponse({"ok": False, "error": "Invalid key name"}, status_code=400)
    result = _generate_keypair(name)
    return {"ok": True, "public_key": result["public"], "key_path": result["private"]}


@app.post("/api/installer/test_ssh")
async def test_ssh(request: Request):
    """Test SSH connection."""
    data = await request.json()
    ip = data.get("ip", "")
    user = data.get("user", "root")
    port = int(data.get("port", 22))
    auth = data.get("auth", "password")

    if not ip:
        return JSONResponse({"ok": False, "error": "IP není zadána"}, status_code=400)

    if auth == "password":
        password = data.get("password", "")
        return _ssh_test_password(ip, user, password, port)
    else:
        key_path = data.get("key_path", "")
        if not key_path:
            return JSONResponse({"ok": False, "error": "Cesta ke klíči není zadána"}, status_code=400)
        real_key = os.path.realpath(key_path)
        real_keys_dir = os.path.realpath(KEYS_DIR)
        if not real_key.startswith(real_keys_dir + os.sep):
            return JSONResponse({"ok": False, "error": "Neplatná cesta ke klíči"}, status_code=400)
        return _ssh_test_key(ip, user, key_path, port)


def _generate_dev_script(packages: list, install_path: str) -> str:
    """Generate a bash script that installs selected dev tools."""
    log = f"{install_path}/dev_install.log"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f'LOG="{log}"',
        'log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }',
        'log "=== Dev install started ==="',
        "export DEBIAN_FRONTEND=noninteractive",
    ]

    if "node" in packages:
        lines += [
            'log "Installing Node.js LTS via NVM..."',
            "export NVM_DIR=\"$HOME/.nvm\"",
            "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash",
            r'[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"',
            "nvm install --lts",
            "nvm use --lts",
            "nvm alias default node",
            # Make node/npm available system-wide for subsequent installs
            r'NODE_BIN=$(dirname $(nvm which current))',
            r'export PATH="$NODE_BIN:$PATH"',
            'log "Node.js $(node --version) installed"',
        ]

    if "pnpm" in packages:
        lines += [
            'log "Installing pnpm..."',
            r'[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"',
            "npm install -g pnpm",
            'log "pnpm installed"',
        ]

    if "vercel" in packages:
        lines += [
            'log "Installing Vercel CLI..."',
            r'[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"',
            "npm install -g vercel",
            'log "Vercel CLI installed"',
        ]

    if "supabase" in packages:
        lines += [
            'log "Installing Supabase CLI..."',
            r'[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"',
            "npm install -g supabase",
            'log "Supabase CLI installed"',
        ]

    if "claude" in packages:
        lines += [
            'log "Installing Claude Code..."',
            r'[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"',
            "npm install -g @anthropic-ai/claude-code",
            'log "Claude Code installed"',
        ]

    if "bun" in packages:
        lines += [
            'log "Installing Bun..."',
            "curl -fsSL https://bun.sh/install | bash",
            'log "Bun installed"',
        ]

    if "docker" in packages:
        lines += [
            'log "Installing Docker..."',
            "apt-get update -qq",
            "apt-get install -y ca-certificates curl gnupg lsb-release",
            "install -m 0755 -d /etc/apt/keyrings",
            "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg",
            'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] '
            'https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" '
            '> /etc/apt/sources.list.d/docker.list',
            "apt-get update -qq",
            "apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
            "mkdir -p /etc/docker",
            'echo \'{"storage-driver":"overlay2"}\' > /etc/docker/daemon.json',
            "systemctl enable --now docker",
            'log "Docker installed"',
        ]

    if "redis" in packages:
        lines += [
            'log "Installing Redis..."',
            "apt-get install -y redis-server",
            "systemctl enable --now redis-server",
            'log "Redis installed"',
        ]

    if "python" in packages:
        lines += [
            'log "Installing Python 3 + pip + venv..."',
            "apt-get install -y python3-pip python3-venv python3-full",
            'log "Python tools installed"',
        ]

    if "micro" in packages:
        lines += [
            'log "Installing micro editor..."',
            "apt-get install -y micro",
            'log "micro installed"',
        ]

    lines.append('log "=== Dev install complete ==="')
    return "\n".join(lines) + "\n"


@app.post("/api/installer/save")
async def save_config(request: Request):
    """Final step: save config.json and switch to dashboard mode."""
    data = await request.json()

    # Build config
    username = data.get("username", "admin")
    password = data.get("password", "")
    if not password:
        return JSONResponse({"ok": False, "error": "Heslo nesmí být prázdné"}, status_code=400)

    port = int(data.get("port", 8091))
    if not (1024 <= port <= 65535):
        return JSONResponse({"ok": False, "error": "Port musí být mezi 1024 a 65535"}, status_code=400)

    password_hash = hashlib.sha256(password.encode()).hexdigest()

    config = {
        "dashboard_name": data.get("dashboard_name", "Homelab"),
        "auth": {
            "username": username,
            "password_hash": password_hash,
        },
        "port": port,
        "install_path": INSTALL_PATH,
        "proxmox": {
            "ip": data.get("proxmox_ip", ""),
            "node": data.get("proxmox_node", "proxmox"),
            "ssh_user": data.get("proxmox_ssh_user", "root"),
            "ssh_auth": data.get("proxmox_ssh_auth", "password"),
            "ssh_password": data.get("proxmox_ssh_password", ""),
            "ssh_key_path": data.get("proxmox_ssh_key_path", ""),
            "ssh_port": int(data.get("proxmox_ssh_port", 22)),
        },
        "modules": {
            "home_assistant": {
                "enabled": bool(data.get("ha_enabled", False)),
                "ip": data.get("ha_ip", ""),
                "ssh_user": data.get("ha_ssh_user", "root"),
                "ssh_password": data.get("ha_ssh_password", ""),
                "ssh_port": int(data.get("ha_ssh_port", 22)),
            },
            "router": {
                "enabled": bool(data.get("router_enabled", False)),
                "ip": data.get("router_ip", ""),
                "ssh_port": int(data.get("router_ssh_port", 22)),
                "ssh_user": data.get("router_ssh_user", "root"),
                "ssh_auth": data.get("router_ssh_auth", "key"),
                "ssh_key_path": data.get("router_ssh_key_path", ""),
                "subnet": data.get("router_subnet", ""),
            },
            "cloudflare": {
                "enabled": bool(data.get("cf_enabled", False)),
                "token": data.get("cf_token", ""),
                "account_id": data.get("cf_account_id", ""),
                "zone_id": data.get("cf_zone_id", ""),
                "tunnel_id": data.get("cf_tunnel_id", ""),
            },
            "nextdns": {
                "enabled": bool(data.get("nextdns_enabled", False)),
                "api_key": data.get("nextdns_api_key", ""),
                "profile_id": data.get("nextdns_profile_id", ""),
            },
        },
        "services": data.get("services", []),
        "wol_devices": data.get("wol_devices", []),
    }

    # Write config (restrict permissions so only root can read credentials)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_FILE, 0o600)

    # Update service file port if it differs from current
    service_path = "/etc/systemd/system/monitor-public.service"
    if os.path.exists(service_path):
        with open(service_path) as f:
            svc = f.read()
        svc_updated = re.sub(r'--port \d+', f'--port {port}', svc)
        if svc_updated != svc:
            with open(service_path, "w") as f:
                f.write(svc_updated)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True)

    # Background dev tools install (if any selected)
    dev_packages = data.get("dev_packages", [])
    allowed_packages = {"node","pnpm","vercel","supabase","claude","bun","docker","redis","python","micro"}
    dev_packages = [p for p in dev_packages if p in allowed_packages]
    if dev_packages:
        dev_script = _generate_dev_script(dev_packages, INSTALL_PATH)
        dev_script_path = os.path.join(INSTALL_PATH, "dev_install.sh")
        with open(dev_script_path, "w") as f:
            f.write(dev_script)
        os.chmod(dev_script_path, 0o700)
        subprocess.Popen(
            ["bash", dev_script_path],
            start_new_session=True,
            stdout=open(os.path.join(INSTALL_PATH, "dev_install.log"), "w"),
            stderr=subprocess.STDOUT,
        )

    # Restart service to switch from installer to dashboard
    subprocess.Popen(
        ["systemctl", "restart", "monitor-public"],
        start_new_session=True
    )

    return {"ok": True, "message": "Konfigurace uložena, dashboard se spouští..."}
