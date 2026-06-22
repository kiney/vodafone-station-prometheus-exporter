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
vodafone-station-report --help
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
port: 8018
```

Supported values:

```yaml
base_url: http://192.168.0.1/  # required
username: admin                # defaults to admin if omitted for login
password: xxx                  # required for authenticated router API
interval: 60                   # background scrape interval in seconds
host: 0.0.0.0                  # Flask bind host
port: 8018                     # Flask bind port
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

Report the health status from a SQLite history. This is a separate installed
command, not a `vodafone-station-exporter` subcommand:

```bash
vodafone-station-report metrics.sqlite3
vodafone-station-report metrics.sqlite3 --hours 24
```

The `--hours` window is relative to the newest scrape in the database, so it is
useful for checking the most recent outage even if the daemon was not running
continuously.

The report summarizes:

- scrape success rate and scrape interval
- downstream channel count, lock loss, low or implausible SNR, and power drift
- upstream channel count, ranging failures, high transmit power, degraded
  modulation such as `qpsk`, `8-qam`, `16-qam`, or `32-qam`, modulation changes,
  and transmit-power drift

Exit status is `1` only for a critical report, for example downstream lock loss
or a very high scrape failure rate. Warning reports still exit `0` so the tool
can be used interactively without tripping shell scripts on every marginal cable
signal.

Example output:

```text
DOCSIS health report: metrics.sqlite3
Status: WARN
Window: 2026-05-25T16:47:29.616808+02:00 to 2026-05-25T17:47:39.103369+02:00
Scrapes: 2 total, 2 ok, 0 failed (100.0% success)
Median interval: 60.2m
Channels: 33 downstream, 5 upstream
Findings:
- WARN: high upstream transmit power in 3 sample(s)
- WARN: degraded upstream modulation on channel(s): 6 (16-qam), 8 (32-qam), 10 (16-qam)
```

## HTTP Endpoints

- `GET /metrics` exposes the latest scrape in Prometheus text format.
- `GET /healthz` returns `200` after a successful scrape and `503` otherwise.
- `POST /scrape` triggers an immediate scrape and returns the resulting state.

The daemon performs an initial scrape immediately after startup, then repeats it
every `interval` seconds.

## Docker

Build the image:

```bash
docker build -t vodafone-station-exporter .
```

Run it with separate volumes for configuration and runtime data:

```bash
docker run --rm \
  -p 8018:8018 \
  -v vodafone-station-config:/config \
  -v vodafone-station-data:/data \
  vodafone-station-exporter
```

The container reads `/config/config.yml` and uses `/data` as its working
directory, so relative `snapshot_dir` and `sqlite_path` values are written to the
data volume. Put at least `base_url` and `password` in the mounted config file;
if `port` is omitted, the exporter listens on `8018`.

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
          - localhost:8018
```

## Development Checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile vodafone_station_exporter/*.py tests/*.py
```

## License

WTFPL, see `LICENSE`.
