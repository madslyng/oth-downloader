"""Fetching and parsing of the 2600 Off The Hook archive site."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx

from .models import Episode, MonthPage, Status

ARCHIVE_INDEX_URL = "https://www.2600.com/offthehook/archive_ra.html"

USER_AGENT = "oth-downloader/0.1 (personal archival tool; +https://www.2600.com/offthehook/)"

_OPTION_RE = re.compile(
    r'<option\b[^>]*?\svalue="([^"]+)"[^>]*>\s*([A-Za-z]+)', re.IGNORECASE
)
_MP3_HREF_RE = re.compile(r'href="([^"]+?/mp3files/[^"]+?\.mp3)"', re.IGNORECASE)
_YEAR_DIR_RE = re.compile(r"/(\d{4})/(\d{2})(\d{2})\.html?$", re.IGNORECASE)
_BASENAME_RE = re.compile(
    r"^(?P<kind>off_the_hook(?:_overtime)?)__(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})(?P<part>[a-z]?)$"
)


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(30.0, connect=15.0),
        follow_redirects=True,
    )


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.text


def parse_archive_index(html: str, base_url: str) -> list[MonthPage]:
    """Parse archive_ra.html, returning every monthly page it links to."""
    months: list[MonthPage] = []
    seen: set[str] = set()
    for match in _OPTION_RE.finditer(html):
        raw_value, label = match.group(1), match.group(2)
        url = urljoin(base_url, raw_value)
        m = _YEAR_DIR_RE.search(url)
        if not m:
            continue
        year = int(m.group(1))
        month = int(m.group(2))
        if url in seen:
            continue
        seen.add(url)
        months.append(MonthPage(year=year, month=month, label=label, url=url))
    months.sort(key=lambda mp: (mp.year, mp.month))
    return months


def _title_for(kind: str, y: str, mth: str, d: str, part: str) -> str:
    label = "Off The Hook Overtime" if kind.endswith("overtime") else "Off The Hook"
    title = f"{label} - {y}-{mth}-{d}"
    if part:
        title += f" (part {part})"
    return title


def parse_month_page(html: str, base_url: str, month: MonthPage) -> list[Episode]:
    """Parse a monthly page, returning one Episode per show at its highest bitrate."""
    by_basename: dict[str, dict[str, str]] = {}
    for match in _MP3_HREF_RE.finditer(html):
        href = match.group(1)
        url = urljoin(base_url, href)
        filename = url.rsplit("/", 1)[-1]
        stem = filename[:-4]  # strip ".mp3"
        if stem.endswith("-128"):
            basename = stem[: -len("-128")]
            bitrate = "128k"
        else:
            basename = stem
            bitrate = "16k"
        entry = by_basename.setdefault(basename, {})
        # Prefer 128k if both variants are seen for this basename.
        if bitrate == "128k" or "128k" not in entry:
            entry[bitrate] = url
        entry.setdefault(bitrate, url)

    episodes: list[Episode] = []
    for basename, variants in by_basename.items():
        if "128k" in variants:
            bitrate, url = "128k", variants["128k"]
        else:
            bitrate, url = "16k", variants["16k"]

        m = _BASENAME_RE.match(basename)
        if m:
            title = _title_for(m["kind"], m["y"], m["m"], m["d"], m["part"])
            date_label = f"{m['y']}-{m['m']}-{m['d']}"
        else:
            title = basename
            date_label = f"{month.year:04d}-{month.month:02d}"

        episodes.append(
            Episode(
                year=month.year,
                month=month.month,
                date_label=date_label,
                basename=basename,
                title=title,
                url=url,
                bitrate=bitrate,
                source_page=base_url,
                status=Status.PENDING,
            )
        )

    episodes.sort(key=lambda e: e.basename)
    return episodes
