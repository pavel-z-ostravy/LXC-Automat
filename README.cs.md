# LXC-Automat

> Self-hosted homelab dashboard s webovým instalátorem

🇬🇧 [English](README.md) | 🇨🇿 Česky

Config-driven homelab dashboard pro Proxmox + volitelné moduly (Home Assistant, Router, Cloudflare, NextDNS). Instalace jedním příkazem — webový wizard tě provede celým nastavením, žádné ruční editování konfiguračních souborů.

---

## Rychlá instalace

```bash
curl -sSL https://raw.githubusercontent.com/pavel-z-ostravy/LXC-Automat/main/install.sh | sudo bash
```

Pak otevři `http://<IP-serveru>:8091/setup` a projdi wizard.

> Instalační wizard vždy běží na portu **8091**. V průběhu wizardu si zvolíš, na kterém portu poběží samotný dashboard (výchozí: 8091).

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

8-krokový wizard — žádné SSH ani ruční editování souborů:

| Krok | Co nastavuješ |
|------|---------------|
| 1. Kontrola systému | Python, sshpass, paramiko |
| 2. Přihlašovací údaje | Název dashboardu, port, uživatel + heslo (SHA-256 hash, s generátorem) |
| 3. Proxmox | IP, node name, SSH auth (heslo **nebo** generovaný keypair) |
| 4. Moduly | Home Assistant, Router, Cloudflare, NextDNS (každý volitelný) |
| 5. Služby | URL adresy pro monitoring dostupnosti |
| 6. WoL zařízení | Název + MAC + IP pro Wake-on-LAN |
| 7. Vývojové prostředí | Volitelné vývojářské nástroje pro instalaci na server |
| 8. Review + Instalace | Zobrazí celý config (hesla skryta), uloží `config.json` |

### UX funkce wizardu

- **Výběr jazyka před startem** — celostránková volba EN 🇬🇧 / CS 🇨🇿 před zahájením wizardu; přepínač je i v hlavičce
- **Název dashboardu** — dynamicky aktualizuje titulek prohlížeče i navbar dashboardu
- **Generátor hesel** — generuje 32/64/128-znakové heslo přes `crypto.getRandomValues`, zobrazí strength bar
- **Validace shody hesel** — živá zpětná vazba ✓/✗ pod polem pro potvrzení hesla
- **Šedé výchozí hodnoty** — předvyplněná pole (`admin`, `proxmox`, `root`) jsou šedá dokud nezačneš psát
- **Generické placeholdery** — IP pole zobrazují `např. 192.168.1.x` místo konkrétních adres
- **Ikonka oka v review** — možnost zobrazit heslo naposledy před instalací

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

**Volitelné balíčky:** Docker, Node.js LTS, pnpm, Vercel CLI, Claude Code, Supabase CLI, micro editor, Git konfigurace

---

## Architektura

```
Prohlížeč  ──→  Web UI (single-page HTML + JS, EN/CS)
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

> ### ⚠️ Určeno pouze pro důvěryhodné lokální sítě
> **Nevystavuj tento dashboard přímo na internet.**
> Nemá HTTPS, ochranu proti brute-force ani rate limiting na přihlašovacím endpointu.
> Pokud potřebuješ vzdálený přístup, použij reverzní proxy (např. Nginx nebo Caddy) s HTTPS,
> nebo VPN / Cloudflare Tunnel.

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
│   ├── en.json          # překlady wizardu (EN)
│   ├── cs.json          # překlady wizardu (CS)
│   ├── dashboard-en.json  # překlady dashboardu (EN)
│   └── dashboard-cs.json  # překlady dashboardu (CS)
├── requirements.txt
├── monitor-public.service
├── screenshots/         # screenshoty pro README
├── keys/                # SSH klíče generované wizardem (gitignored)
└── config.json          # generovaný wizardem (gitignored)
```

---

## Screenshoty

### Instalační wizard

#### Krok 1 — Kontrola systému
Ověření dostupnosti Pythonu 3, sshpass a paramiko; detekce lokální IP adresy serveru.

![Krok 1 - Kontrola systému](screenshots/wizard-step1-system-check.png)

#### Krok 2 — Přihlašovací údaje
Nastavení názvu dashboardu (live aktualizace titulku prohlížeče), portu, uživatelského jména a hesla. Zabudovaný generátor vytváří 32/64/128-znaková hesla se strength barem; živý indikátor ✓/✗ potvrzuje shodu obou polí.

![Krok 2 - Přihlašovací údaje](screenshots/wizard-step2-credentials.png)

#### Krok 3 — Připojení k Proxmoxu
IP adresa, název nodu a SSH přihlášení — heslem nebo wizardem generovaným ed25519 klíčem (veřejný klíč se zobrazí s tlačítkem Kopírovat pro vložení do `authorized_keys`). Tlačítko **Test SSH connection** ověří přihlašovací údaje před pokračováním.

![Krok 3 - Proxmox](screenshots/wizard-step3-proxmox.png)

#### Krok 4 — Volitelné moduly
Aktivace Home Assistant, Router, Cloudflare a/nebo NextDNS. Každý modul po zaškrtnutí rozbalí vlastní formulář s přihlašovacími údaji. Neaktivní moduly se v dashboardu úplně skryjí — žádné prázdné karty.

![Krok 4 - Moduly](screenshots/wizard-step4-modules.png)

#### Krok 5 — Monitorované služby
Přidání libovolného počtu URL (název + adresa) pro HTTP kontrolu dostupnosti. Každá služba dostane live stavový indikátor na dashboardu.

![Krok 5 - Služby](screenshots/wizard-step5-services.png)

#### Krok 6 — Wake-on-LAN zařízení
Registrace zařízení podle názvu, MAC adresy a IP. Dashboard zobrazuje živý ping stav a tlačítko pro odeslání WoL paketu jedním kliknutím.

![Krok 6 - WoL](screenshots/wizard-step6-wol.png)

#### Krok 7 — Vývojové prostředí
Volitelná instalace vývojářských nástrojů na server na pozadí po spuštění dashboardu. Nástroje jsou rozděleny do dvou skupin: **Node.js ekosystém** (Node.js LTS + jako závislé pnpm, Vercel CLI, Supabase CLI, Claude Code) a **Nezávislé nástroje** (Bun, Docker, Redis, Python 3, micro editor). Průběh se loguje do `dev_install.log`.

![Krok 7 - Vývojové prostředí](screenshots/wizard-step7-devenv.png)

---

### Dashboard

#### Zdroje — Teploty a grafy CPU/RAM
Záložka Resources zobrazuje živé hodnoty ze senzorů (PCH, ACPITZ, teploty per-core) a rolující historické grafy teplot a využití CPU/RAM (Proxmox host + aktivní VM). Stavový řádek nahoře zobrazuje uptime každého monitorovaného systému.

![Dashboard - Zdroje](screenshots/dashboard-resources-temperatures.png)

#### Nástroje — LXC Setup Generator
Záložka Tools obsahuje wizard pro provisioning LXC kontejnerů. Vyplň identitu kontejneru (CT ID, hostname, RAM, CPU, disk), síťovou konfiguraci (IP adresa s živou kontrolou dostupnosti, brána), volitelnou Git konfiguraci a vyber balíčky k instalaci. Kliknutím na **Vytvořit LXC a nainstalovat** se kontejner provisionuje na Proxmoxu s live logem.

![Dashboard - Nástroje LXC](screenshots/dashboard-tools-lxc.png)

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
- Webový instalační wizard (8 kroků, `installer.py` + `installer.html`)
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

**Bezpečnostní audit a opravy:**
- Odstraněn `shell=True` ve speedtestu + `server_id` validován jako číslice
- Zálohy — spuštění: `vmid` pouze číslice, `mode` whitelist `{stop, suspend, snapshot}`
- Zálohy — smazání: `volid` validován regexem bezpečných znaků
- Zálohy — plánování: `vmids`, `dow`, `hour`, `minute`, `maxfiles` validovány/whitelistovány
- LXC generátor skriptů: `git_name`, `git_email`, `ssh_key` obaleny `shlex.quote()` + SSH klíč zapisován přes `printf '%s'` místo `echo '...'`
- `generate_key` — name validován regexem; `test_ssh` — key_path ověřen vůči `KEYS_DIR`
- LXC parametry: `ct_id`, `hostname`, `ip`, `gw` validovány přísnými regexy; `shlex.quote()` na heslo a šablonu

**Čtvrtá iterace — i18n dashboardu + krok Vývojové prostředí:**
- Plný anglický překlad frontendu dashboardu (`locales/dashboard-en.json`, 114 klíčů)
- Dashboard výchozí jazyk EN; kopíruje volbu jazyka z wizardu přes `localStorage`
- Přepínač vlajek v navbaru přepíná jazyk dashboardu živě bez načtení stránky
- Přidán krok 7 Vývojové prostředí do wizardu: Node.js ekosystém + nezávislé nástroje v 2-sloupcovém gridu karet
- Instalace na pozadí přes `subprocess.Popen` po dokončení wizardu; průběh v `dev_install.log`
- LXC formulář: přidáno pole CT ID + sekce "02 — Síťová konfigurace" (IP + brána)

---

> Nápady na funkce, vylepšení a design rozhraní jsou z mé hlavy, ale těžkou programátorskou práci dělal Claude AI, Sonnet 🙂
