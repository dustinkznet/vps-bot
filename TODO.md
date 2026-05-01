# VPS Bot — TODO & Ideas

## Done
- [x] All secrets/tokens in `/etc/bots/server.env` — none in code
- [x] `MONITORED_DOMAINS` configurable via env (SSL + form health checks)
- [x] `MONITORED_SERVICES` configurable via env (/status + daily report)
- [x] Two-step reboot confirmation with 60s expiry
- [x] Chat ID whitelist — bot ignores all other senders
- [x] `server.env.example` template for new installs
- [x] `.gitignore` covering secrets, CLAUDE.md, runtime state
- [x] README with full setup guide

---

## Improvements

### High Value
- [x] **Configurable alert thresholds** — `DISK_WARN_PCT` and `CERT_WARN_DAYS` in `server.env`
- [x] **Proactive alerts** — background monitoring fires on service down or disk over threshold, resolves on recovery
- [x] **`/logs` command** — tail journal output for any monitored service (e.g. `/logs nginx 30`)
- [x] **`/upgrade` confirmation step** — two-step confirm with 60s expiry, mirrors /reboot pattern

### Quality of Life
- [ ] **Configurable report schedule** — the timer is hardcoded to Mondays 9AM in the README. Could default to daily and let users edit the timer, or add a note making it more obvious.
- [ ] **CPU in /status and reports** — load average is there but not CPU %. Add a quick `top`/`mpstat` line.
- [ ] **Network stats** — active connections count, maybe bandwidth if `vnstat` is available.

### Bigger Features
- [ ] **Alert cooldown / suppression** — if proactive alerts are added, need logic to avoid spamming the same alert repeatedly.
- [ ] **Multiple notification targets** — support a `TELEGRAM_ALERT_CHAT_ID` separate from the command chat, so alerts go somewhere different than interactive commands.
- [ ] **`/history` command** — simple log of last N events (upgrades run, reboots, alerts fired). Could just be a flat file appended to.
- [ ] **Docker support** — optional: if Docker is installed, show container status in `/status` and reports.

### Polish
- [x] **Add a LICENSE file** — MIT
- [x] **`/api/health` note in README** — clarified form check is optional, explained 404 behaviour
- [x] **Report schedule note in README** — explains how to edit the timer
- [x] **Alert cooldown note in README** — documented the in-memory state caveat
- [ ] **Test on a fresh Ubuntu server** — verify the README setup steps work end-to-end for someone starting from scratch.
