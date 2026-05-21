# Vodafone Station Prometheus Exporter

Small Python daemon that logs in to a Vodafone Station cable router, scrapes the
DOCSIS status API, and exposes the latest values as Prometheus metrics.

The exporter also writes raw DOCSIS snapshots to `snapshots/` and can store a
compact scrape history in SQLite.

## Status

This currently targets the Vodafone Station web UI/API shape tested on the local
router:

- login endpoint: `/api/v1/session/login`
- DOCSIS endpoint: `/api/v1/sta_docsis_status`
- authentication: the same salt/PBKDF2 flow used by the router web UI

The parser also keeps support for the manually copied text snapshots in
`snapshots/`, so older example files remain useful as fixtures.

## Installation

With `uv`:

```bash
uv pip install -e .
```

Without `uv`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

After installation the command is available as:

```bash
.venv/bin/vodafone-station-exporter --help
```

If your shell has the virtualenv on `PATH`, `vodafone-station-exporter` is
enough.

## Configuration

Create `config.yml` in the repository root. This file contains router
credentials and is intentionally ignored by git.

Minimal example:

```yaml
base_url: http://192.168.0.1/
username: admin
password: xxx
interval: 60
port: 8000
```

Supported values:

```yaml
base_url: http://192.168.0.1/  # required
username: admin                # defaults to admin if omitted for login
password: xxx                  # required for authenticated router API
interval: 60                   # background scrape interval in seconds
host: 0.0.0.0                  # Flask bind host
port: 8000                     # Flask bind port
snapshot_dir: snapshots        # raw successful DOCSIS responses
sqlite_path: metrics.sqlite3   # set to null or "" to disable SQLite logging
request_timeout: 10            # router HTTP timeout in seconds
verify_tls: true               # relevant only for HTTPS base_url
```

Advanced endpoint override:

```yaml
docsis_path: /api/v1/sta_docsis_status
docsis_paths:
  - /api/v1/sta_docsis_status
  - /php/status_docsis_data.php
  - /status_docsis_data.php
```

Normally you do not need `docsis_path` or `docsis_paths`; the default list
already starts with the tested Vodafone Station JSON endpoint.

## Usage

Run the daemon:

```bash
.venv/bin/vodafone-station-exporter --config config.yml
```

Scrape once and print Prometheus text:

```bash
.venv/bin/vodafone-station-exporter --config config.yml --once
```

Diagnostic commands:

```bash
.venv/bin/vodafone-station-exporter --config config.yml --discover
.venv/bin/vodafone-station-exporter --config config.yml --debug-login
```

The diagnostic output is sanitized and does not print the configured password.

## HTTP Endpoints

- `GET /metrics` exposes the latest scrape in Prometheus text format.
- `GET /healthz` returns `200` after a successful scrape and `503` otherwise.
- `POST /scrape` triggers an immediate scrape and returns the resulting state.

The daemon performs an initial scrape immediately after startup, then repeats it
every `interval` seconds.

## Metrics

Core scrape state:

- `vodafone_station_scrape_success`
- `vodafone_station_last_scrape_timestamp_seconds`
- `vodafone_station_scrape_error{message=...}` when the last scrape failed

Downstream DOCSIS metrics:

- `vodafone_station_docsis_downstream_power_dbmv`
- `vodafone_station_docsis_downstream_power_dbuv`
- `vodafone_station_docsis_downstream_snr_db`
- `vodafone_station_docsis_downstream_locked`

Upstream DOCSIS metrics:

- `vodafone_station_docsis_upstream_power_dbmv`
- `vodafone_station_docsis_upstream_power_dbuv`
- `vodafone_station_docsis_upstream_ranging_success`

Channel count:

- `vodafone_station_docsis_channels{direction="downstream"}`
- `vodafone_station_docsis_channels{direction="upstream"}`

Channel metrics include labels such as `channel_id`, `channel_type`,
`frequency_mhz`, `modulation`, and the original lock/ranging status text.

## Storage

On each successful scrape, the raw router response is written to:

```text
snapshots/DOCSIS_<timestamp>
```

If `sqlite_path` is enabled, every scrape attempt is recorded in the `scrapes`
table with timestamp, success flag, error text, channel counts, and parsed JSON
payload for successful scrapes.

## Prometheus Example

```yaml
scrape_configs:
  - job_name: vodafone_station
    static_configs:
      - targets:
          - localhost:8000
```

## Development Checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile vodafone_station_exporter/*.py tests/test_docsis.py
```
