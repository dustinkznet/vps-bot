#!/usr/bin/env python3
"""
Server management Telegram bot.

Commands (also available as tap buttons):
  /report   → trigger an immediate daily report
  /upgrade  → run apt upgrade now (inline confirm/cancel buttons)
  /reboot   → reboot the server (inline confirm/cancel buttons)
  /status   → quick service status check
  /logs     → tail recent logs for a service (e.g. /logs nginx 30)
  /help     → list commands and show button keyboard

Proactive alerts (checked every ALERT_INTERVAL_MINUTES):
  - Service down / recovered
  - Disk usage above DISK_WARN_PCT
  - Reboot required after kernel/lib update
  - SSL cert expiring within SSL_WARN_DAYS days (set MONITORED_DOMAINS)
  - New fail2ban bans
  - Successful SSH logins
"""

import urllib.request
import urllib.parse
import json
import time
import subprocess
import os
import ssl
import socket
from datetime import datetime
from pathlib import Path

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
OFFSET_FILE      = Path("/var/lib/serverbot/.offset")

SCRIPTS_DIR        = "/opt/bots/server"
MONITORED_SERVICES = os.environ.get("MONITORED_SERVICES", "nginx fail2ban").split()
MONITORED_DOMAINS  = os.environ.get("MONITORED_DOMAINS", "").split()
DISK_WARN_PCT      = int(os.environ.get("DISK_WARN_PCT", "80"))
SSL_WARN_DAYS      = int(os.environ.get("SSL_WARN_DAYS", "30"))
ALERT_INTERVAL     = int(os.environ.get("ALERT_INTERVAL_MINUTES", "5")) * 60

# Tracks active alert state to avoid repeat notifications.
# Keys: "disk", "svc:<name>", "ssl:<domain>", "reboot_required" — True while alert is active.
alert_state = {}

# Tracks when the last proactive check ran, used for journalctl --since queries.
last_check_dt = None

# Persistent reply keyboard shown at the bottom of the chat.
# Tapping a button sends its label as a text message.
MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Report"}, {"text": "⚡ Status"}],
        [{"text": "📜 Logs"},   {"text": "🔧 Upgrade"}],
        [{"text": "🔄 Reboot"}, {"text": "❓ Help"}],
    ],
    "resize_keyboard": True,
    "persistent": True,
}

# Maps button labels (lowercase) to their equivalent slash commands.
BUTTON_MAP = {
    "📊 report":  "/report",
    "⚡ status":  "/status",
    "📜 logs":    "/logs",
    "🔧 upgrade": "/upgrade",
    "🔄 reboot":  "/reboot",
    "❓ help":    "/help",
}


def send(text, reply_markup=None):
    """Send a message, optionally with a reply_markup (keyboard or inline buttons)."""
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"Telegram send error: {e}")


def answer_callback(callback_id, text=""):
    """Acknowledge a button tap — clears Telegram's loading spinner."""
    payload = json.dumps({"callback_query_id": callback_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        log(f"answerCallbackQuery error: {e}")


def get_updates(offset=0):
    params = urllib.parse.urlencode({
        "timeout": 30,
        "offset": offset,
        "allowed_updates": json.dumps(["message", "callback_query"]),
    })
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?{params}"
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
    """Run all proactive checks and alert on new issues.
    Alerts fire once on onset and resolve once on recovery."""
    global last_check_dt

    # For journalctl queries: look back to last check, or one interval on first run
    if last_check_dt:
        since = last_check_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        since_ts = datetime.utcnow().timestamp() - ALERT_INTERVAL
        since = datetime.utcfromtimestamp(since_ts).strftime("%Y-%m-%d %H:%M:%S")

    # --- Service checks ---
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

    # --- Disk usage check ---
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

    # --- Reboot required ---
    if Path("/var/run/reboot-required").exists():
        if not alert_state.get("reboot_required"):
            send("⚠️ *Reboot required* — a kernel or library update is waiting to be applied.")
            alert_state["reboot_required"] = True
    else:
        alert_state["reboot_required"] = False

    # --- SSL cert expiry ---
    # Two failure modes deserve a Telegram alert (not just a log line):
    #   1. Cert is valid but expiring within SSL_WARN_DAYS
    #   2. Cert has already expired (validation throws CERTIFICATE_VERIFY_FAILED)
    # Without (2), an expired cert would silently log an error forever — the
    # exact case where the alerting system needs to be loudest.
    for domain in MONITORED_DOMAINS:
        key = f"ssl:{domain}"
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(
                socket.create_connection((domain, 443), timeout=10),
                server_hostname=domain
            ) as s:
                cert = s.getpeercert()
            expiry = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
            days_left = (expiry - datetime.utcnow()).days
            if days_left <= SSL_WARN_DAYS:
                if not alert_state.get(key):
                    send(f"⚠️ *SSL cert expiring in {days_left} days* — `{domain}`")
                    alert_state[key] = True
            else:
                alert_state[key] = False
        except ssl.SSLCertVerificationError as e:
            # Most commonly: cert already expired. Alert once, don't spam.
            if not alert_state.get(key):
                send(f"🚨 *SSL cert invalid* — `{domain}`\n`{e.reason}`")
                alert_state[key] = True
        except Exception as e:
            log(f"SSL check error ({domain}): {e}")

    # --- Service log errors ---
    # Scan each monitored service for new error/warn lines since last check.
    # Naturally non-spammy because we only look at the window since last check.
    # --utc is critical: `since` is built from datetime.utcnow(), and without
    # --utc journalctl interprets the timestamp in the server's local TZ.
    LOG_KEYWORDS = ("error", "warn", "crit", "fatal")
    for svc in MONITORED_SERVICES:
        try:
            result = subprocess.run(
                ["journalctl", "-u", svc, "--since", since, "--utc", "--no-pager", "-q"],
                capture_output=True, text=True
            )
            error_lines = [
                l for l in result.stdout.splitlines()
                if any(kw in l.lower() for kw in LOG_KEYWORDS)
            ]
            if error_lines:
                count = len(error_lines)
                send(
                    f"⚠️ *{svc}:* {count} new error/warn line(s) — worth a look.",
                    reply_markup={
                        "inline_keyboard": [[
                            {"text": "Last 20 lines", "callback_data": f"logs_tail:{svc}"},
                            {"text": "Errors only",   "callback_data": f"logs_errors:{svc}"},
                        ]]
                    },
                )
        except Exception as e:
            log(f"Log error check ({svc}): {e}")

    # --- fail2ban new bans ---
    try:
        result = subprocess.run(
            ["journalctl", "-u", "fail2ban", "--since", since, "--utc", "--no-pager", "-q"],
            capture_output=True, text=True
        )
        ban_lines = [l for l in result.stdout.splitlines() if " Ban " in l]
        if ban_lines:
            ips = [l.split(" Ban ")[-1].strip() for l in ban_lines]
            ip_list = "\n".join(f"`{ip}`" for ip in ips[:10])
            extra = f" _(+{len(ips) - 10} more)_" if len(ips) > 10 else ""
            send(f"🔒 *fail2ban:* {len(ips)} new ban(s){extra}\n{ip_list}")
    except Exception as e:
        log(f"fail2ban check error: {e}")

    # --- Successful SSH logins ---
    try:
        result = subprocess.run(
            ["journalctl", "-u", "ssh", "--since", since, "--utc", "--no-pager", "-q"],
            capture_output=True, text=True
        )
        logins = [l for l in result.stdout.splitlines() if "Accepted" in l]
        for login in logins:
            send(f"🔑 *SSH login detected*\n`{login}`")
    except Exception as e:
        log(f"SSH login check error: {e}")

    last_check_dt = datetime.utcnow()


def fetch_and_send_logs(svc, errors_only=False):
    """Fetch journalctl output for a service and send it to Telegram."""
    n_lines = 200 if errors_only else 20
    result = subprocess.run(
        ["journalctl", "-u", svc, "-n", str(n_lines), "--no-pager"],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().splitlines()
    if errors_only:
        keywords = ("error", "warn", "crit", "fatal")
        lines = [l for l in lines if any(kw in l.lower() for kw in keywords)]
        if not lines:
            send(f"✅ No errors/warnings found in recent `{svc}` logs.")
            return
        label = f"Errors: {svc}"
    else:
        label = f"Logs: {svc} (last {n_lines} lines)"
    out = "\n".join(lines) or "No log output."
    if len(out) > 3500:
        out = "..." + out[-3500:]
    send(f"*{label}*\n```\n{out}\n```")


def handle_callback(callback_id, data):
    """Handle inline keyboard button taps (confirm/cancel for reboot/upgrade, log viewing)."""
    answer_callback(callback_id)

    # --- Log service picker: show tail/errors buttons for a chosen service ---
    if data.startswith("logs_pick:"):
        svc = data.split(":", 1)[1]
        send(
            f"📜 *{svc} logs* — what do you want to see?",
            reply_markup={
                "inline_keyboard": [[
                    {"text": "Last 20 lines",  "callback_data": f"logs_tail:{svc}"},
                    {"text": "Errors only",    "callback_data": f"logs_errors:{svc}"},
                ]]
            },
        )
        return

    # --- Log output: tail or errors-only ---
    if data.startswith("logs_tail:"):
        fetch_and_send_logs(data.split(":", 1)[1], errors_only=False)
        return

    if data.startswith("logs_errors:"):
        fetch_and_send_logs(data.split(":", 1)[1], errors_only=True)
        return

    if data == "confirm_reboot":
        send("🔄 Rebooting now...")
        time.sleep(1)
        subprocess.run(["sudo", "reboot"])

    elif data == "cancel_reboot":
        send("❌ Reboot cancelled.")

    elif data == "confirm_upgrade":
        send("⏳ Starting upgrade — I'll report back when done...")
        code, out = run_script(f"{SCRIPTS_DIR}/weekly-upgrade.sh")
        if code != 0:
            send(f"❌ Upgrade script error:\n```{out[-400:]}```")
        # upgrade script sends its own Telegram messages on success

    elif data == "cancel_upgrade":
        send("❌ Upgrade cancelled.")


def handle_message(raw_text):
    # Remap button labels to their slash command equivalents
    normalized = BUTTON_MAP.get(raw_text.strip().lower(), raw_text.strip())

    parts = normalized.split()
    if not parts:
        return
    cmd  = parts[0].lower()
    args = parts[1:]

    # Strip @botname suffix if present (e.g. /start@mybot)
    if "@" in cmd:
        cmd = cmd.split("@")[0]

    if cmd in ("/start", "/help"):
        send(
            "*Server Management Bot*\n\n"
            "Tap a button or type a command:\n\n"
            "  /report — full health report\n"
            "  /status — quick service check\n"
            "  /upgrade — run apt upgrade\n"
            "  /reboot — reboot server\n"
            "  /logs <service> [lines] — tail service logs\n"
            "  /help — this message",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if cmd == "/report":
        send("⏳ Generating report...")
        code, out = run_script(f"{SCRIPTS_DIR}/daily-report.sh")
        if code != 0:
            send(f"❌ Report failed:\n```{out[-400:]}```")
        # report script sends its own Telegram message on success
        return

    if cmd == "/upgrade":
        send(
            "⚠️ *Run apt upgrade now?*",
            reply_markup={
                "inline_keyboard": [[
                    {"text": "✅ Confirm", "callback_data": "confirm_upgrade"},
                    {"text": "❌ Cancel",  "callback_data": "cancel_upgrade"},
                ]]
            },
        )
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
                "📜 *Check logs:*",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": svc, "callback_data": f"logs_pick:{svc}"}
                        for svc in MONITORED_SERVICES
                    ]]
                },
            )
            return
        svc = args[0].lower()
        if svc not in MONITORED_SERVICES:
            send(
                f"Unknown service `{svc}`.\n"
                "Monitored services: " + ", ".join(f"`{s}`" for s in MONITORED_SERVICES)
            )
            return
        fetch_and_send_logs(svc, errors_only=False)
        return

    if cmd == "/reboot":
        send(
            "⚠️ *Reboot the server?*",
            reply_markup={
                "inline_keyboard": [[
                    {"text": "✅ Confirm", "callback_data": "confirm_reboot"},
                    {"text": "❌ Cancel",  "callback_data": "cancel_reboot"},
                ]]
            },
        )
        return

    send("Unknown command. Send /help for a list of commands.")


def register_commands():
    """Register slash commands with Telegram so they appear in the / menu."""
    commands = [
        {"command": "report",  "description": "Full health report"},
        {"command": "status",  "description": "Quick service check"},
        {"command": "logs",    "description": "Tail service logs (e.g. /logs nginx 30)"},
        {"command": "upgrade", "description": "Run apt upgrade"},
        {"command": "reboot",  "description": "Reboot the server"},
        {"command": "help",    "description": "Show commands and button keyboard"},
    ]
    payload = json.dumps({"commands": commands}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
            if result.get("ok"):
                log("Slash commands registered with Telegram.")
            else:
                log(f"setMyCommands failed: {result}")
    except Exception as e:
        log(f"setMyCommands error: {e}")


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main():
    log(f"Server management bot started (pid={os.getpid()})")
    Path("/var/lib/serverbot").mkdir(parents=True, exist_ok=True)
    register_commands()
    offset = int(OFFSET_FILE.read_text().strip()) if OFFSET_FILE.exists() else 0
    log(f"Starting at offset {offset}")

    last_check = 0

    while True:
        try:
            now = time.time()

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

                # Handle inline button taps
                cb = update.get("callback_query")
                if cb:
                    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                    if chat_id != TELEGRAM_CHAT_ID:
                        log(f"Ignored callback from chat_id={chat_id}")
                        continue
                    log(f"Callback: {cb['data']}")
                    handle_callback(cb["id"], cb["data"])
                    continue

                # Handle text messages
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
