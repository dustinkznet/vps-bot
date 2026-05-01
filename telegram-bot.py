#!/usr/bin/env python3
"""
Server management Telegram bot.

Commands:
  /report   → trigger an immediate daily report
  /upgrade  → run apt upgrade now (asks for confirmation)
  /reboot   → reboot the server (asks for confirmation)
  /status   → quick service status check
  /logs     → tail recent logs for a service (e.g. /logs nginx 30)
  /help     → list commands
"""

import urllib.request
import json
import time
import subprocess
import os
from datetime import datetime
from pathlib import Path

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
OFFSET_FILE      = Path("/var/lib/serverbot/.offset")
PENDING_REBOOT   = Path("/var/lib/serverbot/.pending-reboot")
PENDING_UPGRADE  = Path("/var/lib/serverbot/.pending-upgrade")

SCRIPTS_DIR        = "/opt/bots/server"
MONITORED_SERVICES = os.environ.get("MONITORED_SERVICES", "nginx fail2ban").split()
DISK_WARN_PCT      = int(os.environ.get("DISK_WARN_PCT", "80"))
ALERT_INTERVAL     = int(os.environ.get("ALERT_INTERVAL_MINUTES", "5")) * 60

# Tracks active alert state to avoid repeat notifications.
# Keys: "disk", "svc:<name>" — True while the alert condition is active.
alert_state = {}


def send(text):
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"Telegram send error: {e}")


def get_updates(offset=0):
    url = (f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
           f"/getUpdates?timeout=30&offset={offset}&allowed_updates=[\"message\"]")
    try:
        with urllib.request.urlopen(url, timeout=35) as r:
            return json.loads(r.read()).get("result", [])
    except Exception as e:
        log(f"getUpdates error: {e}")
        return []


def run_script(script_path):
    """Run a shell script and return (exit_code, stdout+stderr combined)."""
    result = subprocess.run(
        ["bash", script_path],
        capture_output=True, text=True, timeout=300
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def service_status(name):
    r = subprocess.run(["systemctl", "is-active", name],
                       capture_output=True, text=True)
    return r.stdout.strip()


def run_proactive_checks():
    """Check services and disk; send an alert if a threshold is breached.
    Tracks state so alerts fire once on onset and resolve once on recovery."""
    # Service checks
    for svc in MONITORED_SERVICES:
        status = service_status(svc)
        key = f"svc:{svc}"
        if status != "active":
            if not alert_state.get(key):
                send(f"🚨 *Alert:* `{svc}` is *{status}*")
                alert_state[key] = True
        else:
            if alert_state.get(key):
                send(f"✅ *Resolved:* `{svc}` is back online")
            alert_state[key] = False

    # Disk usage check
    try:
        disk_pct = int(
            subprocess.run(["df", "/"], capture_output=True, text=True)
            .stdout.split("\n")[1].split()[4].rstrip('%')
        )
        if disk_pct >= DISK_WARN_PCT:
            if not alert_state.get("disk"):
                send(f"🚨 *Alert:* Disk usage is *{disk_pct}%* (threshold: {DISK_WARN_PCT}%)")
                alert_state["disk"] = True
        else:
            if alert_state.get("disk"):
                send(f"✅ *Resolved:* Disk usage back to {disk_pct}%")
            alert_state["disk"] = False
    except Exception as e:
        log(f"Disk check error: {e}")


def handle_message(raw_text):
    parts = raw_text.strip().split()
    if not parts:
        return
    cmd  = parts[0].lower()
    args = parts[1:]

    if cmd in ("/start", "/help"):
        send(
            "*Server Management Bot*\n\n"
            "Commands:\n"
            "  /report — full health report\n"
            "  /status — quick service check\n"
            "  /upgrade — run apt upgrade now\n"
            "  /reboot — reboot server\n"
            "  /logs <service> [lines] — tail service logs\n"
            "  /help — this message"
        )
        return

    if cmd == "/report":
        send("⏳ Generating report...")
        code, out = run_script(f"{SCRIPTS_DIR}/daily-report.sh")
        if code != 0:
            send(f"❌ Report failed:\n```{out[-400:]}```")
        # report sends its own Telegram message on success
        return

    if cmd == "/upgrade":
        if PENDING_UPGRADE.exists():
            PENDING_UPGRADE.unlink()
            send("⏳ Starting upgrade — I'll report back when done...")
            code, out = run_script(f"{SCRIPTS_DIR}/weekly-upgrade.sh")
            if code != 0:
                send(f"❌ Upgrade script error:\n```{out[-400:]}```")
            # upgrade sends its own Telegram messages
        else:
            PENDING_UPGRADE.touch()
            send("⚠️ *Are you sure?* Send /upgrade again within 60 seconds to confirm.")
        return

    if cmd == "/status":
        service_lines = "\n".join(
            f"{svc}: {service_status(svc)}" for svc in MONITORED_SERVICES
        )
        reboot = "⚠️ YES" if Path("/var/run/reboot-required").exists() else "no"
        load   = subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
        disk   = subprocess.run(["df", "-h", "/"], capture_output=True, text=True).stdout.split("\n")[1].split()
        send(
            f"*Quick Status*\n\n"
            f"{service_lines}\n\n"
            f"Disk: {disk[2]} used / {disk[1]} ({disk[4]})\n"
            f"Reboot required: {reboot}\n\n"
            f"`{load}`"
        )
        return

    if cmd == "/logs":
        if not args:
            send(
                "Usage: `/logs <service> [lines]`\n"
                "Example: `/logs nginx 30`\n\n"
                "Monitored services: " + ", ".join(f"`{s}`" for s in MONITORED_SERVICES)
            )
            return
        svc = args[0].lower()
        if svc not in MONITORED_SERVICES:
            send(
                f"Unknown service `{svc}`.\n"
                "Monitored services: " + ", ".join(f"`{s}`" for s in MONITORED_SERVICES)
            )
            return
        try:
            n_lines = min(int(args[1]), 50) if len(args) > 1 else 20
        except ValueError:
            n_lines = 20
        result = subprocess.run(
            ["journalctl", "-u", svc, "-n", str(n_lines), "--no-pager"],
            capture_output=True, text=True
        )
        out = result.stdout.strip() or "No log output."
        # Trim to fit Telegram's 4096 char message limit
        if len(out) > 3500:
            out = "..." + out[-3500:]
        send(f"*Logs: {svc} (last {n_lines} lines)*\n```\n{out}\n```")
        return

    if cmd == "/reboot":
        if PENDING_REBOOT.exists():
            PENDING_REBOOT.unlink()
            send("🔄 Rebooting now...")
            time.sleep(1)
            subprocess.run(["sudo", "reboot"])
        else:
            PENDING_REBOOT.touch()
            send("⚠️ *Are you sure?* Send /reboot again within 60 seconds to confirm.")
        return

    send("Unknown command. Send /help for a list of commands.")


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main():
    log(f"Server management bot started (pid={os.getpid()})")
    Path("/var/lib/serverbot").mkdir(parents=True, exist_ok=True)
    offset = int(OFFSET_FILE.read_text().strip()) if OFFSET_FILE.exists() else 0
    log(f"Starting at offset {offset}")

    pending_reboot_time  = 0
    pending_upgrade_time = 0
    last_check           = 0

    while True:
        try:
            now = time.time()

            # Expire pending reboot confirmation after 60s
            if PENDING_REBOOT.exists():
                if pending_reboot_time == 0:
                    pending_reboot_time = now
                elif now - pending_reboot_time > 60:
                    PENDING_REBOOT.unlink(missing_ok=True)
                    pending_reboot_time = 0
                    send("⏱ Reboot confirmation expired.")
            else:
                pending_reboot_time = 0

            # Expire pending upgrade confirmation after 60s
            if PENDING_UPGRADE.exists():
                if pending_upgrade_time == 0:
                    pending_upgrade_time = now
                elif now - pending_upgrade_time > 60:
                    PENDING_UPGRADE.unlink(missing_ok=True)
                    pending_upgrade_time = 0
                    send("⏱ Upgrade confirmation expired.")
            else:
                pending_upgrade_time = 0

            # Proactive monitoring — runs every ALERT_INTERVAL seconds
            if now - last_check >= ALERT_INTERVAL:
                last_check = now
                try:
                    run_proactive_checks()
                except Exception as e:
                    log(f"Proactive check error: {e}")

            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                OFFSET_FILE.write_text(str(offset))

                msg     = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text    = msg.get("text", "")

                if chat_id != TELEGRAM_CHAT_ID:
                    log(f"Ignored message from chat_id={chat_id}")
                    continue
                if text:
                    log(f"Received: {repr(text)}")
                    handle_message(text)

        except Exception as e:
            log(f"Loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
