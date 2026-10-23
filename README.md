# Newsarr

**Newsarr** is a self-hosted newspaper and magazine collection manager — think
*Radarr/Sonarr, but for print*. It tracks the titles you follow, searches your
**Prowlarr** instance for new issues, sends them to **qBittorrent**, and files the
finished PDFs/EPUBs into a tidy library.

It borrows the *patterns* of the Servarr family (publications ≈ movies/series,
issues ≈ episodes, a provider-agnostic indexer layer, a download-client layer, a
queue, and a library importer) but stays a small, readable standalone codebase.

```
┌──────────┐   search    ┌───────────┐   grab    ┌──────────────┐   move   ┌─────────┐
│ Newsarr  │ ──────────▶ │ Prowlarr  │ ────────▶ │ qBittorrent  │ ───────▶ │ Library │
│  (API)   │ ◀────────── │ (indexers)│           │  (client)    │          │ folders │
└──────────┘   releases  └───────────┘           └──────────────┘          └─────────┘
      ▲
      │ REST
┌──────────┐
│ React UI │
└──────────┘
```

## Features

### Library and catalog
- **Track publications** — title, keywords, Newznab categories, language,
  country, preferred format, monitored flag, and a per-publication library folder.
- **Issue catalog** — describe a publishing schedule (daily, weekly on a chosen
  weekday, every two weeks, monthly, or quarterly) and a start date. Newsarr
  generates every expected issue and tracks **owned / missing / grabbed /
  ignored** per date.
- **Cover images** — upload a JPG/PNG/WebP/GIF cover (or point at an external
  image URL).
- **Find gaps** — scan the library folder to mark existing files as owned,
  search one missing issue by date, or search and grab all missing issues.
- **One-click issue download** — **Auto-download** searches Prowlarr for a
  specific issue and grabs the date-matched release with the most seeders.

### Acquisition
- **Search Prowlarr** — aggregate search across every indexer configured in your
  Prowlarr instance, directly from a publication's page.
- **Grab releases** into qBittorrent; magnet links and `.torrent` URLs both work.
- **Automatic tracking** — an RSS-style poll plus a scheduled catch-up search
  find and grab new issues for monitored publications.
- **Queue and history** — live progress, retry, remove, diagnostics, and status
  per grab.
- **Automatic import** — completed downloads are moved into the library with a
  configurable naming scheme (for example `The Guardian - 2026-10-21.pdf`).

### Operations
- **Runtime configuration** — Prowlarr and qBittorrent credentials live in the
  database and are edited in the UI. Secrets are never returned to the browser.
- **Single process** — the FastAPI app serves both the API and the built React
  UI; no external database or message broker is required.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12+ / FastAPI / SQLAlchemy 2 / SQLite |
| Frontend | React 19 + TypeScript + Vite + React Router |
| HTTP client | httpx |
| Storage | SQLite at `~/.config/newsarr/newsarr.db` by default |

## Prerequisites

- Python 3.12 or newer, or Docker with Compose v2
- Node.js with a version supported by Vite 8 (only for local builds)
- A reachable **Prowlarr** instance and API key
- A reachable **qBittorrent** WebUI with its username/password
- A library directory that the Newsarr process can write to

## Quick start

### Using the Makefile

```bash
make setup       # create backend/.venv, install Python + frontend deps
make backend     # API with autoreload on http://localhost:7878
make frontend    # Vite dev server on http://localhost:5173
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to port `7878`.

### Manual setup

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py          # http://localhost:7878

# Frontend (in another terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

### Production-style single process

```bash
cd frontend && npm run build     # emits frontend/dist
cd ../backend && .venv/bin/python run.py
```

The API serves the built UI at <http://localhost:7878>. `run.py` enables
autoreload; for a long-running deployment, run the same app with a production
Uvicorn/Gunicorn configuration and put it behind your reverse proxy of choice.

### Docker

The image is a multi-stage build: Node builds the React frontend, then a slim
Python runtime serves the API and the static UI from one process.

```bash
docker compose up -d --build
# or: make docker-up
```

Open <http://localhost:7878>. Application data lives in the `newsarr-data` named
volume (`/data` in the container). Stop it with:

```bash
docker compose down
# or: make docker-down
```

To publish a different host port, set `NEWSARR_HTTP_PORT`:

```bash
NEWSARR_HTTP_PORT=8080 docker compose up -d
```

Logs and health:

```bash
docker compose logs -f newsarr
docker inspect --format '{{.State.Health.Status}}' newsarr
```

The container runs as UID/GID **1000** by default. If your bind mounts use
different ownership, set `PUID`/`PGID` when building:

```bash
PUID=1001 PGID=1001 docker compose up -d --build
```

If the `newsarr-data` volume already exists, changing UID/GID does not rewrite
its ownership; `chown` `/data` in a one-off container or recreate the volume.

To use a library or download directory outside the named volume, uncomment the
bind mount in `docker-compose.yml`:

```yaml
volumes:
  - newsarr-data:/data
  - /path/to/media:/media
```

Then set **Library root** to `/media/library` in Settings. If qBittorrent also
runs in Docker, mount the same host directory at the same container path in
both containers and set qBittorrent's save path accordingly. The container's
UID/GID must be able to read the completed downloads and write the library.

You can also build and run without Compose:

```bash
docker build -t newsarr .
docker run -d --name newsarr \
  -p 7878:7878 \
  -v newsarr-data:/data \
  --restart unless-stopped \
  newsarr
```

The image exposes port `7878` and includes a `/api/v1/health` health check.

### Publishing to GitHub Container Registry

`.github/workflows/docker-publish.yml` builds the image and publishes it to
**GitHub Container Registry** using the repository's built-in `GITHUB_TOKEN`.
No extra secrets are required.

| Trigger | Published tags |
|---|---|
| Push to `main` | `main`, `sha-<commit>`, `latest` |
| Push a tag like `v1.2.3` | `1.2.3`, `1.2`, `1`, `latest`, `sha-<commit>` |
| Pull request | Build only, no push |
| Manual workflow run | Same rules for the selected ref |

The image name is the repository path lowercased:
`ghcr.io/taumille/newsarr`.

1. Push the workflow to `main`:

   ```bash
   git add .github/workflows/docker-publish.yml
   git commit -m "Publish container image to GHCR"
   git push
   ```

2. Watch the **Actions → Publish container** run. The package appears under the
   repository's **Packages** section.

3. New GHCR packages are private by default. To allow anonymous pulls, open the
   package page → **Package settings** → **Danger Zone** → **Change visibility**
   → **Public**. Keep it private if you prefer authenticated pulls.

4. Pull the published image:

   ```bash
   docker pull ghcr.io/taumille/newsarr:latest
   ```

5. Use the registry image with Compose instead of a local build:

   ```bash
   export NEWSARR_IMAGE=ghcr.io/taumille/newsarr:latest
   docker compose pull newsarr
   docker compose up -d --no-build
   ```

If the workflow cannot push, check **Settings → Actions → General → Workflow
permissions** and allow read/write permissions (the workflow explicitly requests
`packages: write`). For private packages, authenticate before pulling:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
```

The token needs at least the `read:packages` scope.

> On this machine the system npm may fail with
> `Class extends value undefined is not a constructor or null`. If so, use the
> bundled wrapper: `node ../tools/npm.js install` and
> `node ../tools/npm.js run build` from `frontend/`.

## Configuration

### Bootstrap environment variables

These are read before the database is opened:

| Variable | Default | Meaning |
|---|---|---|
| `NEWSARR_DATA_DIR` | `~/.config/newsarr` | Database, covers, and default library location. |
| `NEWSARR_HOST` | `0.0.0.0` | API bind address. |
| `NEWSARR_PORT` | `7878` | API port. |
| `NEWSARR_FRONTEND_DIR` | `frontend/dist` | Built UI served by the API. |
| `NEWSARR_QUEUE_POLL_SECONDS` | `20` | How often the scheduler reconciles the download queue. |

### User settings

Everything else is stored in the SQLite `settings` table and edited on the
**Settings** page:

| Setting | Default | Meaning |
|---|---|---|
| `prowlarr_url` / `prowlarr_api_key` | empty | Prowlarr base URL and API key. |
| `qbittorrent_url` | empty | qBittorrent WebUI URL. |
| `qbittorrent_username` / `qbittorrent_password` | empty | qBittorrent credentials. |
| `qbittorrent_category` | `newsarr` | Category assigned to grabbed torrents. |
| `qbittorrent_save_path` | empty | Optional save path passed to qBittorrent. |
| `library_root` | `<data_dir>/library` | Root of the imported library. |
| `naming_template` | `{title} - {date}` | File name template; supports `{title}` and `{date}`. |
| `rss_sync_enabled` | `true` | Enable the recent-release poll. |
| `rss_sync_interval_minutes` | `30` | Minimum 60 seconds. |
| `rss_recent_hours` | `72` | Look-back window for the RSS sync. |
| `auto_search_enabled` | `true` | Enable the catch-up search. |
| `auto_search_interval_minutes` | `360` | Minimum 60 seconds. |
| `auto_search_recent_days` | `30` | Look-back window when a publication has no history. |
| `auto_search_max_grabs` | `3` | Maximum grabs per publication per run. |

Both integration sections have a **Test connection** button. Prowlarr
credentials are sent as `X-Api-Key`; qBittorrent is logged into first and then
called with a matching `Referer`/`Origin` so CSRF/Host-header protection works.

## Using Newsarr

1. Open **Settings** and configure Prowlarr, qBittorrent, and the library root.
2. Go to **Add publication** and enter the title, search keywords, and Newznab
   categories. For example: *Le Canard Enchaîné*, keyword `pdf`, category
   `7010`.
3. Optionally set a schedule: frequency `weekly`, publication day `Wednesday`,
   calendar start date `2020-01-01`. Newsarr generates every Wednesday since
   that date.
4. Open the publication. Use **Search** for the general release list, or use the
   **Issues** panel to target one specific date.
5. **Grab** a result. It appears in the **Queue**.
6. The scheduler polls qBittorrent. When the download finishes, Newsarr imports
   the file into the library and marks the matching issue **owned**.

## Issue catalog and owned/missing tracking

A publication can describe its publishing schedule:

| Field | Example |
|---|---|
| Frequency | `weekly` |
| Publication day | Wednesday (Monday = 0) |
| Calendar start date | `2020-01-01` |

On create/update, Newsarr generates one **Issue** per scheduled date from the
start date through today. The calendar is also refreshed during automatic
search, so it keeps rolling forward as weeks and months pass.

### Issue statuses

| Status | Meaning |
|---|---|
| **missing** | Stored as `expected`, but the date has passed. This is an issue you do not have. |
| **upcoming** | Stored as `expected`; the date is still in the future. |
| **grabbed** | A download is queued or in progress for this issue. |
| **owned** | The file is in the library (imported, found by a scan, or marked manually). |
| **ignored** | Deliberately skipped; kept when the calendar is regenerated. |

`missing` is computed, not stored: an issue is missing when its stored status is
`expected` and its date is on or before today.

### How ownership is detected

1. **On import** — the importer matches the download's publish date (falling
   back to a date in the final filename, then the import date) and marks that
   issue owned.
2. **On demand: Scan library** — walks the publication's library folder
   recursively and reads a date from each filename. Supported forms include:
   - `2020-01-08`
   - `08-01-2020`
   - `20200108`
   - `8 January 2020`
   - `8 janvier 2020`
3. **Manual override** — use **Mark owned**, **Mark missing**, or **Ignore** on
   any issue.

Files without a parseable date are skipped by the scanner. The accepted file
extensions are PDF, EPUB, MOBI, AZW3, CBZ, CBR, DJVU, ZIP, and RAR.

### Searching for missing issues

- **Per issue: Search** — queries Prowlarr with the publication title and issue
  date, filters results to releases whose title or publish date matches the
  issue date within ±1 day, and lets you grab one.
- **Per issue: Auto-download** — does the same date-matched search, then
  automatically grabs the usable release with the **highest seeder count**
  (newest wins ties). The button is only enabled for missing/upcoming issues.
- **⤓ Search all missing** — searches once for the publication, matches releases
  to missing dates (newest first), and grabs up to the requested limit (10 from
  the UI). Release choice prefers the publication's preferred format, then
  seeders, then newest publish date.

Release date matching prefers a date embedded in the release title, because an
indexer's `publishDate` can be an upload date rather than the issue date.

### Covers

Uploaded covers are stored under `NEWSARR_DATA_DIR/covers/<publication-id>.<ext>`
and served by the API. The upload is limited to 10 MB and accepts JPEG, PNG,
WebP, and GIF extensions. If no image is uploaded, the `cover_url` field can
point at an external image. Cover files are never committed to the repository.

## Automatic tracking

Newsarr runs three cadences from one in-process scheduler:

| Task | Default cadence | Behaviour |
|---|---|---|
| **Queue sync** | every 20 s | Reconciles active downloads with qBittorrent and imports completed ones. |
| **RSS sync** | every 30 min | Searches for releases published in a short recent window (default 72 h) and grabs new issues quickly. |
| **Auto search** | every 6 h | Thorough catch-up search within a look-back window (default 30 days), capped at *Max grabs per run* (default 3). |

A release is grabbed only if it is:

- **relevant** — it shares at least one title token of four or more characters
  with the publication,
- **not already grabbed** — de-duplicated by GUID and normalized title,
- **not older than the newest issue already recorded** — so an automatic search
  does not pull in an old backlog; the configured look-back window applies when
  the publication has no history,
- within the configured grab cap.

Manual triggers:

- **Library → ⤓ Auto-search all** runs the catch-up search for every monitored
  publication.
- **A publication → ⤓ Auto-search** runs it for that title only.
- `POST /api/v1/tasks/rss-sync` and `POST /api/v1/tasks/auto-search`.

## API

All endpoints are under `/api/v1`. Interactive OpenAPI docs are available at
`/docs`; the health probe is `/api/v1/health`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/system/status` | Version, counts, configuration status. |
| GET/POST | `/publications` | List / create publications. |
| GET/PUT/DELETE | `/publications/{id}` | Read / update / remove a publication. |
| POST | `/publications/{id}/search` | Search Prowlarr for that publication. |
| POST | `/publications/{id}/auto-search` | Run the automatic search for one publication. |
| POST/GET/DELETE | `/publications/{id}/cover` | Upload / read / remove a cover image. |
| GET | `/publications/{id}/issues` | List the issue catalog plus a summary. Supports `status`, `from_date`, `to_date`, `offset`, `limit`. |
| POST | `/publications/{id}/issues/generate` | Rebuild the expected-issue calendar. |
| POST | `/publications/{id}/issues/scan` | Match library files to issues. |
| POST | `/publications/{id}/issues/search-missing` | Search and grab missing issues. |
| GET/PATCH | `/issues/{id}` | Read / update one issue (status, label, notes, file path). |
| POST | `/issues/{id}/search` | Search Prowlarr for one dated issue. |
| POST | `/issues/{id}/auto-grab` | Search and grab the most-seeded release for an issue. |
| POST | `/issues/{id}/grab` | Grab a specific release for an issue. |
| GET | `/search?query=` | Ad-hoc Prowlarr search. |
| GET/POST | `/queue` | List the queue / grab a release. |
| GET | `/queue/diagnostics` | Compare stored records with qBittorrent torrents. |
| GET/DELETE | `/queue/{id}` | Inspect / remove a download. |
| POST | `/queue/{id}/retry` | Recover the hash and re-check a failed download. |
| POST | `/queue/sync` | Force a queue/client reconcile. |
| GET/PUT | `/settings` | Read / update configuration. |
| POST | `/settings/test/prowlarr` | Test Prowlarr credentials before saving. |
| POST | `/settings/test/qbittorrent` | Test qBittorrent credentials before saving. |
| GET | `/settings/prowlarr/indexers` | List indexers visible to Prowlarr. |
| POST | `/tasks/rss-sync` | Run the RSS sync now. |
| POST | `/tasks/auto-search` | Run the catch-up auto search now. |

`GET /settings` strips secrets and reports `prowlarr_api_key_set` /
`qbittorrent_password_set` instead. Sending a blank secret leaves the stored one
untouched.

## Project layout

```text
Dockerfile                  # multi-stage frontend + Python runtime image
docker-compose.yml          # single-service deployment with a data volume
.dockerignore
.github/workflows/
  docker-publish.yml        # build + publish to GitHub Container Registry
backend/
  run.py                    # uvicorn launcher
  app/
    main.py                 # FastAPI app, lifespan, scheduler, SPA fallback
    config.py               # bootstrap environment settings
    database.py             # SQLite engine/session + lightweight migrations
    models.py               # Publication, Issue, DownloadRecord, AppSetting
    schemas.py              # public Pydantic API surface
    api/                    # system, publications, issues, search, queue,
                            # settings, tasks routers
    services/               # Prowlarr, qBittorrent, torrent hashing, grab,
                            # sync, library import, issue catalog, autosearch
  tests/                    # mock-backed integration and unit tests
frontend/
  src/
    api.ts                  # typed fetch wrapper
    App.tsx                 # routes and sidebar
    pages/                  # Library, Add, Detail, Queue, Settings
    components/             # publication form, cover panel, issue library
    styles.css              # dark UI theme
tools/
  npm, npm.js               # workaround for the broken system npm
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the data model, request/background
flows, and extension points.

## Tests

```bash
make test
```

This runs, in order:

| Test | Coverage |
|---|---|
| `tests/e2e_smoke.py` | Mock Prowlarr + qBittorrent: search → grab → sync → import. |
| `tests/qbit_error_paths.py` | qBittorrent login failure messages (403, 401, bad credentials). |
| `tests/torrent_hash.py` | Bencode decoder and info-hash maths. |
| `tests/background_loop.py` | Background queue poll updates progress without a manual sync. |
| `tests/autosearch.py` | Relevance, de-duplication, cutoff, and grab selection. |
| `tests/issues.py` | Schedule generation, date parsing, folder scan, covers, statuses. |
| `tests/issue_auto_grab.py` | Most-seeded selection, auto-grab endpoint, status guard. |

Frontend checks:

```bash
cd frontend
npm run typecheck
npm run build
```

## Troubleshooting

### A download stays at 0% in the Queue

Newsarr identifies a grabbed download by its BitTorrent **info hash**, computed
directly from the `.torrent` file or from the `btih` value in a magnet link. The
queue sync fetches the full torrent list, recovers hashes from stored magnets or
by re-downloading the release's `.torrent`, falls back to name matching, and logs
a warning for anything it cannot match.

If a row is stuck:

1. Open **Queue → Diagnostics** (`/api/v1/queue/diagnostics`). It shows every
   qBittorrent torrent next to every Newsarr record and how each matched
   (`matched_by`: `hash`, `magnet`, `name`, or `null`).
2. Click **Re-check** on the row to recompute its hash and re-sync.
3. If `matched_by` is non-null but progress is still `0`, the torrent is still at
   0% in qBittorrent. States such as `stalledDL` or `metaDL` usually mean the
   payload or tracker is unreachable.

If a row cannot be matched at all, remove it and grab the release again; new
grabs always store the computed hash.

### qBittorrent test fails with 403 or 401

qBittorrent requires authentication on every API endpoint except
`/api/v2/auth/login`. With CSRF protection enabled (the default), it also checks
the `Origin`/`Referer` header against the request's `Host`. Newsarr logs in
first and sends a matching `Referer`, so these errors point at the real cause:

- **"Your IP is most likely temporarily banned"** — too many failed logins.
  Wait a few minutes, then check the username/password.
- **"401 ... CSRF / Host-header protection"** — the configured URL host does not
  match how qBittorrent is reached. Use the same host/IP as in the browser, or
  in qBittorrent's **Options → WebUI** disable *Host header validation* and
  *CSRF protection*, or add the host to the whitelist.
- **"Incorrect qBittorrent username or password"** — credentials are wrong.

If Newsarr and qBittorrent run on the same host, enabling *Bypass authentication
for clients on localhost* in qBittorrent is the simplest fix.

### Prowlarr searches fail

Check that the URL is reachable from the Newsarr process and that the API key
belongs to the same Prowlarr instance. Search errors are returned as HTTP `502`
with the upstream message. The **Prowlarr indexers** check on the Settings page
lists the indexers Prowlarr will search.

### An existing file was not marked owned

The scanner only matches dates embedded in file names, so rename the file to
include one of the supported date forms, or use **Mark owned** on the issue.
The scan looks in `<library_root>/<publication folder or slug>/`.

### Library import fails

The library root must be writable by the Newsarr process, and qBittorrent's
save path must be visible at the same location (or on a shared mount). If
qBittorrent runs in another container, mount the same volume at the same path,
or set a save path that both processes can see.

## Notes and limitations

- **No built-in catalog** — Prowlarr indexers are the source of new issues.
  Metadata enrichment (ISSN, Wikidata), Internet Archive, Gallica/BnF, and
  Calibre recipes are natural future integrations but are **not implemented**.
- **One weekday per weekly schedule** — the model supports a single publication
  day, not varying days per week.
- **SQLite and a lightweight migration helper** — `create_all` plus an
  idempotent `ALTER TABLE` for publication columns. There is no Alembic
  migration history.
- **qBittorrent is the only download client implementation.** The schema carries
  a protocol field, but a usenet client is not implemented.
- **No authentication on the web UI.** Put it behind a reverse proxy or trusted
  network.
- **Date matching is heuristic.** Release/file names without a recognizable date
  cannot be matched automatically.

## Roadmap

- ISSN / Wikidata metadata enrichment when adding publications.
- Internet Archive and Calibre-recipe source integrations.
- Direct Newznab/Torznab indexer support (not only via Prowlarr).
- Multiple publication days per week and holiday/exception dates.
- Proper database migrations.
- Post-processing hooks and notification integrations (Discord, ntfy, …).
- Authentication for the web UI.
