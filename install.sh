#!/bin/bash
# Server-side installer. Run by deploy.sh on the remote host.
# Assumes the deploy script has staged files under ~/vps-bot-deploy/.
#
# Validates sudoers BEFORE installing — a malformed sudoers file can
# break sudo entirely, which is hard to recover from.

set -euo pipefail

cd ~/vps-bot-deploy

echo "==> Validating sudoers file"
sudo visudo -cf sudoers/serverbot

echo "==> Installing bot scripts to /opt/bots/server/"
sudo install -m 0755 -o serverbot -g serverbot telegram-bot.py   /opt/bots/server/telegram-bot.py
sudo install -m 0755 -o serverbot -g serverbot daily-report.sh   /opt/bots/server/daily-report.sh
sudo install -m 0755 -o serverbot -g serverbot weekly-upgrade.sh /opt/bots/server/weekly-upgrade.sh

echo "==> Installing systemd units to /etc/systemd/system/"
sudo install -m 0644 -o root -g root systemd/server-bot.service              /etc/systemd/system/
sudo install -m 0644 -o root -g root systemd/server-daily-report.service     /etc/systemd/system/
sudo install -m 0644 -o root -g root systemd/server-daily-report.timer       /etc/systemd/system/
sudo install -m 0644 -o root -g root systemd/server-weekly-upgrade.service   /etc/systemd/system/
sudo install -m 0644 -o root -g root systemd/server-weekly-upgrade.timer     /etc/systemd/system/

echo "==> Installing sudoers file"
sudo install -m 0440 -o root -g root sudoers/serverbot /etc/sudoers.d/serverbot

echo "==> Reloading systemd and (re)starting services"
sudo systemctl daemon-reload
sudo systemctl enable --now server-daily-report.timer server-weekly-upgrade.timer
sudo systemctl restart server-bot

echo "==> Cleaning up staging dir"
cd ~ && rm -rf ~/vps-bot-deploy

echo
echo "==> Status:"
systemctl is-active server-bot
systemctl list-timers --no-pager | grep -E "server-(daily|weekly)" || true
