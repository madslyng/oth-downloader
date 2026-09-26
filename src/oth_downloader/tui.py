"""Textual TUI for browsing the Off The Hook archive and downloading episodes."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from .downloader import crawl_archive_index, crawl_episodes, dest_path_for, download_all
from .manifest import Manifest
from .models import Episode, MonthPage, Status
from .scraper import new_client

STATUS_STYLE = {
    Status.PENDING: "dim",
    Status.QUEUED: "dim",
    Status.DOWNLOADING: "bold yellow",
    Status.DONE: "bold green",
    Status.SKIPPED: "cyan",
    Status.FAILED: "bold red",
}


def human_size(n: int) -> str:
    if n <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


class StatsPanel(Static):
    """Live summary of crawl/download progress."""

    def __init__(self) -> None:
        super().__init__(id="stats")
        self._phase = "Starting..."
        self._months_done = 0
        self._months_total = 0
        self._episodes: list[Episode] = []
        self._bytes_start = 0
        self._start_time = time.monotonic()

    def set_phase(self, phase: str) -> None:
        self._phase = phase
        if phase.startswith("Downloading"):
            self._start_time = time.monotonic()
        self.refresh_stats()

    def set_months_progress(self, done: int, total: int) -> None:
        self._months_done = done
        self._months_total = total
        self.refresh_stats()

    def bind_episodes(self, episodes: list[Episode]) -> None:
        self._episodes = episodes
        self.refresh_stats()

    def refresh_stats(self) -> None:
        counts = Counter(e.status for e in self._episodes)
        total_bytes = sum(e.downloaded_bytes for e in self._episodes)
        elapsed = max(time.monotonic() - self._start_time, 1e-6)
        speed = total_bytes / elapsed
        lines = [
            f"[b]Phase:[/b] {self._phase}",
            f"[b]Months scanned:[/b] {self._months_done}/{self._months_total or '?'}",
            f"[b]Episodes:[/b] {len(self._episodes)} total  "
            f"[green]{counts[Status.DONE]} done[/green]  "
            f"[cyan]{counts[Status.SKIPPED]} skipped[/cyan]  "
            f"[yellow]{counts[Status.DOWNLOADING]} active[/yellow]  "
            f"[dim]{counts[Status.PENDING] + counts[Status.QUEUED]} pending[/dim]  "
            f"[red]{counts[Status.FAILED]} failed[/red]",
            f"[b]Downloaded this session:[/b] {human_size(total_bytes)}  "
            f"({human_size(int(speed))}/s)",
        ]
        self.update("\n".join(lines))


class OthDownloaderApp(App):
    CSS = """
    #stats { height: 6; border: round $accent; padding: 0 1; }
    #log { height: 12; border: round $secondary; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        dest_root: Path,
        workers: int = 3,
        since_year: int | None = None,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> None:
        super().__init__()
        self.dest_root = dest_root
        self.num_workers = workers
        self.since_year = since_year
        self.limit = limit
        self.dry_run = dry_run
        self.episodes: list[Episode] = []
        self._row_keys: dict[str, str] = {}
        self._last_ui_update: dict[str, float] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield StatsPanel()
            yield RichLog(id="log", highlight=False, markup=True, wrap=False)
            table = DataTable(id="episodes")
            (
                self._col_year,
                self._col_month,
                self._col_date,
                self._col_title,
                self._col_bitrate,
                self._col_size,
                self._col_status,
            ) = table.add_columns(
                "Year", "Month", "Date", "Title", "Bitrate", "Size", "Status"
            )
            yield table
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Off The Hook Downloader"
        self.sub_title = str(self.dest_root)
        self.set_interval(1.0, self.query_one(StatsPanel).refresh_stats)
        self.run_worker(self.pipeline(), exclusive=True)

    def log_line(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)

    # -- pipeline --------------------------------------------------------
    async def pipeline(self) -> None:
        stats = self.query_one(StatsPanel)
        table = self.query_one("#episodes", DataTable)
        stats.set_phase("Crawling archive index")

        async with new_client() as client:
            months = await crawl_archive_index(client, self.log_line)
            if self.since_year:
                months = [m for m in months if m.year >= self.since_year]
                self.log_line(f"Filtered to {len(months)} months >= {self.since_year}")
            stats.set_months_progress(0, len(months))

            stats.set_phase("Scanning monthly pages for episodes")
            done_counter = {"n": 0}

            def on_month_start(month: MonthPage) -> None:
                pass

            def on_month_done(month: MonthPage) -> None:
                done_counter["n"] += 1
                stats.set_months_progress(done_counter["n"], len(months))
                if done_counter["n"] % 20 == 0 or done_counter["n"] == len(months):
                    self.log_line(
                        f"Scanned {done_counter['n']}/{len(months)} months "
                        f"({len(self.episodes)} episodes so far)"
                    )

            def on_episode(ep: Episode) -> None:
                self.episodes.append(ep)
                dest = dest_path_for(ep, self.dest_root)
                ep.dest_path = str(dest)
                row_key = f"{ep.year}-{ep.month:02d}-{ep.basename}"
                self._row_keys[ep.basename] = row_key
                table.add_row(
                    str(ep.year),
                    f"{ep.month:02d}",
                    ep.date_label,
                    ep.title,
                    ep.bitrate,
                    "-",
                    Text(ep.status.value, style=STATUS_STYLE[ep.status]),
                    key=row_key,
                )

            await crawl_episodes(
                client, months, on_month_start, on_month_done, on_episode, self.log_line
            )
            stats.bind_episodes(self.episodes)

            if self.limit:
                self.episodes = self.episodes[: self.limit]
                self.log_line(f"Limiting to first {self.limit} episodes (testing mode)")

            self.log_line(
                f"Overview complete: {len(self.episodes)} episodes ready to download "
                f"into {self.dest_root}"
            )

            if self.dry_run:
                stats.set_phase("Dry run complete (no files downloaded)")
                return

            stats.set_phase(f"Downloading ({self.num_workers} workers)")
            manifest = Manifest(self.dest_root)
            self.dest_root.mkdir(parents=True, exist_ok=True)

            def on_progress(ep: Episode) -> None:
                now = time.monotonic()
                last = self._last_ui_update.get(ep.basename, 0.0)
                terminal = ep.status in (Status.DONE, Status.FAILED, Status.SKIPPED)
                if not terminal and now - last < 0.25:
                    return
                self._last_ui_update[ep.basename] = now
                row_key = self._row_keys.get(ep.basename)
                if row_key is None:
                    return
                size_txt = (
                    f"{human_size(ep.downloaded_bytes)}/{human_size(ep.size_bytes)}"
                    if ep.status == Status.DOWNLOADING
                    else human_size(ep.size_bytes or ep.downloaded_bytes)
                )
                status_txt = ep.status.value if not ep.error else f"failed: {ep.error[:30]}"
                table.update_cell(row_key, self._col_size, size_txt)
                table.update_cell(
                    row_key, self._col_status, Text(status_txt, style=STATUS_STYLE[ep.status])
                )
                if terminal:
                    stats.refresh_stats()

            await download_all(
                client,
                self.episodes,
                self.dest_root,
                manifest,
                self.num_workers,
                on_progress,
            )
            stats.refresh_stats()
            stats.set_phase("Done")
            self.log_line("[b green]All downloads complete.[/b green]")


def run_app(
    dest_root: Path,
    workers: int = 3,
    since_year: int | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> None:
    app = OthDownloaderApp(
        dest_root=dest_root,
        workers=workers,
        since_year=since_year,
        limit=limit,
        dry_run=dry_run,
    )
    app.run()
