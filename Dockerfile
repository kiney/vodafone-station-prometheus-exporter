FROM debian:bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/vodafone-station-exporter/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY vodafone_station_exporter ./vodafone_station_exporter

RUN python3 -m venv /opt/vodafone-station-exporter \
    && /opt/vodafone-station-exporter/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/vodafone-station-exporter/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/vodafone-station-exporter/bin/pip install --no-cache-dir .

RUN useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin exporter \
    && mkdir -p /config /data \
    && chown -R exporter:exporter /config /data

USER exporter
WORKDIR /data

VOLUME ["/config", "/data"]
EXPOSE 8018

CMD ["vodafone-station-exporter", "--config", "/config/config.yml"]
