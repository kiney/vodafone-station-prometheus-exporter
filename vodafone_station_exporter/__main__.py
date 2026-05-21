from __future__ import annotations

import argparse
import logging

from .app import create_app, run_daemon
from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Vodafone Station DOCSIS Prometheus exporter")
    parser.add_argument("--config", default="config.yml", help="YAML config file path (default: ./config.yml)")
    parser.add_argument("--once", action="store_true", help="scrape once and print metrics")
    parser.add_argument("--discover", action="store_true", help="probe known router endpoints without printing secrets")
    parser.add_argument("--save-login-page", help="write the router login HTML to this path for local inspection")
    parser.add_argument("--save-docsis-api", help="login and write /api/v1/sta_docsis_status JSON to this path")
    parser.add_argument("--debug-login", action="store_true", help="print sanitized router login diagnostics")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_file(args.config)

    if args.discover:
        from .discovery import discover_router

        for line in discover_router(config):
            print(line)
        return

    if args.save_login_page:
        from .discovery import save_login_page

        print(save_login_page(config, args.save_login_page))
        return

    if args.save_docsis_api:
        from .discovery import save_docsis_api

        print(save_docsis_api(config, args.save_docsis_api))
        return

    if args.debug_login:
        from .discovery import debug_login

        for line in debug_login(config):
            print(line)
        return

    if args.once:
        from .metrics import render_metrics

        app = create_app(config)
        state = app.config["EXPORTER_STATE"]
        state.scrape()
        status, scraped_at, error = state.snapshot()
        print(render_metrics(status, scraped_at, error), end="")
        return

    run_daemon(config)


if __name__ == "__main__":
    main()
