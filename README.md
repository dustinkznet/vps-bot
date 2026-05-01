# VPS Server Bot

A Telegram bot for managing and monitoring a Linux VPS. Get daily health reports, trigger upgrades, check service status, and reboot — all from your phone.

## Example Report

```
🖥 Daily Server Report
2026-05-01 07:00 UTC

Uptime: 2 weeks, 1 day, 4 hours
Load: 0.02, 0.01, 0.00

💾 Disk: 12G used / 80G total (15%)
🧠 Memory: 312MB used / 1963MB total (1651MB free)
🔄 Swap: 0MB / 2047MB

⚙️ Services:
  • nginx: active
  • postgresql: active
  • fail2ban: active

🔒 Security:
  • SSH failed logins (24h): 3
  • Fail2ban total bans: 847

🌐 SSL Certificates:
  • mysite.com: ✅ 42d
  • shop.example.com: ✅ 60d
  • staging.example.com: ⚠️ 11d

📬 Contact Forms:
  • mysite.com: ✅
  • shop.example.com: ✅
  • staging.example.com: ✅

📦 Updates: 3 package(s) pending
🕐 Last upgrade: 2026-04-28 09:00:00
```

## Features

- **`/report`** — full server health report (disk, memory, load, services, SSL cert expiry, contact form health, pending updates)
- **`/status`** — quick service status snapshot
- **`/upgrade`** — run `apt upgrade` now (confirmation required)
- **`/reboot`** — reboot with a two-step confirmation and 60-second expiry
- **`/logs <service> [lines]`** — tail recent journal logs for a monitored service (default: 20 lines, max 50)
- **`/help`** — command list
- **Proactive alerts** — background monitoring fires a Telegram message when a service goes down or disk usage exceeds your threshold, and a follow-up when it recovers

The daily report also runs automatically on a systemd timer (default: Mondays at 9AM — edit the timer to change the schedule).

## Requirements

- Linux server with `systemd`
- Python 3 (stdlib only — no pip installs needed)
- `curl`, `openssl` on the server
- `fail2ban` (optional — security stats in reports will show `n/a` without it)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/dustinkznet/vps-bot.git
cd vps-bot
```

### 2. Create the env file

```bash
sudo mkdir -p /etc/bots
sudo cp server.env.example /etc/bots/server.env
sudo nano /etc/bots/server.env
```

Fill in your Telegram bot token, chat ID, and the lists you want monitored:

- `MONITORED_DOMAINS` — checked for SSL cert expiry and `/api/health` endpoint status
- `MONITORED_SERVICES` — systemd service names checked in `/status`, daily reports, and proactive alerts
- `DISK_WARN_PCT` — disk usage percentage that triggers a proactive alert (default: 80)
- `CERT_WARN_DAYS` — days before SSL expiry to show a warning in reports (default: 14)
- `ALERT_INTERVAL_MINUTES` — how often the bot checks services and disk in the background (default: 5)

### 3. Deploy the bot files

```bash
sudo mkdir -p /opt/bots/server
sudo cp telegram-bot.py daily-report.sh weekly-upgrade.sh /opt/bots/server/
sudo chmod +x /opt/bots/server/*.sh /opt/bots/server/telegram-bot.py
```

### 4. Create a dedicated user

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin serverbot
sudo chown -R serverbot:serverbot /opt/bots/server
```

### 5. Set up runtime state directory

```bash
sudo mkdir -p /var/lib/serverbot
sudo chown serverbot:serverbot /var/lib/serverbot
```

### 6. Create the systemd service

`/etc/systemd/system/server-bot.service`:

```ini
[Unit]
Description=Server Management Telegram Bot
After=network.target

[Service]
User=serverbot
EnvironmentFile=/etc/bots/server.env
ExecStart=/usr/bin/python3 /opt/bots/server/telegram-bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 7. Create the daily report timer

`/etc/systemd/system/server-daily-report.service`:

```ini
[Unit]
Description=Daily Server Report

[Service]
User=serverbot
EnvironmentFile=/etc/bots/server.env
ExecStart=/bin/bash /opt/bots/server/daily-report.sh
```

`/etc/systemd/system/server-daily-report.timer`:

```ini
[Unit]
Description=Run daily server report

[Timer]
OnCalendar=Mon *-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 8. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now server-bot
sudo systemctl enable --now server-daily-report.timer
```

## Sudo permissions

The bot needs limited sudo access for a few commands. Create `/etc/sudoers.d/serverbot`:

```
serverbot ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/sbin/reboot, /usr/bin/fail2ban-client
```

## Security notes

- The bot only responds to the `TELEGRAM_CHAT_ID` set in `server.env` — all other senders are silently ignored
- Tokens and credentials live in `/etc/bots/server.env`, which is root-owned and never committed to git
- Reboot requires a two-step confirmation with a 60-second expiry

## Updating

Edit files locally, copy to the server, then move them into place and restart:

```bash
scp daily-report.sh weekly-upgrade.sh telegram-bot.py youruser@yourserver:~/
ssh youruser@yourserver
sudo mv ~/telegram-bot.py ~/daily-report.sh ~/weekly-upgrade.sh /opt/bots/server/
sudo chmod +x /opt/bots/server/*.sh
sudo systemctl restart server-bot
```

The extra step is because `/opt/bots/server/` is owned by the `serverbot` system user.
