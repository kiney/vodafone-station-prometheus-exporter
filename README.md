# Vodafone Station Prometheus Exporter

Small Python daemon that logs in to a Vodafone Station cable router, scrapes the
DOCSIS status API, and exposes the latest values as Prometheus metrics.

The exporter also writes DOCSIS text snapshots to `snapshots/` and can store a
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
vodafone-station-exporter --help
```

Activate the virtualenv before running the command when you installed into a
venv.

## Configuration

Create `config.yml` in the directory where you start the exporter. If no
`--config` argument is given, the exporter reads `./config.yml`. This file
contains router credentials and is intentionally ignored by git.

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
snapshot_dir: snapshots        # successful DOCSIS text snapshots
sqlite_path: metrics.sqlite3   # set to null or "" to disable SQLite logging
request_timeout: 10            # router HTTP timeout in seconds
verify_tls: true               # relevant only for HTTPS base_url
docsis_path: /api/v1/sta_docsis_status  # normally do not change this
```

Endpoint override:

```yaml
docsis_path: /api/v1/sta_docsis_status
```

The exporter scrapes exactly this one endpoint. If it returns a login page, an
HTTP error, or a non-DOCSIS response, the scrape fails with a clear error
instead of probing fallback URLs.

## Usage

Run the daemon:

```bash
vodafone-station-exporter
```

Scrape once and print Prometheus text:

```bash
vodafone-station-exporter --once
```

Diagnostic commands:

```bash
vodafone-station-exporter --discover
vodafone-station-exporter --debug-login
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

On each successful scrape, a text snapshot is written to:

```text
snapshots/DOCSIS_<timestamp>
```

The snapshot format matches the older manually copied DOCSIS examples in this
repository rather than the router's raw JSON API response.

If `sqlite_path` is enabled, every scrape attempt is recorded in SQLite. The
`scrapes` table contains the timestamp, success flag, error text, and channel
counts. Parsed channel values are stored as rows in `downstream_channels` and
`upstream_channels`, keyed by `scrape_id`, so values such as SNR, power, lock
state, and ranging state can be queried directly with SQL.

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
python3 -m py_compile vodafone_station_exporter/*.py tests/*.py
```

## License

WTFPL, see `LICENSE`.
