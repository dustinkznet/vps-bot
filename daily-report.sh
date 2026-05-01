#!/bin/bash
# Daily server health report — sends summary to Telegram
# Domains monitored for SSL and form health are set in server.env as:
#   MONITORED_DOMAINS="example.com another.com"
set -euo pipefail

source /etc/bots/server.env

send_telegram() {
    local text="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":$(echo "$text" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"parse_mode\":\"Markdown\"}" \
        > /dev/null
}

# --- Disk ---
DISK_LINE=$(df -h / | awk 'NR==2 {print $3 " used / " $2 " total (" $5 ")"}')
DISK_PCT=$(df / | awk 'NR==2 {print $5}' | tr -d '%')

# --- Memory ---
MEM_TOTAL=$(free -m | awk '/^Mem:/ {print $2}')
MEM_USED=$(free -m | awk '/^Mem:/ {print $3}')
MEM_AVAIL=$(free -m | awk '/^Mem:/ {print $7}')
SWAP_TOTAL=$(free -m | awk '/^Swap:/ {print $2}')
SWAP_USED=$(free -m | awk '/^Swap:/ {print $3}')

# --- Load ---
LOAD=$(uptime | awk -F'load average:' '{print $2}' | xargs)
UPTIME=$(uptime -p | sed 's/up //')

# --- Updates ---
UPDATES=$(apt list --upgradable 2>/dev/null | grep -c upgradable 2>/dev/null || echo 0)
REBOOT_REQUIRED=""
[ -f /var/run/reboot-required ] && REBOOT_REQUIRED="⚠️ *Reboot required*" || true

# --- Services ---
check_service() {
    systemctl is-active "$1" 2>/dev/null || echo "inactive"
}
# Build service status lines from MONITORED_SERVICES in server.env
SERVICE_LINES=""
for svc in ${MONITORED_SERVICES:-}; do
    SERVICE_LINES+="  • ${svc}: $(check_service "$svc")"$'\n'
done

# --- Fail2ban bans ---
F2B_BANS=$(sudo fail2ban-client status sshd 2>/dev/null | awk '/Total banned:/ {print $NF}' || echo "n/a")

# --- SSL cert expiry (loops over MONITORED_DOMAINS from server.env) ---
check_cert_expiry() {
    local domain="$1"
    local expiry
    expiry=$(echo | timeout 5 openssl s_client -connect "${domain}:443" -servername "$domain" 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null \
        | cut -d= -f2)
    if [ -n "$expiry" ]; then
        local days
        days=$(( ( $(date -d "$expiry" +%s) - $(date +%s) ) / 86400 ))
        echo "$days"
    else
        echo "?"
    fi
}

cert_line() {
    local domain="$1" days="$2"
    if [ "$days" = "?" ]; then
        echo "  • ${domain}: ❓"
    elif [ "$days" -lt "${CERT_WARN_DAYS:-14}" ]; then
        echo "  • ${domain}: ⚠️ ${days}d"
    else
        echo "  • ${domain}: ✅ ${days}d"
    fi
}

CERT_LINES=""
for domain in $MONITORED_DOMAINS; do
    days=$(check_cert_expiry "$domain")
    CERT_LINES+="$(cert_line "$domain" "$days")"$'\n'
done

# --- SSH failed logins (last 24h) ---
FAILED_SSH=$(journalctl -u ssh --since "24 hours ago" 2>/dev/null | grep -c "Failed password\|Invalid user" || true)

# --- Last upgrade ---
LAST_UPGRADE=$(grep "End-Date" /var/log/apt/history.log 2>/dev/null | tail -1 | awk '{print $2, $3}' || echo "unknown")

# --- Contact form endpoint health checks (loops over MONITORED_DOMAINS) ---
check_form() {
    local url="$1"
    local endpoint="$2"
    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" "$url" \
        --max-time 10 2>/dev/null || echo "000")
    if [ "$response" = "200" ]; then
        echo "  • ${endpoint}: ✅"
    else
        echo "  • ${endpoint}: ❌ (HTTP ${response})"
    fi
}

FORM_LINES=""
for domain in $MONITORED_DOMAINS; do
    FORM_LINES+="$(check_form "https://${domain}/api/health" "$domain")"$'\n'
done

# --- Build message ---
disk_warn=""
[ "$DISK_PCT" -ge "${DISK_WARN_PCT:-80}" ] && disk_warn=" ⚠️"

MSG="🖥 *Daily Server Report*
$(date '+%Y-%m-%d %H:%M UTC')

*Uptime:* ${UPTIME}
*Load:* ${LOAD}

💾 *Disk:* ${DISK_LINE}${disk_warn}
🧠 *Memory:* ${MEM_USED}MB used / ${MEM_TOTAL}MB total (${MEM_AVAIL}MB free)
🔄 *Swap:* ${SWAP_USED}MB / ${SWAP_TOTAL}MB

⚙️ *Services:*
${SERVICE_LINES}

🔒 *Security:*
  • SSH failed logins (24h): ${FAILED_SSH}
  • Fail2ban bans (lifetime): ${F2B_BANS}

🌐 *SSL Certificates:*
${CERT_LINES}
📬 *Contact Forms:*
${FORM_LINES}

📦 *Updates:* ${UPDATES} package(s) pending
🕐 *Last upgrade:* ${LAST_UPGRADE}
${REBOOT_REQUIRED}"

send_telegram "$MSG"
