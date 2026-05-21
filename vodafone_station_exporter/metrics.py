from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime

from .docsis import DocsisStatus


def render_metrics(status: DocsisStatus | None, scraped_at: datetime | None, error: str | None) -> str:
    lines = [
        "# HELP vodafone_station_scrape_success Whether the last router scrape succeeded.",
        "# TYPE vodafone_station_scrape_success gauge",
        f"vodafone_station_scrape_success {1 if status is not None and error is None else 0}",
        "# HELP vodafone_station_last_scrape_timestamp_seconds Unix timestamp of the last scrape attempt.",
        "# TYPE vodafone_station_last_scrape_timestamp_seconds gauge",
        f"vodafone_station_last_scrape_timestamp_seconds {_timestamp(scraped_at)}",
    ]
    if error:
        lines.extend(
            [
                "# HELP vodafone_station_scrape_error Last scrape error, exposed as a labelled info metric.",
                "# TYPE vodafone_station_scrape_error gauge",
                f'vodafone_station_scrape_error{{message="{_escape(error)}"}} 1',
            ]
        )
    if status is None:
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "# HELP vodafone_station_docsis_downstream_power_dbmv Downstream receive power in dBmV.",
            "# TYPE vodafone_station_docsis_downstream_power_dbmv gauge",
            *_samples("vodafone_station_docsis_downstream_power_dbmv", _downstream_labels(status), "power_dbmv"),
            "# HELP vodafone_station_docsis_downstream_power_dbuv Downstream receive power in dBuV.",
            "# TYPE vodafone_station_docsis_downstream_power_dbuv gauge",
            *_samples("vodafone_station_docsis_downstream_power_dbuv", _downstream_labels(status), "power_dbuv"),
            "# HELP vodafone_station_docsis_downstream_snr_db Downstream SNR/MER in dB.",
            "# TYPE vodafone_station_docsis_downstream_snr_db gauge",
            *_samples("vodafone_station_docsis_downstream_snr_db", _downstream_labels(status), "snr_db"),
            "# HELP vodafone_station_docsis_downstream_locked Downstream lock status, 1 when locked.",
            "# TYPE vodafone_station_docsis_downstream_locked gauge",
            *[
                _sample("vodafone_station_docsis_downstream_locked", item["labels"], 1 if item["locked"] else 0)
                for item in _downstream_labels(status)
            ],
            "# HELP vodafone_station_docsis_upstream_power_dbmv Upstream send power in dBmV.",
            "# TYPE vodafone_station_docsis_upstream_power_dbmv gauge",
            *_samples("vodafone_station_docsis_upstream_power_dbmv", _upstream_labels(status), "power_dbmv"),
            "# HELP vodafone_station_docsis_upstream_power_dbuv Upstream send power in dBuV.",
            "# TYPE vodafone_station_docsis_upstream_power_dbuv gauge",
            *_samples("vodafone_station_docsis_upstream_power_dbuv", _upstream_labels(status), "power_dbuv"),
            "# HELP vodafone_station_docsis_upstream_ranging_success Upstream ranging status, 1 when successful.",
            "# TYPE vodafone_station_docsis_upstream_ranging_success gauge",
            *[
                _sample("vodafone_station_docsis_upstream_ranging_success", item["labels"], 1 if item["ranging_success"] else 0)
                for item in _upstream_labels(status)
            ],
            "# HELP vodafone_station_docsis_channels Number of parsed DOCSIS channels by direction.",
            "# TYPE vodafone_station_docsis_channels gauge",
            f'vodafone_station_docsis_channels{{direction="downstream"}} {len(status.downstream)}',
            f'vodafone_station_docsis_channels{{direction="upstream"}} {len(status.upstream)}',
        ]
    )
    return "\n".join(lines) + "\n"


def _downstream_labels(status: DocsisStatus) -> list[dict[str, object]]:
    return [
        {
            **asdict(channel),
            "labels": {
                "channel_id": channel.channel_id,
                "channel_type": channel.channel_type,
                "frequency_mhz": channel.frequency_mhz,
                "modulation": channel.modulation,
                "lock_status": channel.lock_status,
            },
        }
        for channel in status.downstream
    ]


def _upstream_labels(status: DocsisStatus) -> list[dict[str, object]]:
    return [
        {
            **asdict(channel),
            "labels": {
                "channel_id": channel.channel_id,
                "channel_type": channel.channel_type,
                "frequency_mhz": channel.frequency_mhz,
                "modulation": channel.modulation,
                "ranging_status": channel.ranging_status,
            },
        }
        for channel in status.upstream
    ]


def _samples(metric: str, items: Iterable[dict[str, object]], key: str) -> list[str]:
    samples = []
    for item in items:
        value = item[key]
        if value is not None:
            samples.append(_sample(metric, item["labels"], value))
    return samples


def _sample(metric: str, labels: dict[str, str], value: object) -> str:
    label_text = ",".join(f'{name}="{_escape(value)}"' for name, value in labels.items())
    return f"{metric}{{{label_text}}} {value}"


def _timestamp(scraped_at: datetime | None) -> int:
    if scraped_at is None:
        return 0
    return int(scraped_at.timestamp())


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
