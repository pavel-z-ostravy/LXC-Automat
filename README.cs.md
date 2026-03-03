# proxmox-lxc-hud

> Self-hosted homelab dashboard s webovým instalátorem

🇬🇧 [English](README.md) | 🇨🇿 Česky

Config-driven homelab dashboard pro Proxmox + volitelné moduly (Home Assistant, Router, Cloudflare, NextDNS). Instalace jedním příkazem — webový wizard tě provede celým nastavením, žádné ruční editování konfiguračních souborů.

---

## Rychlá instalace

```bash
curl -sSL https://raw.githubusercontent.com/pavel-z-ostravy/proxmox-lxc-hud/main/install.sh | sudo bash
```

Pak otevři `http://<IP-serveru>:8091/setup` a projdi wizard.

---

## Jak to funguje

### Dvě fáze startu

```
install.sh → [clone + deps + systemd] → wizard /setup (port 8091)
                                               ↓  (po dokončení wizardu)
                                         config.json → dashboard (port 8091)
```

App automaticky detekuje zda existuje `config.json`:
- **Chybí** → zobrazí instalační wizard
- **Existuje** → spustí plný dashboard

---

## Webový instalační wizard

7-krokový wizard — žádné SSH ani ruční editování souborů:

| Krok | Co nastavuješ |
|------|---------------|
| 1. Kontrola systému | Python, sshpass, paramiko |
| 2. Přihlašovací údaje | Název dashboardu, uživatel + heslo (SHA-256 hash, s generátorem) |
| 3. Proxmox | IP, node name, SSH auth (heslo **nebo** generovaný keypair) |
| 4. Moduly | Home Assistant, Router, Cloudflare, NextDNS (každý volitelný) |
| 5. Služby | URL adresy pro monitoring dostupnosti |
| 6. WoL zařízení | Název + MAC + IP pro Wake-on-LAN |
| 7. Review + Instalace | Zobrazí celý config (hesla skryta), uloží `config.json` |

### UX funkce wizardu

- **Přepínač jazyků EN/CS** — tlačítko v hlavičce, okamžitě přeloží všechny popisky, nápovědy a placeholdery
- **Název dashboardu** — dynamicky aktualizuje titulek prohlížeče i navbar dashboardu
- **Generátor hesel** — generuje 32/64/128-znakové heslo přes `crypto.getRandomValues`, zobrazí strength bar
- **Šedé výchozí hodnoty** — předvyplněná pole (`admin`, `proxmox`, `root`) jsou šedá dokud nezačneš psát
- **Generické placeholdery** — IP pole zobrazují `např. 192.168.1.x` místo konkrétních adres

### Generování SSH klíče (kroky 3 a 4)

Pro Proxmox a Router si můžeš vybrat mezi autentizací heslem nebo SSH klíčem. Při výběru klíče wizard vygeneruje ed25519 keypair, zobrazí veřejný klíč s tlačítkem **Kopírovat** a řekne ti přesně kam ho vložit (`~/.ssh/authorized_keys`).

---

## Moduly dashboardu

Všechny moduly jsou **volitelné** — neaktivní se v UI úplně skryjí.

| Modul | Co zobrazuje |
|-------|-------------|
| **Proxmox** | CPU, RAM, disk, procesy, sensory, zálohy, speedtest |
| **Home Assistant** | Statistiky HA VM přes SSH |
| **Router** | Rychlosti sítě per-zařízení přes conntrack |
| **Cloudflare** | Stav tunnelu, DNS záznamy, cloudflared metriky |
| **NextDNS** | DNS statistiky, blokované domény, přehled per-zařízení |
| **Služby** | HTTP kontrola dostupnosti nakonfigurovaných URL |
| **Wake-on-LAN** | Ping stav + WoL tlačítko pro nakonfigurovaná zařízení |
| **LXC Wizard** | Provisioning LXC kontejneru na jedno kliknutí (viz níže) |

---

## LXC Provisioning Wizard

Vyplň formulář, klikni **"Vytvořit LXC a nainstalovat"** — nástroj se postará o vše:

```
[1/9] Ověřuji CT ID...                      ✓ CT ID 203 je volné
[2/9] Hledám Ubuntu 22.04 šablonu...        ✓ local:vztmpl/ubuntu-22.04-...
[3/9] Vytvářím LXC kontejner...             ✓ Kontejner vytvořen (2CPU, 2GB, 8GB)
[4/9] Upravuji .conf pro Docker...          ✓ lxc.apparmor.profile přidán
[5/9] Startuji kontejner...                 ✓ Bootuje...
[6/9] Čekám na boot (max 90s)...            ✓ Připraven po 15s
[7/9] Generuji setup.sh...                  ✓ Skript připraven
[8/9] Kopíruji skript do kontejneru...      ✓ /root/setup.sh připraven
[9/9] Spouštím setup.sh (živý výstup)...

  >>> Aktualizace systému...
  ✓ Základní balíčky nainstalovány
  >>> Instalace Dockeru...
  ✓ Docker funguje
  ...

╔══════════════════════════════════════════╗
  Hotovo! SSH: ssh root@192.168.1.93
╚══════════════════════════════════════════╝
```

**Volitelné balíčky:** Docker, Node.js LTS, pnpm, Vercel CLI, Claude Code, micro editor, Git konfigurace

---

## Architektura

```
Prohlížeč  ──→  Web UI (single-page HTML + JS)
                  │
                  ▼
              FastAPI (Python)  ←── config.json
                  │
                  ├── SSH ──→  Proxmox host
                  │              └── pvesh, pct, vzdump, smartctl
                  │
                  ├── SSH ──→  Home Assistant VM  (pokud aktivní)
                  ├── SSH ──→  Router              (pokud aktivní)
                  ├── HTTPS ──→ Cloudflare API     (pokud aktivní)
                  └── HTTPS ──→ NextDNS API        (pokud aktivní)
```

- **Backend**: Python 3.11+ / FastAPI / Uvicorn
- **Frontend**: Single-page HTML+JS, bez frameworku, bez build kroku
- **Auth**: Cookie session, SHA-256 hash hesla, nikdy neuloženo v plaintextu
- **Config**: `config.json` — gitignored, generovaný wizardem
- **SSH klíče**: adresář `keys/` — gitignored, generovaný wizardem

---

## Bezpečnost

- `config.json` a `keys/` jsou gitignored — credentials se nikdy nedostanou do repo
- Hesla uložena pouze jako SHA-256 hash
- Cloudflare/NextDNS tokeny se nikdy nelogují
- SSH klíče mají práva `600`

---

## Struktura souborů

```
/opt/monitor-public/
├── install.sh           # curl | bash vstupní bod
├── installer.py         # backend wizardu (FastAPI)
├── installer.html       # UI wizardu (vícekrokový formulář)
├── app.py               # backend dashboardu (config-driven)
├── index.html           # frontend dashboardu
├── locales/
│   ├── en.json          # anglické překlady
│   └── cs.json          # české překlady
├── requirements.txt
├── monitor-public.service
├── keys/                # SSH klíče generované wizardem (gitignored)
└── config.json          # generovaný wizardem (gitignored)
```

---

## Screenshoty

### LXC Wizard — konfigurace a spuštění
![LXC Wizard](screenshots/lxc-wizard.png)

### Zálohy — správa Proxmox záloh
![Backups](screenshots/backups.png)

### Wake-on-LAN
![Wake-on-LAN](screenshots/wol.png)

---

## Plánované funkce

- [ ] Výběr LXC šablony (nejen Ubuntu 22.04)
- [ ] Správa kontejnerů: start/stop/restart z dashboardu
- [ ] Monitoring zdrojů per-kontejner (CPU, RAM, disk)
- [ ] Podpora více Proxmox nodů
- [ ] Šablony kontejnerů (přednastavení: webdev, databáze, media server...)
- [ ] Opětovné spuštění wizardu pro úpravu configu

---

## Poznámky k vývoji

### Session log — březen 2026

**První iterace (uvnitř privátního homelab-dashboard):**
- LXC konfigurační stránka s generátorem skriptů
- `POST /api/lxc/create` → 9-krokový background worker s live polling logu
- `POST /api/setup/save` + `GET /setup.sh`
- Kontrola dostupnosti IP

**Druhá iterace — extrakce do samostatného veřejného repo:**
- Webový instalační wizard (7 kroků, `installer.py` + `installer.html`)
- Config-driven `app.py` — všechny credentials/IP adresy z `config.json`
- Podmínečná registrace endpointů dle aktivních modulů
- `install.sh` one-command instalátor
- Frontend skrývá neaktivní sekce dle konfigurace
- WoL zařízení načítána dynamicky z configu

**Opravené chyby:**
- `pct restart` → správný příkaz je `pct reboot`
- Chyběl `python-multipart` → FastAPI bez něj neumí zpracovat login formulář
- Redirect smyčka po dokončení wizardu → nahrazeno stránkou s instrukcemi pro restart
- Konflikt portů s existující monitor service → změněno na port 8091

**Třetí iterace — UX vylepšení wizardu:**
- Přepínač jazyků EN/CS, překlady v `locales/` JSON souborech, funkce `t('key')`
- Pole pro název dashboardu → live aktualizace titulku prohlížeče i navbaru
- Generátor hesel (32/64/128 znaků, `crypto.getRandomValues`) + strength bar
- Šedé předvyplněné hodnoty (`admin`, `proxmox`, `root`)
- Generické IP placeholdery (žádné hardcoded privátní IP v UI)
- `dashboard_name` uložen do `config.json`, dostupný přes `/api/config/modules`

---

> Nápady na funkce, vylepšení a design rozhraní jsou z mé hlavy, ale těžkou programátorskou práci dělal Claude AI, Sonnet 🙂
