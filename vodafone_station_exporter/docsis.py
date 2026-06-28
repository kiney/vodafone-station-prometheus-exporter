from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
import re


NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class DownstreamChannel:
    channel_id: str
    channel_type: str
    frequency_mhz: str
    modulation: str
    power_dbmv: float | None
    power_dbuv: float | None
    snr_db: float | None
    locked: bool
    lock_status: str


@dataclass(frozen=True)
class UpstreamChannel:
    channel_id: str
    channel_type: str
    frequency_mhz: str
    modulation: str
    power_dbmv: float | None
    power_dbuv: float | None
    ranging_success: bool
    ranging_status: str


@dataclass(frozen=True)
class DocsisStatus:
    downstream: list[DownstreamChannel]
    upstream: list[UpstreamChannel]

    @property
    def total_channels(self) -> int:
        return len(self.downstream) + len(self.upstream)


def parse_docsis_status(raw: str) -> DocsisStatus:
    text = html_to_text(raw) if _looks_like_html(raw) else raw
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    downstream_lines = _section_lines(lines, "Downstream-Kanäle", "Upstream-Kanäle")
    upstream_lines = _section_lines(lines, "Upstream-Kanäle", None)
    return DocsisStatus(
        downstream=[channel for line in downstream_lines if (channel := _parse_downstream(line))],
        upstream=[channel for line in upstream_lines if (channel := _parse_upstream(line))],
    )


def parse_docsis_json(payload: dict[str, Any]) -> DocsisStatus:
    data = payload.get("data", payload)
    downstream_raw = [
        *_as_list(_first_present(data, ("ofdm_downstream", "ofdmDownstream"))),
        *_as_list(_first_present(data, ("downstream", "Downstream", "ds", "Ds", "docsisDownstream", "downstreamChannels"))),
    ]
    upstream_raw = [
        *_as_list(_first_present(data, ("ofdma_upstream", "ofdmaUpstream"))),
        *_as_list(_first_present(data, ("upstream", "Upstream", "us", "Us", "docsisUpstream", "upstreamChannels"))),
    ]
    return DocsisStatus(
        downstream=[_downstream_from_mapping(item) for item in downstream_raw if isinstance(item, dict)],
        upstream=[_upstream_from_mapping(item) for item in upstream_raw if isinstance(item, dict)],
    )


def html_to_text(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw)
    return "\n".join(part.strip() for part in parser.parts if part.strip())


def _looks_like_html(raw: str) -> bool:
    prefix = raw[:2048].lower()
    return "<html" in prefix or "<table" in prefix or "<body" in prefix or "</" in prefix


def _section_lines(lines: list[str], start: str, end: str | None) -> list[str]:
    try:
        start_index = lines.index(start) + 1
    except ValueError:
        return []
    if end is None:
        end_index = len(lines)
    else:
        try:
            end_index = lines.index(end, start_index)
        except ValueError:
            end_index = len(lines)
    return lines[start_index:end_index]


def _parse_downstream(line: str) -> DownstreamChannel | None:
    cells = _cells(line)
    if len(cells) < 7 or not cells[0].isdigit():
        return None
    power_dbmv, power_dbuv = _split_power(cells[4])
    return DownstreamChannel(
        channel_id=cells[0],
        channel_type=cells[1],
        frequency_mhz=cells[2],
        modulation=cells[3],
        power_dbmv=power_dbmv,
        power_dbuv=power_dbuv,
        snr_db=_number(cells[5]),
        locked=_is_yes(cells[6]),
        lock_status=cells[6],
    )


def _downstream_from_mapping(item: dict[str, Any]) -> DownstreamChannel:
    power_dbmv, power_dbuv = _split_power(str(_value(item, "power", "Power", "power_ofdm", "PowerLevel", "signalStrength", "SignalStrength", "rxPower", default="")))
    power_dbuv = _with_dbuv(power_dbmv, power_dbuv)
    start_frequency = _value(item, "start_frequency", "startFrequency", default=None)
    end_frequency = _value(item, "end_frequency", "endFrequency", default=None)
    return DownstreamChannel(
        channel_id=str(_value(item, "channelId", "ChannelId", "channel_id", "channelid", "channelid_ofdm", "id", "ID", default="")),
        channel_type=str(_value(item, "channelType", "ChannelType", "type", "Type", default="")),
        frequency_mhz=_frequency_label(item, start_frequency, end_frequency),
        modulation=str(_value(item, "modulation", "Modulation", "FFT", "FFT_ofdm", default="")),
        power_dbmv=_number_value(_value(item, "powerDbmv", "power_dbmv", "PowerDbmv", default=None), power_dbmv),
        power_dbuv=_number_value(_value(item, "powerDbuv", "power_dbuv", "PowerDbuv", default=None), power_dbuv),
        snr_db=_number_value(_value(item, "snr", "SNR", "SNR_ofdm", "SNRLevel", "mer", "MER", "snrMer", default=None), None),
        locked=_is_yes(str(_value(item, "lockStatus", "LockStatus", "locked", "locked_ofdm", "Locked", default=""))),
        lock_status=str(_value(item, "lockStatus", "LockStatus", "locked", "locked_ofdm", "Locked", default="")),
    )


def _parse_upstream(line: str) -> UpstreamChannel | None:
    cells = _cells(line)
    if len(cells) < 6 or not cells[0].isdigit():
        return None
    power_dbmv, power_dbuv = _split_power(cells[4])
    return UpstreamChannel(
        channel_id=cells[0],
        channel_type=cells[1],
        frequency_mhz=cells[2],
        modulation=cells[3],
        power_dbmv=power_dbmv,
        power_dbuv=power_dbuv,
        ranging_success=cells[5].casefold() in {"erfolgreich", "success", "successful"},
        ranging_status=cells[5],
    )


def _upstream_from_mapping(item: dict[str, Any]) -> UpstreamChannel:
    power_dbmv, power_dbuv = _split_power(str(_value(item, "power", "Power", "PowerLevel", "signalStrength", "SignalStrength", "txPower", default="")))
    power_dbuv = _with_dbuv(power_dbmv, power_dbuv)
    ranging_status = str(_value(item, "rangingStatus", "RangingStatus", "ranging", "Ranging", "LockStatus", "locked", default=""))
    start_frequency = _value(item, "start_frequency", "startFrequency", default=None)
    end_frequency = _value(item, "end_frequency", "endFrequency", default=None)
    return UpstreamChannel(
        channel_id=str(_value(item, "channelId", "ChannelId", "channel_id", "channelidup", "id", "ID", default="")),
        channel_type=str(_value(item, "channelType", "ChannelType", "type", "Type", default="")),
        frequency_mhz=_frequency_label(item, start_frequency, end_frequency),
        modulation=str(_value(item, "modulation", "Modulation", "FFT", default="")),
        power_dbmv=_number_value(_value(item, "powerDbmv", "power_dbmv", "PowerDbmv", default=None), power_dbmv),
        power_dbuv=_number_value(_value(item, "powerDbuv", "power_dbuv", "PowerDbuv", default=None), power_dbuv),
        ranging_success=ranging_status.casefold() in {"erfolgreich", "success", "successful", "completed", "active", "locked", "operate"},
        ranging_status=ranging_status,
    )


def _cells(line: str) -> list[str]:
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t") if cell.strip()]
    return [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]


def _split_power(value: str) -> tuple[float | None, float | None]:
    values = [_to_float(match.group(0)) for match in NUMBER_RE.finditer(value)]
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], None
    return values[0], values[1]


def _number(value: str) -> float | None:
    match = NUMBER_RE.search(value)
    if not match:
        return None
    return _to_float(match.group(0))


def _number_value(value: Any, default: float | None) -> float | None:
    if value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    return _number(str(value)) if str(value) else default


def _with_dbuv(power_dbmv: float | None, power_dbuv: float | None) -> float | None:
    if power_dbuv is not None:
        return power_dbuv
    if power_dbmv is None:
        return None
    return power_dbmv + 60


def _frequency_label(item: dict[str, Any], start_frequency: Any, end_frequency: Any) -> str:
    if start_frequency and end_frequency:
        return f"{_strip_unit(start_frequency)}~{_strip_unit(end_frequency)}"
    return str(_value(item, "frequency", "Frequency", "freq", "Freq", "CentralFrequency", "CentralFrequency_ofdm", default=""))


def _strip_unit(value: Any) -> str:
    number = _number(str(value))
    if number is None:
        return str(value)
    return f"{number:g}"


def _first_present(data: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data:
            return data[key]
    for value in data.values():
        if isinstance(value, dict):
            found = _first_present(value, keys)
            if found is not None:
                return found
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _value(item: dict[str, Any], *keys: str, default: Any) -> Any:
    for key in keys:
        if key in item:
            return item[key]
    lowered = {str(key).casefold(): value for key, value in item.items()}
    for key in keys:
        if key.casefold() in lowered:
            return lowered[key.casefold()]
    return default


def _to_float(value: str) -> float:
    return float(value.replace(",", "."))


def _is_yes(value: str) -> bool:
    return value.strip().casefold() in {"ja", "yes", "true", "locked", "1"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self._cell is not None:
            self._cell.append(data.strip())
        elif self._row is None:
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            value = " ".join(part for part in self._cell if part).strip()
            if value:
                self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.parts.append("\t".join(self._row))
            self._row = None
