# proxmox-lxc-hud

> LXC provisioning wizard pro Proxmox VE na jedno kliknutí

🇬🇧 [English](README.md) | 🇨🇿 Česky

Lehký webový dashboard, který automatizuje celý životní cyklus vytváření a konfigurace LXC kontejnerů na Proxmoxu — od vytvoření až po plně nakonfigurovaný vývojový server, se sledováním průběhu v reálném čase.

---

## Problém

Nastavení nového LXC kontejneru na Proxmoxu obnáší příliš mnoho ručních kroků:

1. Vytvoř kontejner v Proxmox webovém rozhraní
2. SSH na Proxmox host, uprav `/etc/pve/lxc/{id}.conf` pro podporu Dockeru
3. Restartuj kontejner
4. Zkopíruj setup skript do kontejneru
5. SSH dovnitř, spusť skript, čekej
6. Doufej, že se nic nepokazilo potichu

**proxmox-lxc-hud tohle celé zredukuje na jedno kliknutí.**

---

## Co umí

### LXC Provisioning Wizard

Vyplň formulář, klikni **"Vytvořit LXC a nainstalovat"** — nástroj se postará o vše:

```
[1/9] Ověřuji CT ID...                      ✓ CT ID 203 je volné
[2/9] Hledám Ubuntu 22.04 šablonu...        ✓ local:vztmpl/ubuntu-22.04-...
[3/9] Vytvářím LXC kontejner...             ✓ Kontejner vytvořen (2CPU, 2GB, 8GB)
[4/9] Upravuji .conf pro Docker...          ✓ lxc.apparmor.profile přidán
[5/9] Startuji kontejner...                 ✓ Bootuje...
[6/9] Čekám na boot (max 90s)...            ✓ Připraven po 15s
[7/9] Generuji setup.sh...                  ✓ Skript připraven (4.2 KB)
[8/9] Kopíruji skript do kontejneru...      ✓ /root/setup.sh připraven
[9/9] Spouštím setup.sh (živý výstup)...

  >>> Aktualizace systému...
  ✓ Základní balíčky nainstalovány
  >>> Instalace Dockeru...
  ✓ Docker funguje
  >>> Instalace Node.js LTS...
  ✓ Node.js v22.x nainstalován
  ...

╔══════════════════════════════════════════╗
  Hotovo! SSH: ssh user@192.168.1.93
  Heslo: Xk9#mP2...
╚══════════════════════════════════════════╝
```

### Konfigurovatelné parametry

| Pole | Výchozí | Popis |
|------|---------|-------|
| CT ID | — | ID kontejneru v Proxmoxu |
| Hostname | — | Název kontejneru |
| IP adresa | — | Statická IP (automatická kontrola dostupnosti) |
| RAM | 2048 MB | Přidělená paměť |
| CPU jader | 2 | Počet vCPU |
| Disk | 8 GB | Velikost root filesystému |
| Heslo | generované | Automaticky nebo vlastní |

### Softwarové balíčky (volitelné)

- **Docker** — s overlay2 storage driverem, nakonfigurovaný pro LXC
- **Node.js LTS** — přes nvm
- **pnpm** — rychlejší správce balíčků
- **Vercel CLI** — nasazení přímo z kontejneru
- **Claude Code** — AI asistent pro programování
- **micro** — moderní terminálový editor
- Git konfigurace (jméno, email, SSH klíč nebo automatické vygenerování)

### Kontrola dostupnosti IP

Před spuštěním wizard pingne cílovou IP adresu a upozorní, pokud je již obsazená v síti.

### Ruční režim (záloha)

Pro uživatele, kteří preferují ruční nastavení, je k dispozici sbalená sekce **Ruční režim**:
- Krok za krokem pro úpravu `.conf`
- Generátor `setup.sh` s možnostmi kopírovat/stáhnout/uložit na server
- Připravené příkazy `pct push` + `pct exec`

---

## Architektura

```
Prohlížeč  ──→  Web UI (single-page HTML + JS)
                  │
                  ▼
              FastAPI (Python)
                  │
                  ├── SSH ──→  Proxmox Host (user@proxmox)
                  │              └── pvesh create/start/exec
                  │              └── pct push / pct exec
                  │
                  └── Lokální generování setup.sh
```

- **Backend**: Python (FastAPI), jeden soubor `app.py`
- **Frontend**: Single-page HTML/JS, bez frameworku, bez build kroku
- **Auth**: Cookie session (SHA-256 hash hesla)
- **Připojení k Proxmoxu**: SSH klíč

---

## Plánované funkce

- [ ] Auto-install: webový instalátor se zadáním proměnných (IP Proxmoxu, SSH klíč, přihlašovací údaje)
- [ ] Výběr LXC šablony (nejen Ubuntu 22.04)
- [ ] Správa kontejnerů: start/stop/restart z dashboardu
- [ ] Monitoring zdrojů per-kontejner (CPU, RAM, disk)
- [ ] Automatické přidání SSH klíče na GitHub
- [ ] Integrace s 1Password CLI pro ukládání přihlašovacích údajů
- [ ] Podpora více Proxmox nodů
- [ ] Šablony kontejnerů (přednastavení: webdev, databáze, media server...)

---

## Aktuální stav

> **Alpha / Osobní použití** — provozováno na domácím Proxmox serveru.
> Repo vytvořeno: březen 2026.

LXC wizard je funkční. Projekt momentálně žije jako modul v rámci většího homelab dashboardu. Plán je extrahovat ho do samostatného instalovatelného nástroje.

---

## Screenshoty

### LXC Wizard — konfigurace a spuštění
![LXC Wizard](screenshots/lxc-wizard.png)

### Zálohy — správa Proxmox záloh
![Backups](screenshots/backups.png)

### Wake-on-LAN
![Wake-on-LAN](screenshots/wol.png)

---

## Související projekty

| Projekt | Zaměření |
|---------|----------|
| [Pulse](https://github.com/rcourtman/Pulse) | Proxmox monitoring dashboard |
| [proxmox-dashboard](https://github.com/anomixer/proxmox-dashboard) | Monitoring nodů/VM/LXC |
| [awesome-proxmox-ve](https://github.com/Corsinvest/awesome-proxmox-ve) | Kurátorský seznam Proxmox nástrojů |

**Mezera kterou tento projekt zaplňuje:** Žádný z výše uvedených projektů neautomatizuje *provisioning* LXC — pouze monitorují to, co už běží.

---

## Poznámky k vývoji

### Session log — březen 2026

**Co jsme postavili (první iterace, uvnitř homelab-dashboard):**
- LXC konfigurační stránka s generátorem skriptů (`lxcGenerate()`)
- Backend endpoint `POST /api/lxc/create` → 9-krokový background worker
- `GET /api/lxc/poll/{job_id}` pro live polling logu
- `POST /api/setup/save` → uloží skript lokálně + SCP na Proxmox
- `GET /setup.sh` → servíruje skript pro `curl | bash` instalace
- Kontrola dostupnosti IP přes existující `/api/ping` endpoint

**Opravené chyby:**
- `pct restart` → správný příkaz je `pct reboot`
- `PermitRootLogin` nenastaveno na čistém Ubuntu LXC → opraveno přes `sed -i '/PermitRootLogin/d' && echo "PermitRootLogin yes" >>`
- `curl` nedostupný v čistém kontejneru → přechod na `pct push` + `pct exec`
- `navigator.clipboard` nefunguje na HTTP → přidán `execCommand` fallback
- Interaktivní dialog `apt upgrade` pro openssh-server → opraveno přes `DEBIAN_FRONTEND=noninteractive` + `--force-confold`

**Zdrojové repo (privátní, celý homelab dashboard):** `github.com/pueblo78/homelab-dashboard`
