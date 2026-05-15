# VPS Bot — To Do

## Next Session

**Last worked on:** 2026-05-14
**Left off at:** Senior-dev sweep + repo cleanup landed. Config-as-code deploy pipeline is live (`deploy.sh` + `install.sh`, systemd units + sudoers tracked in repo, validated and deployed cleanly to webserver1). SSL silent-failure bug fixed. Bonus side-quest: built `~/classroom/` learning hub + queued two teaching topics (silent-failure pattern, `sudo sed -i.bak`). Two threads still open: (1) `/logs` README/code mismatch held for discussion, (2) backups still untouched.
**Start with:** `/logs` doc/code mismatch discussion (~5min, then fix), then move to backups.

## Active

- [ ] **Discuss `/logs` README/code mismatch** — README claims `[lines]` arg + max 50 lines; code ignores both. Decide: implement the arg, or update docs to match current behavior. ~3 line code change either way.
- [ ] **Backups** — priority. Plan: DigitalOcean built-in backups + rsync to NAS over VPN. Bot configs are on GitHub, sites recoverable locally, but server config/env files/scripts are not backed up.

## Completed

### 2026-05-14 session
- [x] **Security audit** — clean. No hardcoded tokens, personal info, or secrets in tracked files. CLAUDE.md properly gitignored.
- [x] **systemd units + sudoers tracked in repo** — pulled live configs from server, now in `systemd/` and `sudoers/`. No more drift between docs and reality.
- [x] **`deploy.sh` + `install.sh`** — config-as-code deploy. Validates sudoers before installing (prevents lockout), uses `install` for atomic ownership/permissions, restarts services. Replaces the manual `scp + ssh + mv + chmod` dance.
- [x] **journalctl `--utc` fix** — added to all 3 `--since` calls in `telegram-bot.py`. Server is UTC so wasn't biting in practice, but fragile if droplet ever moves TZ.
- [x] **README updates** — fixed timer schedule (was "Mondays 9am", actually "daily 7am UTC"); added weekly-upgrade docs (was scheduled on server but undocumented); replaced manual update flow with `./deploy.sh`.
- [x] **`VERSION` file at 0.5.0** — joins the bots' semver convention. Pre-1.0 reserved until ready to recommend to others.
- [x] **SSL silent-failure bug fix** — `ssl.SSLCertVerificationError` (cert already expired) was logged-and-swallowed; now fires a Telegram alert via the same `alert_state` mechanism. Discovered when `keesburyproperties.com` (now removed from MONITORED_DOMAINS) showed up in deploy logs.
- [x] **Removed kkp from `MONITORED_DOMAINS`** — dormant domain with expired cert, no longer monitored.
- [x] **Verified deploy pipeline end-to-end** — bot active, both timers (daily 7am, weekly Sun 3am UTC) loaded and scheduled.

### Earlier
- [x] Telegram button keyboard + slash commands
- [x] Weekly upgrade script
- [x] Proactive alerts: SSH logins, fail2ban bans, SSL expiry, reboot required
- [x] Interactive log viewer (service picker -> tail / errors-only buttons)
- [x] Proactive log error alerts with inline view buttons
