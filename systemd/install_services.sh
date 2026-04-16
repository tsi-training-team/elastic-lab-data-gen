#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install -m 0644 "$SCRIPT_DIR"/*.service /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR"/*.timer /etc/systemd/system/

if [[ ! -f /etc/elastic-lab-data-gen.env ]]; then
  install -m 0644 "$SCRIPT_DIR/elastic-lab-data-gen.env.example" /etc/elastic-lab-data-gen.env
  echo "Created /etc/elastic-lab-data-gen.env (edit this file before start if needed)."
fi

systemctl daemon-reload

systemctl enable --now elastic-gen-web.service
systemctl enable --now elastic-gen-auth.service
systemctl enable --now elastic-gen-orders.service
systemctl enable --now elastic-gen-system.service
systemctl enable --now elastic-attack-inject.service

echo "Enabled and started: web/auth/orders/system/attack generators"
echo "Optional burst mode instead: systemctl enable --now elastic-attack-inject.timer"
echo "If using timer mode, disable service mode first: systemctl disable --now elastic-attack-inject.service"
echo "Check status with: systemctl status elastic-gen-web.service"
