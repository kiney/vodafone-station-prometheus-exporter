from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from statistics import median


@dataclass(frozen=True)
class Finding:
    severity: str
    message: str


@dataclass(frozen=True)
class HealthReport:
    status: str
    first_scrape: datetime | None
    last_scrape: datetime | None
    scrape_count: int
    successful_scrapes: int
    failed_scrapes: int
    median_interval_seconds: float | None
    downstream_channels: int
    upstream_channels: int
    findings: list[Finding]


def analyze_sqlite(path: Path, hours: float | None = None) -> HealthReport:
    if not path.exists():
        raise FileNotFoundError(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        _validate_schema(conn)
        scrape_rows = conn.execute("SELECT * FROM scrapes ORDER BY scraped_at").fetchall()
        if hours is not None and scrape_rows:
            cutoff = _parse_datetime(scrape_rows[-1]["scraped_at"]) - timedelta(hours=hours)
            scrape_rows = [row for row in scrape_rows if _parse_datetime(row["scraped_at"]) >= cutoff]
        scrape_ids = [row["id"] for row in scrape_rows]
        downstream_rows = _rows_for_scrapes(conn, "downstream_channels", scrape_ids)
        upstream_rows = _rows_for_scrapes(conn, "upstream_channels", scrape_ids)

    return _analyze(scrape_rows, downstream_rows, upstream_rows)


def render_report(report: HealthReport, path: Path) -> str:
    lines = [
        f"DOCSIS health report: {path}",
        f"Status: {report.status}",
    ]
    if report.scrape_count == 0:
        lines.append("No scrapes found.")
        return "\n".join(lines) + "\n"

    first = report.first_scrape.isoformat() if report.first_scrape else "unknown"
    last = report.last_scrape.isoformat() if report.last_scrape else "unknown"
    success_rate = report.successful_scrapes / report.scrape_count * 100
    lines.extend(
        [
            f"Window: {first} to {last}",
            f"Scrapes: {report.scrape_count} total, {report.successful_scrapes} ok, "
            f"{report.failed_scrapes} failed ({success_rate:.1f}% success)",
        ]
    )
    if report.median_interval_seconds is not None:
        lines.append(f"Median interval: {_format_seconds(report.median_interval_seconds)}")
    lines.append(f"Channels: {report.downstream_channels} downstream, {report.upstream_channels} upstream")
    if report.findings:
        lines.append("Findings:")
        visible_findings = report.findings[:10]
        lines.extend(f"- {finding.severity}: {finding.message}" for finding in visible_findings)
        hidden = len(report.findings) - len(visible_findings)
        if hidden:
            lines.append(f"- INFO: {hidden} additional lower-priority finding(s) omitted")
    else:
        lines.append("Findings: no notable anomalies.")
    return "\n".join(lines) + "\n"


def _validate_schema(conn: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('scrapes', 'downstream_channels', 'upstream_channels')"
        )
    }
    missing = {"scrapes", "downstream_channels", "upstream_channels"} - tables
    if missing:
        raise ValueError(f"database is missing table(s): {', '.join(sorted(missing))}")


def _rows_for_scrapes(conn: sqlite3.Connection, table: str, scrape_ids: list[int]) -> list[sqlite3.Row]:
    if not scrape_ids:
        return []
    rows: list[sqlite3.Row] = []
    for start in range(0, len(scrape_ids), 500):
        chunk = scrape_ids[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(conn.execute(f"SELECT * FROM {table} WHERE scrape_id IN ({placeholders})", chunk).fetchall())
    return rows


def _analyze(
    scrapes: list[sqlite3.Row], downstream: list[sqlite3.Row], upstream: list[sqlite3.Row]
) -> HealthReport:
    if not scrapes:
        return HealthReport("UNKNOWN", None, None, 0, 0, 0, None, 0, 0, [Finding("WARN", "no scrape data")])

    findings: list[Finding] = []
    first = _parse_datetime(scrapes[0]["scraped_at"])
    last = _parse_datetime(scrapes[-1]["scraped_at"])
    successful = sum(1 for row in scrapes if row["success"])
    failed = len(scrapes) - successful
    failure_rate = failed / len(scrapes)
    if failure_rate >= 0.20:
        findings.append(Finding("CRITICAL", f"high scrape failure rate: {failed}/{len(scrapes)} failed"))
    elif failure_rate >= 0.05:
        findings.append(Finding("WARN", f"scrape failures observed: {failed}/{len(scrapes)} failed"))

    intervals = [
        (_parse_datetime(scrapes[index]["scraped_at"]) - _parse_datetime(scrapes[index - 1]["scraped_at"])).total_seconds()
        for index in range(1, len(scrapes))
    ]
    median_interval = median(intervals) if intervals else None

    downstream_channels = len({row["channel_id"] for row in downstream if row["channel_id"]})
    upstream_channels = len({row["channel_id"] for row in upstream if row["channel_id"]})
    _add_downstream_findings(findings, downstream)
    _add_upstream_findings(findings, upstream)

    status = _status(findings)
    return HealthReport(
        status=status,
        first_scrape=first,
        last_scrape=last,
        scrape_count=len(scrapes),
        successful_scrapes=successful,
        failed_scrapes=failed,
        median_interval_seconds=median_interval,
        downstream_channels=downstream_channels,
        upstream_channels=upstream_channels,
        findings=findings,
    )


def _add_downstream_findings(findings: list[Finding], downstream: list[sqlite3.Row]) -> None:
    unlocked = sum(1 for row in downstream if not row["locked"])
    if unlocked:
        findings.append(Finding("CRITICAL", f"downstream lock lost in {unlocked} channel sample(s)"))

    snr_values = [row["snr_db"] for row in downstream if row["snr_db"] is not None]
    if snr_values:
        very_low = sum(1 for value in snr_values if value <= 1.0)
        low = sum(1 for value in snr_values if 1.0 < value < 30.0)
        if very_low:
            findings.append(Finding("WARN", f"implausibly low downstream SNR in {very_low} sample(s)"))
        if low:
            findings.append(Finding("WARN", f"low downstream SNR below 30 dB in {low} sample(s)"))

    drifted_channels = []
    for channel_id, rows in _group_by_channel(downstream).items():
        drift = _drift(rows, "power_dbmv")
        if drift is not None and abs(drift) >= 0.5:
            drifted_channels.append(f"{channel_id} ({drift:+.1f} dB)")
    if drifted_channels:
        findings.append(Finding("INFO", f"downstream power drift on channel(s): {', '.join(drifted_channels[:8])}"))


def _add_upstream_findings(findings: list[Finding], upstream: list[sqlite3.Row]) -> None:
    failed_ranging = sum(1 for row in upstream if not row["ranging_success"])
    if failed_ranging:
        findings.append(Finding("WARN", f"upstream ranging failed in {failed_ranging} channel sample(s)"))

    high_power = [
        row
        for row in upstream
        if row["power_dbmv"] is not None and row["power_dbmv"] >= 51.5
    ]
    if high_power:
        findings.append(Finding("WARN", f"high upstream transmit power in {len(high_power)} sample(s)"))

    modulation_changes = []
    power_drifts = []
    for channel_id, rows in _group_by_channel(upstream).items():
        modulations = {row["modulation"] for row in rows if row["modulation"]}
        if len(modulations) > 1:
            modulation_changes.append(f"{channel_id} ({len(modulations)} states)")
        drift = _drift(rows, "power_dbmv")
        if drift is not None and abs(drift) >= 1.5:
            power_drifts.append(f"{channel_id} ({drift:+.1f} dB)")
    if modulation_changes:
        findings.append(Finding("INFO", f"upstream modulation changed on channel(s): {', '.join(modulation_changes)}"))
    if power_drifts:
        findings.append(Finding("INFO", f"upstream power drift on channel(s): {', '.join(power_drifts)}"))


def _group_by_channel(rows: list[sqlite3.Row]) -> dict[str, list[sqlite3.Row]]:
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        channel_id = row["channel_id"]
        if channel_id:
            groups.setdefault(channel_id, []).append(row)
    return groups


def _drift(rows: list[sqlite3.Row], column: str) -> float | None:
    values = [row[column] for row in rows if row[column] is not None]
    if len(values) < 2:
        return None
    return values[-1] - values[0]


def _status(findings: list[Finding]) -> str:
    severities = {finding.severity for finding in findings}
    if "CRITICAL" in severities:
        return "CRITICAL"
    if "WARN" in severities:
        return "WARN"
    if "INFO" in severities:
        return "OK"
    return "OK"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _format_seconds(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.1f}m"
