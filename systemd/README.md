# systemd Deployment

This folder contains ready-to-copy `systemd` units for non-blocking continuous generation.

## Files

- `elastic-gen-web.service`
- `elastic-gen-auth.service`
- `elastic-gen-orders.service`
- `elastic-gen-system.service`
- `elastic-attack-inject.service` (continuous stream)
- `elastic-attack-inject.timer` (optional periodic burst mode)
- `elastic-lab-data-gen.env.example`
- `install_services.sh`

## Quick Setup

1. Copy this repo to the target host (for example `/opt/elastic-lab-data-gen`).
2. Copy and edit environment file:
   - `sudo cp systemd/elastic-lab-data-gen.env.example /etc/elastic-lab-data-gen.env`
   - `sudo vi /etc/elastic-lab-data-gen.env`
3. Install and start services:
   - `sudo bash systemd/install_services.sh`

## Manage Services

- Status: `systemctl status elastic-gen-web.service`
- Logs: `journalctl -u elastic-gen-web.service -f`
- Restart one: `systemctl restart elastic-gen-web.service`
- Stop one: `systemctl stop elastic-gen-web.service`

Attack service is now installed/enabled by default for continuous attack events.

## Optional Attack Burst Mode (Timer)

If you prefer periodic bursts instead of a stream:

```bash
sudo systemctl disable --now elastic-attack-inject.service
sudo systemctl enable --now elastic-attack-inject.timer
```

Run one attack injection immediately:

```bash
sudo systemctl start elastic-attack-inject.service
```
