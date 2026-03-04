# LXC-Automat

> Self-hosted homelab dashboard s webovým instalátorem

🇬🇧 [English](README.md) | 🇨🇿 Česky

Config-driven homelab dashboard pro Proxmox + volitelné moduly (Home Assistant, Router, Cloudflare, NextDNS). Instalace jedním příkazem — webový wizard tě provede celým nastavením, žádné ruční editování konfiguračních souborů.

---

## Poslední aktualizace

| Datum | Co se změnilo |
|-------|--------------|
| **4. 3. 2026** | **User menu + Settings panel** — dropdown `👤 admin ▾` v navbaru; modál Účet (název dashboardu, heslo, reset 2FA); modál Nastavení se záložkami Moduly, WoL zařízení a Monitorované služby — vše editovatelné živě bez nutnosti spouštět wizard znovu |
| **1. 3. 2026** | **GitHub SSH klíč** + oprava vlastníka `monitor.service` |
| **1. 2. 2026** | **První vydání** — webový instalační wizard, moduly Proxmox/HA/Router/Cloudflare/NextDNS, LXC generátor, speedtest, WoL, TOTP 2FA |

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
| 2. Přihlašovací údaje | Název dashboardu, port, uživatel + heslo (SHA-256 hash, s generátorem) + volitelné TOTP 2FA |
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
- **Volitelné TOTP 2FA** — zaškrtávátko v kroku přihlašovacích údajů; vygeneruje QR kód ke skenování v Google Authenticator / Authy, zobrazí base32 secret pro ruční zadání, vyžaduje ověřený 6-místný kód před pokračováním
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
- **Auth**: Cookie session, SHA-256 hash hesla, volitelné TOTP 2FA (pyotp), nikdy neuloženo v plaintextu
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
- TOTP secret uložen v `config.json` (práva 600, gitignored), nikdy se neloguje
- Cloudflare/NextDNS tokeny se nikdy nelogují
- SSH klíče mají práva `600`

---

## Struktura souborů

```
/opt/lxc-automat/
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
├── lxc-automat.service
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

**Volitelně: dvoufaktorové ověřování (TOTP)** — zaškrtni „Povolit 2FA", klikni na **Generovat QR kód**, naskenuj v Google Authenticator nebo Authy a zadej 6-místný kód pro ověření. Base32 secret se zobrazí i pro ruční zadání. Wizard nepustí dál bez úspěšného ověření.

![Krok 2 - Nastavení TOTP 2FA](screenshots/wizard-step2-totp.png)

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

## Řešení problémů

> **Poznámka k cestám:** Příkazy níže používají výchozí název instalace `lxc-automat`. Pokud sis zvolil jiný název, nahraď `lxc-automat` svým názvem ve všech příkazech.

### Špatné heslo — nelze se přihlásit

Heslo je uloženo jako SHA-256 hash v `config.json`. Reset:

```bash
# Vygeneruj nový hash pro zvolené heslo
python3 -c "import hashlib; print(hashlib.sha256(b'TVOJE_NOVE_HESLO').hexdigest())"

# Uprav config.json a nahraď hodnotu auth.password_hash
nano /opt/lxc-automat/config.json
```

Pak restartuj service:
```bash
sudo systemctl restart lxc-automat
```

---

### Ztracený TOTP / nelze projít 2FA

Pokud ztratíš přístup k aplikaci pro ověřování, vypni 2FA přímo v `config.json`:

```bash
nano /opt/lxc-automat/config.json
```

V sekci `auth` nastav `totp_secret` na `null`:

```json
"auth": {
  "username": "admin",
  "password_hash": "...",
  "totp_secret": null
}
```

Restartuj service — přihlášení bude opět fungovat jen heslem:
```bash
sudo systemctl restart lxc-automat
```

---

### Service se nespustí

Zkontroluj logy:
```bash
sudo journalctl -u lxc-automat -n 50 --no-pager
```

Časté příčiny:
- **`ModuleNotFoundError`** — chybí Python závislost. Nainstaluj ji do venvu:
  ```bash
  /opt/lxc-automat/venv/bin/pip install <název-modulu>
  ```
- **Port je obsazený** — jiná service běží na portu 8091. Zastav ji nebo změň port v `config.json` a v service souboru:
  ```bash
  sudo nano /etc/systemd/system/lxc-automat.service
  sudo systemctl daemon-reload && sudo systemctl restart lxc-automat
  ```
- **Chyba syntaxe v `config.json`** — ověř soubor:
  ```bash
  python3 -m json.tool /opt/lxc-automat/config.json
  ```

---

### Reset wizardu (začít nastavení znovu)

Smazání `config.json` způsobí, že app při příštím startu znovu zobrazí instalační wizard:

```bash
sudo rm /opt/lxc-automat/config.json
sudo systemctl restart lxc-automat
```

Pak otevři `http://<IP-serveru>:8091/setup` — spustí se celý wizard znovu. SSH klíče v `keys/` jsou zachovány, ale lze je ručně smazat.

> **Poznámka:** Tímto se nic neodinstaluje — resetuje se jen konfigurace. Service, venv a všechny soubory zůstávají.

---

### Kompletní reinstalace

```bash
sudo systemctl stop lxc-automat
sudo systemctl disable lxc-automat
sudo rm -rf /opt/lxc-automat
sudo rm /etc/systemd/system/lxc-automat.service
sudo systemctl daemon-reload
```

Pak znovu spusť instalační skript.

---

## Plánované funkce

- [ ] **Systém témat** — více vizuálních designů (Midnight / Obsidian / Forest / Amber) přepínatelných přímo v dashboardu i volitelných jako výchozích ve wizardu (s live CSS náhledem). Každé téma definuje vlastní barevnou paletu, typografii a akcent přes CSS custom properties — bez znovunačtení stránky.
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

**Pátá iterace — TOTP dvoufaktorové ověřování:**
- Volitelné TOTP 2FA v kroku 2 wizardu: zaškrtávátko → QR kód (qrcode.js) → ověření 6-místným kódem
- `GET /api/installer/generate_totp` + `POST /api/installer/verify_totp` v `installer.py`
- `totp_secret` uložen do `config.json` (null pokud zakázáno)
- Dvoufázové přihlášení v `app.py`: heslo → cookie `pending_totp` (120s TTL) → `/login/totp` → pyotp ověření → session
- Nulová režie při vypnutém 2FA — přihlašovací flow beze změny

---

> Nápady na funkce, vylepšení a design rozhraní jsou z mé hlavy, ale těžkou programátorskou práci dělal Claude AI, Sonnet 🙂
