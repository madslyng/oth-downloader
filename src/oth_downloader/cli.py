"""CLI entry point for the Off The Hook downloader TUI."""

from __future__ import annotations

import argparse
from pathlib import Path

from .tui import run_app

DEFAULT_DEST = Path("/mnt/MEDIA_BACKUP/Backups/oth-downloads")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="oth-downloader",
        description="Browse and download the 2600 'Off The Hook' radio archive.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"Destination directory (default: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of concurrent downloads (default: 3)",
    )
    parser.add_argument(
        "--since-year",
        type=int,
        default=None,
        help="Only crawl/download episodes from this year onward",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only download the first N discovered episodes (useful for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Crawl and build the overview only; do not download anything",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run_app(
        dest_root=args.dest,
        workers=args.workers,
        since_year=args.since_year,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
