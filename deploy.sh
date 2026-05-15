#!/bin/bash
# Deploy vps_bot to the server.
# Stages files into ~/vps-bot-deploy/ on the server, then runs install.sh
# (which lives in that staging dir and handles sudo install + systemd reload).
#
# Usage: ./deploy.sh
# Requires: ssh access to $HOST as a user with sudo.

set -euo pipefail

HOST="${VPS_BOT_HOST:-webserver1}"

echo "==> Deploying to $HOST"

# Stage all files in the user's home dir on the server.
echo "==> Copying files to $HOST:~/vps-bot-deploy/"
ssh "$HOST" 'rm -rf ~/vps-bot-deploy && mkdir -p ~/vps-bot-deploy/systemd ~/vps-bot-deploy/sudoers'
scp telegram-bot.py daily-report.sh weekly-upgrade.sh install.sh "$HOST":~/vps-bot-deploy/
scp systemd/*.service systemd/*.timer "$HOST":~/vps-bot-deploy/systemd/
scp sudoers/serverbot "$HOST":~/vps-bot-deploy/sudoers/

# Run the installer with a normal interactive SSH (gets a real TTY, sudo prompt works).
echo "==> Running installer on $HOST (will prompt for sudo password)"
ssh -t "$HOST" 'bash ~/vps-bot-deploy/install.sh'

echo "==> Deploy complete."
