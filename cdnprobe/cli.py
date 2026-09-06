"""Entry point. `serve` is what the container runs."""

from __future__ import annotations

import argparse
import sys
import threading

from . import config, stats, storage
from .daemon import Runner
from .web import serve


def cmd_serve(args) -> None:
    """Runs rounds in the background and serves the dashboard."""
    pause = config.round_pause()
    runner = Runner(pause)
    server = serve(runner)

    worker = threading.Thread(target=runner.run_forever, daemon=True)
    worker.start()

    print(f"dashboard  http://localhost:{config.WEB_PORT}", flush=True)
    print(f"pause between rounds: {config.describe_pause(pause)}", flush=True)
    if pause is None:
        print("manual mode - nothing runs until you press Run round", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", flush=True)
        runner.stop()
        server.shutdown()


def cmd_once(args) -> None:
    """A single round, then exit. Useful for a cron-style setup."""
    runner = Runner(pause=None)
    runner.run_round()
    print(stats.table(stats.aggregate(storage.load())))


def cmd_stats(args) -> None:
    print(stats.table(stats.aggregate(storage.load())))


def cmd_list(args) -> None:
    """Shows what the account actually offers - nothing here is hardcoded."""
    from .panel import Panel

    with Panel(headless=True) as panel:
        panel.ensure_logged_in()
        current = panel.current_cdn()
        print(f"playlist: {panel.playlist_url()}")
        print()
        panel.open_settings()
        for option in panel.cdn_options():
            mark = "  <- selected" if option.value == current.value else ""
            print(f"  {option.value:>3}  {option.label}{mark}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="cdnprobe", description="Measure ilook.tv CDN quality over time"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="run rounds and serve the dashboard"
                   ).set_defaults(func=cmd_serve)
    sub.add_parser("once", help="run a single round and exit"
                   ).set_defaults(func=cmd_once)
    sub.add_parser("stats", help="print the summary table"
                   ).set_defaults(func=cmd_stats)
    sub.add_parser("list", help="list the CDNs and playlist the account offers"
                   ).set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args.func = cmd_serve
    try:
        args.func(args)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
