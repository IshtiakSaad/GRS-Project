#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server. Run as root:
#   sudo bash deploy/scripts/bootstrap-server.sh
# Installs Docker, adds swap, turns on automatic security updates and time sync, closes every
# port except SSH, HTTP and HTTPS, disables SSH passwords, and installs the cron jobs.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
APP_USER="${SUDO_USER:-ubuntu}"

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl git ufw chrony unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== docker"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
usermod -aG docker "$APP_USER"
# Container logs are rotated, so a noisy service cannot fill the disk.
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
JSON
systemctl restart docker

echo "== swap (2 GB): a memory spike slows the box down instead of killing PostgreSQL"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
sysctl -w vm.swappiness=10 >/dev/null
echo "vm.swappiness=10" > /etc/sysctl.d/90-grs.conf

echo "== firewall: 22, 80, 443 only"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
# Docker publishes ports around ufw; only Nginx publishes any in production
# (docker-compose.prod.yml), so nothing else is reachable.

echo "== ssh: keys only"
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh

echo "== cron: nightly backup and demo reset (Asia/Dhaka night = UTC evening)"
mkdir -p /var/backups/grs && chown "$APP_USER" /var/backups/grs
cat > /etc/cron.d/grs <<CRON
SHELL=/bin/bash
# 02:00 Dhaka: back up, then check the backup restores.
0 20 * * * $APP_USER cd $APP_DIR && deploy/scripts/backup.sh >> /var/log/grs-backup.log 2>&1 && deploy/scripts/restore-check.sh >> /var/log/grs-backup.log 2>&1
# 03:00 Dhaka: wipe and reseed the public demo.
0 21 * * * $APP_USER cd $APP_DIR && deploy/scripts/reset-demo.sh >> /var/log/grs-reset.log 2>&1
CRON
touch /var/log/grs-backup.log /var/log/grs-reset.log
chown "$APP_USER" /var/log/grs-backup.log /var/log/grs-reset.log

echo "done. Log out and back in (docker group), then: deploy/scripts/gen-env.sh <domain> <email>"
