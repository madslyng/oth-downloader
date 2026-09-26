# oth-downloader

A terminal (TUI) application that browses the [2600 "Off The Hook"](https://www.2600.com/offthehook/)
radio show archive, builds an overview of every episode ever published (1988-present), and
downloads each one at the highest available bitrate to local storage — organized by year and month.

## What it does

1. Fetches the archive index (`archive_ra.html`), which lists every monthly page from
   October 1988 through the current month.
2. Visits each monthly page concurrently and parses out every episode's MP3 links,
   preferring the `-128` (128kbps) file over the 16kbps one when both exist.
3. Shows a live TUI while it works: a crawl log, an episode table with per-file
   download progress, and overall stats (scanned months, done/active/pending/failed
   counts, bytes downloaded, throughput).
4. Downloads concurrently (configurable workers) into:

   ```
   <dest>/<year>/<month>-<MonthName>/<original-filename>.mp3
   ```

   e.g. `oth-downloads/2026/09-September/off_the_hook__20260923-128.mp3`

5. Tracks completed downloads in `<dest>/.oth-manifest.json` so re-running the app
   later (e.g. weekly, to pick up new episodes) skips everything already downloaded.

## Usage

```bash
uv run oth-downloader --dest /mnt/MEDIA_BACKUP/Backups/oth-downloads
```

or, after activating the venv:

```bash
python -m oth_downloader --dest /mnt/MEDIA_BACKUP/Backups/oth-downloads
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--dest PATH` | `/mnt/MEDIA_BACKUP/Backups/oth-downloads` | Destination root directory |
| `--workers N` | `3` | Concurrent downloads |
| `--since-year YYYY` | (none) | Only crawl/download episodes from this year onward |
| `--limit N` | (none) | Only download the first N discovered episodes (for testing) |
| `--dry-run` | off | Crawl and build the overview only; download nothing |

Press `q` at any time to quit. The app is idempotent — it's safe to stop and
re-run at any time:

- Fully downloaded episodes are recorded in the manifest and skipped instantly.
- A file that was interrupted mid-download (killed process, crash, etc.) is
  resumed via HTTP `Range` requests from wherever it left off, instead of
  starting over.
- New episodes published since your last run are discovered by the crawl and
  downloaded on their own — you don't need to re-download anything else.

## Notes

- The site is crawled politely: monthly pages are fetched with bounded concurrency
  (8 at a time), and downloads default to 3 concurrent workers.
- Full history is roughly 445 monthly pages, thousands of individual shows; a first
  full run will take a while and use significant disk space. Use `--since-year` to
  do an incremental/partial run.
