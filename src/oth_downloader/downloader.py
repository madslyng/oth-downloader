"""Crawling and downloading orchestration for Off The Hook episodes."""

from __future__ import annotations

import asyncio
import calendar
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from .manifest import Manifest
from .models import Episode, MonthPage, Status
from .scraper import ARCHIVE_INDEX_URL, fetch_text, parse_archive_index, parse_month_page

LogFn = Callable[[str], None]
MonthFn = Callable[[MonthPage], None]
EpisodeFn = Callable[[Episode], None]

CRAWL_CONCURRENCY = 8
CHUNK_SIZE = 1 << 16  # 64 KiB


async def crawl_archive_index(client: httpx.AsyncClient, log: LogFn) -> list[MonthPage]:
    log(f"Fetching archive index: {ARCHIVE_INDEX_URL}")
    html = await fetch_text(client, ARCHIVE_INDEX_URL)
    months = parse_archive_index(html, ARCHIVE_INDEX_URL)
    log(f"Archive index lists {len(months)} monthly pages "
        f"({months[0].year}-{months[-1].year})" if months else "No months found")
    return months


async def crawl_episodes(
    client: httpx.AsyncClient,
    months: list[MonthPage],
    on_month_start: MonthFn,
    on_month_done: MonthFn,
    on_episode: EpisodeFn,
    log: LogFn,
) -> list[Episode]:
    sem = asyncio.Semaphore(CRAWL_CONCURRENCY)
    episodes: list[Episode] = []
    lock = asyncio.Lock()

    async def visit(month: MonthPage) -> None:
        async with sem:
            on_month_start(month)
            try:
                html = await fetch_text(client, month.url)
                found = parse_month_page(html, month.url, month)
            except Exception as exc:  # noqa: BLE001 - report and continue crawling
                log(f"  ! failed to fetch {month.url}: {exc}")
                found = []
            async with lock:
                episodes.extend(found)
            for ep in found:
                on_episode(ep)
            on_month_done(month)

    await asyncio.gather(*(visit(m) for m in months))
    episodes.sort(key=lambda e: (e.year, e.month, e.basename))
    log(f"Discovered {len(episodes)} episodes across {len(months)} months")
    return episodes


def dest_path_for(episode: Episode, dest_root: Path) -> Path:
    month_name = calendar.month_name[episode.month] or f"month-{episode.month:02d}"
    folder = dest_root / f"{episode.year:04d}" / f"{episode.month:02d}-{month_name}"
    filename = episode.url.rsplit("/", 1)[-1]
    return folder / filename


async def download_episode(
    client: httpx.AsyncClient,
    episode: Episode,
    dest_root: Path,
    manifest: Manifest,
    on_progress: EpisodeFn,
) -> None:
    dest = dest_path_for(episode, dest_root)
    episode.dest_path = str(dest)

    if manifest.is_done(episode.basename, dest):
        episode.status = Status.SKIPPED
        episode.size_bytes = dest.stat().st_size
        episode.downloaded_bytes = episode.size_bytes
        on_progress(episode)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    episode.status = Status.DOWNLOADING
    on_progress(episode)

    try:
        async with client.stream("GET", episode.url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            episode.size_bytes = total
            downloaded = 0
            with open(tmp, "wb") as fh:
                async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                    fh.write(chunk)
                    downloaded += len(chunk)
                    episode.downloaded_bytes = downloaded
                    on_progress(episode)
        tmp.replace(dest)
        episode.status = Status.DONE
        episode.downloaded_bytes = dest.stat().st_size
        episode.size_bytes = episode.downloaded_bytes
        manifest.mark_done(episode.basename, episode.url, dest, episode.size_bytes)
    except Exception as exc:  # noqa: BLE001 - surface error, keep other downloads going
        episode.status = Status.FAILED
        episode.error = str(exc)
        manifest.mark_failed(episode.basename, episode.url, str(exc))
        tmp.unlink(missing_ok=True)
    finally:
        on_progress(episode)


async def download_all(
    client: httpx.AsyncClient,
    episodes: list[Episode],
    dest_root: Path,
    manifest: Manifest,
    workers: int,
    on_progress: EpisodeFn,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    sem = asyncio.Semaphore(workers)

    async def run(ep: Episode) -> None:
        if should_stop and should_stop():
            return
        async with sem:
            if should_stop and should_stop():
                return
            await download_episode(client, ep, dest_root, manifest, on_progress)

    await asyncio.gather(*(run(ep) for ep in episodes))
