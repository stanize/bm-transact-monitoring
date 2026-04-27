# Transact Monitoring Service — Installation Guide

## Prerequisites

- Python 3 installed at `/bin/python3`
- `psql` installed at `/bin/psql`
- `transactuser` account exists on the host
- `.pgpass` configured for `transactuser` with correct DB credentials
- OTEL collector reachable at the endpoint defined in `otel_config.json`

---

## 1. Deploy the files

This should be done as part of the CI/CD pipeline
https://bancamarch.ghe.com/BM-LUX/temenos-monitoring

---

## 2. Configure

Ensure the files under `config/` match the target environment:

| File | What to set |
|---|---|
| `config/db_config.json` | `db_host`, `db_name`, `db_user`, `psql`, `python`, `service` |
| `config/otel_config.json` | `endpoint`, `service_name`, `export_interval_ms` |
| `config/mdp_config.json` | `interval_seconds`, `logging.level`, enable/disable individual MDPs |
| `config/env_config.json` | Verify the current hostname is listed in `env_map` |

---

## 3. Run the preflight check

Run as `transactuser` to validate everything before starting the service:

```bash
sudo -i -u transactuser
cd /mnt/temenos/T24/bnk/t24scripts/transact_monitoring
python3 bm_transact_monitoring_preflight.py
```

All checks must pass before proceeding. Review `logs/bm-preflight.log` if anything fails.

---

## 4. Install the systemd service

```bash
sudo cp transact-monitoring.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable transact-monitoring
sudo systemctl start transact-monitoring
sudo systemctl status transact-monitoring
```

---

## 5. Verify

Check the service is running and producing output:

```bash
# Service status
sudo systemctl status transact-monitoring

# Live logs via journald
journalctl -u transact-monitoring -f

# Or check the log file directly
tail -f /mnt/temenos/T24/bnk/t24scripts/transact_monitoring/logs/bm-transact-monitoring.log
```

You should see `[AUDIT]` entries for each cycle starting and finishing every 5 minutes.

---

## Common Commands

```bash
# Stop the service
sudo systemctl stop transact-monitoring

# Restart the service
sudo systemctl restart transact-monitoring

# Disable from starting on boot
sudo systemctl disable transact-monitoring

# Check recent logs
journalctl -u transact-monitoring --since "1 hour ago"
```

---

## Troubleshooting

### PermissionError on log file at startup

If the service fails immediately with a permission error on the log file,
it was likely created by root during a previous test run. Fix it with:

```bash
sudo rm /mnt/temenos/T24/bnk/t24scripts/transact_monitoring/logs/bm-transact-monitoring.log
sudo systemctl start transact-monitoring
```

The service will recreate the file with the correct ownership.
