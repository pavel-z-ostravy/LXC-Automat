#!/bin/bash
# monitor-public installer
# Usage: curl -sSL https://raw.githubusercontent.com/pueblo78/monitor-public/main/install.sh | bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="/opt/monitor-public"
REPO_URL="https://github.com/pavel-z-ostravy/proxmox-lxc-hud.git"
SERVICE_NAME="monitor-public"
PORT=8090

log()  { echo -e "${CYAN}>>> $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err()  { echo -e "${RED}✗ $1${NC}"; exit 1; }

# --- Root check ---
if [ "$EUID" -ne 0 ]; then
    err "Spusť jako root: sudo bash install.sh"
fi

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║      monitor-public installer         ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════╝${NC}"
echo ""

# --- Závislosti ---
log "Kontroluji závislosti..."

apt-get update -qq

# Python 3.11+
if ! python3 --version 2>/dev/null | grep -qE "3\.(11|12|13)"; then
    log "Instaluji Python 3.11..."
    apt-get install -y -q python3 python3-pip python3-venv python3-full || true
fi
python3 --version >/dev/null 2>&1 || err "Python 3 není dostupný"
ok "Python $(python3 --version | cut -d' ' -f2)"

# git
if ! command -v git &>/dev/null; then
    log "Instaluji git..."
    apt-get install -y -q git
fi
ok "git $(git --version | cut -d' ' -f3)"

# sshpass
if ! command -v sshpass &>/dev/null; then
    log "Instaluji sshpass..."
    apt-get install -y -q sshpass
fi
ok "sshpass"

# smartmontools
if ! command -v smartctl &>/dev/null; then
    log "Instaluji smartmontools..."
    apt-get install -y -q smartmontools
fi
ok "smartmontools"

# wakeonlan / etherwake
if ! command -v etherwake &>/dev/null && ! python3 -c "import wakeonlan" 2>/dev/null; then
    apt-get install -y -q etherwake 2>/dev/null || true
fi

# --- Klonování repo ---
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Aktualizuji existující instalaci..."
    git -C "$INSTALL_DIR" pull origin main
else
    log "Klonuji repozitář do $INSTALL_DIR..."
    if [ -d "$INSTALL_DIR" ]; then
        warn "Adresář $INSTALL_DIR již existuje, zachovávám config.json a keys/"
        # Dočasně zálohy
        [ -f "$INSTALL_DIR/config.json" ] && cp "$INSTALL_DIR/config.json" /tmp/monitor-config-backup.json
        [ -d "$INSTALL_DIR/keys" ] && cp -r "$INSTALL_DIR/keys" /tmp/monitor-keys-backup
    fi
    git clone "$REPO_URL" "$INSTALL_DIR"
    # Obnovit zálohy
    [ -f /tmp/monitor-config-backup.json ] && cp /tmp/monitor-config-backup.json "$INSTALL_DIR/config.json"
    [ -d /tmp/monitor-keys-backup ] && cp -r /tmp/monitor-keys-backup "$INSTALL_DIR/keys"
fi
ok "Repozitář připraven v $INSTALL_DIR"

# --- Python venv ---
log "Nastavuji Python venv..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
ok "Python závislosti nainstalovány"

# --- Systemd service ---
log "Nastavuji systemd service..."
cp "$INSTALL_DIR/monitor-public.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
ok "Systemd service $SERVICE_NAME nastaven"

# --- Zjisti lokální IP ---
LOCAL_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Instalace dokončena!          ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""

# --- Spuštění ---
if [ -f "$INSTALL_DIR/config.json" ]; then
    log "Existující config.json nalezen, spouštím dashboard..."
    systemctl restart "$SERVICE_NAME"
    ok "Dashboard běží"
    echo ""
    echo -e "  Dashboard: ${CYAN}http://${LOCAL_IP}:${PORT}${NC}"
else
    log "Spouštím installer wizard..."
    systemctl start "$SERVICE_NAME"
    echo ""
    echo -e "  ${YELLOW}Otevři prohlížeč a dokonči konfiguraci:${NC}"
    echo -e "  ${CYAN}http://${LOCAL_IP}:${PORT}/setup${NC}"
fi
echo ""
