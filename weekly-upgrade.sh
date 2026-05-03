#!/bin/bash
# Weekly full system upgrade — runs apt update + upgrade, reports to Telegram
set -uo pipefail

source /etc/bots/server.env

send_telegram() {
    local text="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":$(echo "$text" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"parse_mode\":\"Markdown\"}" \
        > /dev/null
}

START=$(date '+%Y-%m-%d %H:%M UTC')
send_telegram "🔄 *Weekly upgrade started* — ${START}"

# Update package lists
UPDATE_OUT=$(sudo apt-get update 2>&1)
UPDATE_EXIT=$?

if [ $UPDATE_EXIT -ne 0 ]; then
    send_telegram "❌ *apt update failed*\n\`\`\`${UPDATE_OUT: -800}\`\`\`"
    exit 1
fi

# Count upgradable before
BEFORE=$(apt list --upgradable 2>/dev/null | grep -c upgradable || echo 0)

if [ "$BEFORE" -eq 0 ]; then
    send_telegram "✅ *Weekly upgrade complete* — system already up to date."
    exit 0
fi

# Get list of packages being upgraded
PKG_LIST=$(apt list --upgradable 2>/dev/null | grep upgradable | awk -F/ '{print $1}' | head -30 | tr '\n' ' ')

# Run upgrade
UPGRADE_OUT=$(sudo apt-get upgrade -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold 2>&1)
UPGRADE_EXIT=$?

END=$(date '+%Y-%m-%d %H:%M UTC')
REBOOT_MSG=""
[ -f /var/run/reboot-required ] && REBOOT_MSG="\n\n⚠️ *Reboot required to apply kernel/lib updates*"

if [ $UPGRADE_EXIT -eq 0 ]; then
    # Trim output to last 600 chars if long
    SUMMARY="${UPGRADE_OUT: -400}"
    send_telegram "✅ *Weekly upgrade complete*
Finished: ${END}
Upgraded: ${BEFORE} package(s)

*Packages:* \`${PKG_LIST}\`${REBOOT_MSG}"
else
    send_telegram "❌ *Weekly upgrade failed*
\`\`\`${UPGRADE_OUT: -600}\`\`\`${REBOOT_MSG}"
fi

# Clean up
sudo apt-get autoremove -y > /dev/null 2>&1 || true
sudo apt-get clean > /dev/null 2>&1 || true
