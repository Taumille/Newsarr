# Newsarr Architecture

This document describes how Newsarr is put together: the runtime topology, the
backend and frontend layers, the database model, the important request and
background flows, and where to extend it.

For installation and user-facing usage, see [README.md](README.md).

---

## 1. Purpose and scope

Newsarr is a single-user, self-hosted periodical manager. Its job is to:

1. store the publications a user follows and the expected dates of their issues,
2. query **Prowlarr** for releases,
3. send chosen releases to **qBittorrent**,
4. reconcile the download queue,
5. import completed files into a library, and
6. keep a dated **owned / missing** catalog in sync with what is on disk.

It deliberately does **not** implement indexer protocols, torrent transport,
metadata enrichment, or authentication. Those are delegated to Prowlarr,
qBittorrent, external metadata sources (future), and the surrounding
infrastructure (reverse proxy), respectively.

---

## 2. System context

```text
                         ┌─────────────────────────────────────────────┐
                         │              Newsarr process                │
                         │                                             │
  Browser ──────────────▶│ FastAPI ── REST ── React SPA (built assets) │
                         │    │                                        │
                         │    ├── API routers                        │
                         │    ├── service layer                      │
                         │    ├── in-process scheduler               │
                         │    └── SQLAlchemy ── SQLite               │
                         └──────┬───────────────────────┬──────────────┘
                                │ HTTP                  │ filesystem
                                ▼                       ▼
                         ┌────────────┐          ┌─────────────┐
                         │  Prowlarr  │          │   Library   │
                         │ (indexers) │          │  (imports)  │
                         └────────────┘          └─────────────┘
                                │
                                │ release URLs / magnets
                                ▼
                         ┌────────────┐
                         │ qBittorrent│
                         │  (client)  │
                         └──────┬─────┘
                                │ completed files
                                └──────────────▶ library path
```

There is no separate worker process, queue broker, or external database. The
scheduler runs inside the API process. Running multiple Newsarr instances
against the same database is not supported because each instance would run its
own scheduler.

---

## 3. Runtime model

### Process lifecycle

`backend/run.py` starts Uvicorn with `app.main:app`.

`app.main.lifespan`:

1. calls `init_db()` — creates missing tables and applies lightweight SQLite
   column migrations,
2. starts `_scheduler()` as an asyncio task,
3. logs the version and data directory,
4. on shutdown, cancels the scheduler task and awaits its termination.

### Scheduler

`_scheduler()` wakes every **5 seconds** and checks three independent timers:

| Timer | Trigger | Work |
|---|---|---|
| Queue | `NEWSARR_QUEUE_POLL_SECONDS` (default 20 s) | `sync_queue(db)` |
| RSS | `rss_sync_enabled` and `rss_sync_interval_minutes` (default 30 min, floor 60 s) | `run_rss_sync(db)` |
| Auto search | `auto_search_enabled` and `auto_search_interval_minutes` (default 360 min, floor 60 s) | `run_auto_search(db)` |

Each tick opens one `SessionLocal`, reads settings, runs whatever is due, and
closes the session. Exceptions are caught and logged so one failed tick cannot
kill the loop.

### Storage

- **Database:** SQLite at `<NEWSARR_DATA_DIR>/newsarr.db`.
- **Covers:** `<NEWSARR_DATA_DIR>/covers/<publication-id>.<ext>`.
- **Default library root:** `<NEWSARR_DATA_DIR>/library` unless overridden in
  settings.
- **SQLite settings:** `check_same_thread=False`, `expire_on_commit=False`.
  There is no connection pool tuning; this is a small, single-process app.

### Production UI

If `NEWSARR_FRONTEND_DIR` (default `frontend/dist`) exists, the API mounts
`/assets` and registers a catch-all `GET /{full_path:path}` that serves files or
falls back to `index.html` for client-side routing. Paths beginning with `api/`
are excluded and return JSON 404. During development, Vite serves the UI and
proxies `/api` to port 7878.

---

## 4. Repository layout

```text
.
├── Makefile                     # setup / backend / frontend / build / test
├── README.md                    # user guide
├── ARCHITECTURE.md              # this document
├── backend/
│   ├── run.py                   # Uvicorn launcher
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, scheduler, SPA fallback
│   │   ├── config.py            # bootstrap settings from NEWSARR_* env vars
│   │   ├── database.py          # engine, session factory, init + migrations
│   │   ├── models.py            # SQLAlchemy models and enums
│   │   ├── schemas.py           # Pydantic request/response models
│   │   ├── api/
│   │   │   ├── system.py
│   │   │   ├── publications.py
│   │   │   ├── issues.py
│   │   │   ├── search.py
│   │   │   ├── queue.py
│   │   │   ├── settings.py
│   │   │   └── tasks.py
│   │   └── services/
│   │       ├── clients.py       # build Prowlarr/qBittorrent clients from settings
│   │       ├── prowlarr.py      # aggregate search client
│   │       ├── qbittorrent.py   # Web API v2 client
│   │       ├── torrent.py       # bencode + info-hash helpers
│   │       ├── grab.py          # add a release to qBittorrent + create record
│   │       ├── sync.py          # reconcile queue, trigger imports
│   │       ├── library.py       # choose file, move, name, mark issue owned
│   │       ├── issues.py        # schedule, status, scan, gap search
│   │       ├── autosearch.py    # RSS sync + catch-up search
│   │       ├── search.py        # query/category helpers
│   │       ├── naming.py        # slugify/sanitize/naming template
│   │       └── settings.py      # typed access to the settings table
│   └── tests/                   # mock-backed integration and unit tests
├── frontend/
│   ├── src/
│   │   ├── api.ts               # typed fetch wrapper, one object per resource
│   │   ├── types.ts             # shared TypeScript interfaces
│   │   ├── App.tsx              # routes + sidebar + status polling
│   │   ├── pages/               # Library, Add, Detail, Queue, Settings
│   │   ├── components/          # PublicationForm, CoverPanel, IssueLibrary
│   │   ├── format.ts            # byte/date formatting
│   │   └── styles.css           # dark theme
│   └── vite.config.ts           # port 5173, /api proxy → 7878
└── tools/
    ├── npm                      # wrapper for the broken system npm
    └── npm.js
```

---

## 5. Backend architecture

### Layering

```text
HTTP request
    │
    ▼
api/*.py (routers)         validation, HTTP status codes, response models
    │
    ▼
services/*.py              domain logic, external clients, filesystem
    │
    ▼
models.py / database.py    SQLAlchemy models and sessions
```

Pydantic schemas in `schemas.py` are the public contract. Routers use
`response_model` extensively; ORM objects are returned directly where
`from_attributes=True` is configured, or converted with `model_validate` when
extra fields (for example issue counts) must be added.

### API routers

| Router | Prefix | Responsibility |
|---|---|---|
| `system` | `/api/v1/system` | Version, counts, configured flags. |
| `publications` | `/api/v1/publications` | CRUD, covers, general search, per-publication auto-search. |
| `issues` | `/api/v1` | Issue list/generate/scan/search/grab; also `/issues/{id}`. |
| `search` | `/api/v1/search` | Ad-hoc Prowlarr query. |
| `queue` | `/api/v1/queue` | List/grab/delete/retry/sync/diagnostics. |
| `settings` | `/api/v1/settings` | Read/update settings, connection tests, indexer list. |
| `tasks` | `/api/v1/tasks` | Manual RSS/auto-search triggers. |

A bare `/api/v1/health` endpoint is registered in `main.py`.

### Service responsibilities

- **`prowlarr`** wraps Prowlarr's aggregate `/api/v1/search` endpoint and maps
  each result into the internal `Release` schema. It does not talk to indexers
  directly.
- **`qbittorrent`** logs in, adds magnets or `.torrent` files, lists torrents,
  deletes them, and computes an info hash when possible. It also contains the
  qBittorrent-specific error messages for 401/403 and CSRF/Host-header problems.
- **`torrent`** contains a minimal bencode decoder/encoder and SHA-1 info-hash
  calculation. This is what makes queue matching reliable instead of name-based.
- **`grab`** is the single grab path used by all search modes. It calls the
  download client, writes a `DownloadRecord`, and links the record to an
  `Issue` when one is known.
- **`sync`** reconciles active `DownloadRecord`s with qBittorrent, updates
  progress/state, and hands completed records to the importer.
- **`library`** chooses the file to import, moves it into the library, applies
  the naming template, and marks the matching issue owned.
- **`issues`** owns the schedule algorithm, date parsing, status summaries,
  folder scanning, per-issue search, and bulk gap search.
- **`autosearch`** contains the RSS and catch-up policies: relevance, de-dup,
  cutoff, preferred format, grab cap, and orchestration across publications.
- **`settings`** reads and writes the key/value settings table, hides secrets
  from API responses, and exposes typed `as_bool`/`as_int` helpers.
- **`clients`** constructs Prowlarr and qBittorrent clients from a settings map.
- **`naming`** provides slug generation, filename sanitization, and template
  expansion.

---

## 6. Frontend architecture

The frontend is a small React SPA with local component state; there is no
Redux/Zustand/Query cache.

- **`api.ts`** centralizes all `fetch` calls under `/api/v1`, JSON-encodes
  request bodies, handles multipart cover uploads, converts non-2xx responses
  into `Error(detail)`, and returns typed data.
- **`types.ts`** mirrors the backend Pydantic schemas.
- **`App.tsx`** defines the five routes (`/`, `/add`, `/publications/:id`,
  `/queue`, `/settings`), the sidebar, and a 15-second `/system/status` poll.
- **`pages/Publications.tsx`** renders the library grid with cover, counts, and
  monitored/format metadata.
- **`pages/PublicationDetail.tsx`** loads the publication, renders the cover
  panel, edit form, and `IssueLibrary`; it bumps a refresh key when the schedule
  is saved so the issue list reloads.
- **`components/PublicationForm.tsx`** contains the create/edit fields and the
  frequency/weekday/start-date controls.
- **`components/CoverPanel.tsx`** uploads/removes a cover and chooses between the
  uploaded image and `cover_url`.
- **`components/IssueLibrary.tsx`** owns issue filtering, status actions,
  per-issue search results, and bulk missing search.
- **`pages/Queue.tsx`** polls the queue every 10 seconds and exposes sync,
  retry, remove, and diagnostics actions.
- **`pages/Settings.tsx`** edits integrations/automation and runs connection
  tests.

The Vite dev server runs on port 5173 and proxies `/api` to `localhost:7878`;
production uses the static assets served by FastAPI.

---

## 7. Data model

### Entity relationships

```text
Publication 1 ──── * DownloadRecord
Publication 1 ──── * Issue
Issue       * ──── 0..1 DownloadRecord   (Issue.download_id)
```

There is no inverse `Issue` relationship on `DownloadRecord`; queue sync finds a
linked issue with `Issue.download_id == record.id`.

### `Publication` (`publications`)

| Field | Notes |
|---|---|
| `id`, `title`, `slug` | Display identity; slug is derived with `slugify()`. |
| `monitored` | Only monitored publications are auto-searched. |
| `keywords`, `categories` | Search hints. Categories are comma-separated Newznab IDs. |
| `language`, `country` | Metadata only; not used as search filters server-side. |
| `preferred_format` | `any`/`pdf`/`epub`/`mobi`/…; biases file choice and bulk gap selection. |
| `folder` | Optional subfolder under `library_root`; defaults to the slug. |
| `cover_url`, `cover_path` | External URL and uploaded file name (not an absolute path). |
| `frequency` | `irregular`, `daily`, `weekly`, `biweekly`, `monthly`, `quarterly`. |
| `weekday` | Monday=0 … Sunday=6 for weekly/biweekly; nullable. |
| `start_date` | First date considered by the calendar generator; nullable. |
| `created_at`, `updated_at`, `last_search_at` | UTC timestamps. |

`has_cover` is a Python property, not a column, and is exposed through the
response schema.

### `Issue` (`issues`)

| Field | Notes |
|---|---|
| `id`, `publication_id` | Cascades on publication deletion. |
| `issue_date` | Date only. Unique per publication (`uq_issue_pub_date`). Indexed. |
| `label` | Optional free-form edition/number label. |
| `status` | `expected`, `grabbed`, `owned`, `ignored`. |
| `download_id` | Optional FK to the download record associated with this issue (grab or import). |
| `file_path` | Where the owned file lives, when known. |
| `notes` | Free text. |
| `created_at`, `updated_at` | UTC timestamps. |

**Important:** `missing` and `upcoming` are not stored statuses. They are
computed from `status == expected` and the relationship of `issue_date` to
`date.today()`.

### `DownloadRecord` (`downloads`)

Tracks a release from grab through import:

| Group | Fields |
|---|---|
| Identity | `title`, `guid`, `indexer`, `indexer_id`, `protocol`, `size`, `info_url`, `publish_date` |
| Source URLs | `download_url`, `magnet_url` |
| Client state | `client`, `client_hash`, `save_path`, `content_path` |
| Progress | `status`, `progress` (0–100), `error_message` |
| Result | `imported_path`, `completed_at` |
| Audit | `added_at`, `updated_at`, optional `publication_id` |

`status` is `queued`, `downloading`, `completed`, `imported`, or `failed`.

### `AppSetting` (`settings`)

A key/value store (`key` primary key, `value` text). Defaults are defined by
`SettingsModel` in `schemas.py`; rows only exist for values the user has changed.

### Migrations

There is no Alembic history. `init_db()`:

1. imports `models` so mappings are registered,
2. runs `Base.metadata.create_all()` to create missing tables,
3. runs `_migrate_publications()`, which uses `PRAGMA table_info` and
   idempotent `ALTER TABLE ... ADD COLUMN` statements for columns added after the
   first release (`frequency`, `weekday`, `start_date`, `cover_path`).

Adding a new **column** to an existing table therefore requires extending this
helper (or introducing Alembic). New tables are handled by `create_all`.

---

## 8. Domain lifecycles

### Issue lifecycle

```text
                 generate calendar
                         │
                         ▼
                     expected ◀─────────────────────────────┐
                      │     │                                │
          grab issue  │     │ file found / manual mark       │ download fails
                      ▼     ▼                                │
                   grabbed  owned                             │
                      │                                      │
                      └──────────── import ──────────────────┘

  expected ── ignore ──▶ ignored ── unignore ──▶ expected
```

Rules enforced by the API/service:

- Grabbing sets `grabbed`, stores `download_id`, and clears `file_path`.
- Successful import or folder scan sets `owned` and stores `file_path`.
- Manually setting `expected` clears `download_id` and `file_path`.
- Manually setting `ignored` clears `download_id`.
- A failed qBittorrent state resets a linked `grabbed` issue to `expected` so it
  can be searched again.
- Regenerating the calendar deletes only stale `expected` issues with no
  `download_id`; owned, grabbed, and ignored issues are preserved.

### Download lifecycle

```text
grab ──▶ queued ──▶ downloading ──▶ completed ──▶ imported
                         │                │
                         └── failed ◀─────┘ (import error)
```

Queue sync updates `queued`/`downloading` records, marks completion when
qBittorrent reports a completed state or progress reaches 100, and then imports
every completed record.

---

## 9. Key flows

### 9.1 Publication creation and calendar generation

`POST /api/v1/publications`:

1. rejects a duplicate title (case-insensitive) with `409`,
2. creates the `Publication` and derives its slug,
3. commits, then calls `_refresh_calendar()`,
4. if `start_date` is set and `frequency != irregular`, calls
   `sync_calendar()`,
5. returns the publication with issue counts filled by `summary_for()`.

`PUT /api/v1/publications/{id}` tracks whether `frequency`, `weekday`, or
`start_date` was present in the payload. `start_date` and `weekday` may be
explicitly set to `null`; other fields with `null` are ignored. If the schedule
changed, the calendar is regenerated.

### 9.2 Calendar generation

`generate_issue_dates(frequency, weekday, start, end)` returns dates oldest
first, inclusive of both bounds, capped at `MAX_GENERATED = 6000`:

| Frequency | Algorithm |
|---|---|
| `daily` | Every calendar day from `start`. |
| `weekly` | First occurrence of `weekday` on/after `start`, then every 7 days. |
| `biweekly` | Same alignment, then every 14 days. |
| `monthly` | Same day-of-month as `start`, stepping one month; clamps to the last day of short months. |
| `quarterly` | Same as monthly, stepping three months. |
| `irregular` | No dates. |

If `weekday` is null or out of range, the start date's weekday is used.
`sync_calendar()` then:

- inserts missing issues as `expected`,
- prunes stale `expected` issues that are no longer in the schedule and have no
  linked download,
- commits and returns `{added, removed, total}`.

The default end date is `date.today()`, so the catalog covers the past up to
today, not future dates. Auto-search calls `sync_calendar()` before searching,
which keeps the catalog rolling forward.

### 9.3 Search and grab

General per-publication search:

1. `build_query()` joins title, keywords, and optional extra text.
2. `parse_categories()` converts comma/semicolon-separated numeric IDs.
3. `ProwlarrClient.search()` calls `/api/v1/search` with `query`, `type=search`,
   `limit=100`, and optional `categories`.
4. Results are mapped to `Release` objects and sorted newest first.
5. `publication.last_search_at` is updated.

Grab (`POST /queue` or `POST /issues/{id}/grab`):

1. build the qBittorrent client from stored settings,
2. add the magnet or download the `.torrent` and add that,
3. compute the info hash from the magnet `btih` or torrent metadata,
4. create a `queued` `DownloadRecord` with URLs, indexer, size, publish date,
   hash, save path, and client name,
5. link an issue:
   - explicit `issue_id` if provided and it belongs to the publication,
   - otherwise the issue on `release.publish_date.date()` if one exists,
6. set the issue to `grabbed` and store `download_id`,
7. commit and return the record.

The general `/queue` path does not pass an explicit issue ID, so it relies on the
publish-date match. Per-issue grab passes the issue ID and is exact.

### 9.4 Queue reconciliation and import

`sync_queue(db)`:

1. loads records with status `queued` or `downloading`; returns early if none,
2. fetches the **full** qBittorrent torrent list (not a hash-filtered list),
3. builds lookup maps by lower-case hash and normalized name,
4. for each record, tries in order:
   - stored `client_hash`,
   - hash recovered from the stored magnet,
   - normalized torrent name,
   - for legacy rows with no valid 40-hex hash: recompute from magnet or by
     downloading the `.torrent`, store it, and retry the hash lookup,
5. updates `client_hash`, `progress`, `save_path`, `content_path`, and status,
6. on a failed state, marks the record failed and resets a linked `grabbed`
   issue to `expected`,
7. commits,
8. imports every `completed` record.

Import (`import_download`):

1. resolve the source root from `content_path`, then `save_path`, then fall back
   to the save directory if the first path yielded no files,
2. pick a file: document extensions first (or all files if none match), prefer
   the publication's `preferred_format`, otherwise the largest file,
3. compute the target directory: `<library_root>/<folder or slug>`,
4. compute the date string from `publish_date`, else `completed_at`, else now,
5. apply `naming_template` (`{title}`, `{date}`), sanitize it, and add `(1)`,
   `(2)`, … if the target exists,
6. move the file, falling back to copy+unlink for cross-device moves,
7. set `imported_path`, status `imported`, progress 100, `completed_at`,
8. determine the issue date from `publish_date`, else the final filename, else
   the import date string,
9. call `record_owned()`, which creates the issue if it is not in the calendar
   and sets status `owned` + `file_path` + `download_id`.

Import failures set the record to `failed` with a user-visible error message.

### 9.5 Automatic RSS and catch-up search

`run_rss_sync()` and `run_auto_search()` both call `run_for_all()` with different
windows:

- RSS: `recent_hours=72`, max grabs from settings.
- Auto: `recent_days=30`, max grabs from settings.

For each monitored publication, `process_publication()`:

1. returns immediately if not monitored,
2. syncs the issue calendar,
3. performs one Prowlarr search,
4. computes a **cutoff**:
   - newest `DownloadRecord.publish_date` for that publication, if any,
   - otherwise `now - recent_hours/days`.
5. selects candidate releases (`select_new_releases`):
   - relevance: at least one publication title token of length ≥ 4 appears in
     the normalized release title (if the publication title has no such token,
     everything is relevant),
   - de-duplicate against known GUIDs and normalized titles,
   - require `publish_date >= cutoff` when a publish date exists,
   - de-duplicate within the batch,
   - if a preferred format is set, keep only titles containing it when at least
     one such release exists,
   - sort oldest first and cap at `max_grabs`.
6. grabs each candidate. On `GrabError`, logs and stops this publication's run
   (a client failure is likely to affect every subsequent grab).
7. updates `last_search_at`.

This is intentionally conservative: automatic search consumes new issues but
does not try to fill a historical backlog. Historical gaps are handled by the
explicit bulk missing search.

### 9.6 Per-issue and bulk missing search

Per-issue (`search_for_issue`):

1. builds date-qualified queries using `YYYY-MM-DD`, `YYYYMMDD`, and
   `DD-MM-YYYY`, with title + keywords,
2. if any query returns a date-matched release, returns those,
3. otherwise performs the plain title/keyword query and filters by date.

Date matching (`release_issue_date`) prefers a date parsed from the release
title, because Prowlarr's `publishDate` may be an upload date. It falls back to
the publish date. `release_matches_issue()` allows ±1 day.

Bulk (`search_missing`):

1. loads missing issues (`expected` with `issue_date <= today`), newest first,
2. performs one Prowlarr search for the publication,
3. for each missing issue, filters releases matching that date,
4. excludes releases already used in this run,
5. picks the best candidate by `(preferred-format hit, seeders, publish date)`,
6. grabs with the explicit issue ID,
7. stops after `max_grabs` successful grabs or 3 grab failures.

The UI requests a maximum of 10; the API accepts 1–100.

### 9.7 Library scan

`scan_library(publication)`:

1. resolves `<library_root>/<folder or slug>`; returns zeros if it does not
   exist,
2. recursively lists files with allowed document/archive extensions,
3. extracts a date from each **file name**,
4. skips files without a parseable date,
5. finds or creates the matching issue, sets it `owned`, stores `file_path`, and
   clears `download_id`,
6. commits and returns `{scanned, matched, owned}`.

There is no mtime fallback: an undated filename cannot be matched reliably.

Supported filename date forms:

- `YYYY-MM-DD`, `YYYY_MM_DD`, `YYYY.MM.DD`
- `DD-MM-YYYY`, `DD_MM_YYYY`, `DD.MM.YYYY`
- `YYYYMMDD`
- `8 January 2020`, `8 janvier 2020`
- English and French month names (accent-tolerant set defined in `issues.py`)

### 9.8 Cover upload

`POST /publications/{id}/cover`:

1. checks the extension against JPEG/PNG/WebP/GIF,
2. reads the upload and rejects empty or > 10 MB files,
3. removes any existing `<id>.*` cover files,
4. writes `covers/<id><ext>`,
5. stores the file name in `publication.cover_path`,
6. returns the publication with `has_cover=true`.

The upload is extension-validated, not decoded. `GET` serves the file with the
matching media type and a one-hour cache header. Deleting a publication or its
cover removes the files; deletion is best-effort.

---

## 10. Configuration and secrets

Two layers:

1. **Bootstrap settings** (`config.py`) from `NEWSARR_*` environment variables:
   data dir, host, port, frontend dir, queue poll interval.
2. **User settings** in the SQLite `settings` table: integrations, library root,
   naming template, automation windows.

`services/settings.py`:

- merges stored rows over `SettingsModel` defaults,
- returns a sanitized model to the API: `prowlarr_api_key` and
  `qbittorrent_password` are replaced with `""`, and `*_set` booleans indicate
  that a secret exists,
- returns the raw map only to internal services,
- treats a blank secret in an update as "leave the stored value unchanged",
- exposes `get_all`, `get_map`, `update`, `library_root`, `as_bool`, `as_int`.

Secrets are never logged by configuration code and never returned to the
browser.

---

## 11. Error handling

| Situation | Behaviour |
|---|---|
| Publication/issue/download not found | `404` |
| Duplicate publication title | `409` |
| Invalid cover type / empty file | `400` |
| Cover > 10 MB | `413` |
| Generate calendar without start date | `400` |
| Prowlarr unreachable or returns ≥ 400 | `502` with upstream detail |
| qBittorrent add/login failure | `502` via `GrabError` |
| Queue sync qBittorrent failure | Logged; sync skipped, records remain unchanged |
| Import error | Record marked `failed`, error message stored |
| Scheduler exception | Logged; loop continues next tick |
| Search failure for one publication | Logged; other publications continue |

The frontend `api.ts` converts non-2xx responses into `Error(detail)`, which the
pages display in alert boxes.

---

## 12. Concurrency and async model

- FastAPI endpoints are mostly `async def`; they await HTTP clients.
- SQLAlchemy is synchronous. Database calls inside async handlers block the event
  loop, which is acceptable for this single-user, low-throughput app.
- Each request gets its own session from `get_db`; the scheduler opens one
  session per tick; one-shot task entry points open and close their own sessions.
- SQLite serializes writes. There is no explicit retry/backoff for
  `database is locked`.
- The scheduler is in-process and uses `time.monotonic()` deadlines. There is no
  distributed lock, so do not run multiple app instances against one database.
- `expire_on_commit=False` lets response serialization access ORM attributes
  after commit without extra queries.

---

## 13. Security model

Current assumptions:

- **No authentication or authorization.** The UI and API are intended for a
  trusted network or behind a reverse proxy that enforces auth.
- **No CSRF protection on Newsarr's own API.** The app is same-origin in
  production; the only cross-origin allowance is the Vite dev server.
- CORS in `main.py` allows `http://localhost:5173` and
  `http://127.0.0.1:5173` with credentials and any method/header for development.
- Prowlarr and qBittorrent credentials are stored in plaintext in the local
  SQLite database. Protect the data directory and database file accordingly.
- Cover uploads are extension-checked and size-limited but not decoded or
  re-encoded.
- Imported paths come from qBittorrent metadata; the app trusts the configured
  client and library paths.
- File names are sanitized for filesystem-reserved characters. The
  per-publication `folder` is normally a relative subfolder under the library
  root, but the current code does not explicitly reject absolute paths or `..`
  components in that field. Treat Settings and publication editing as
  admin-only operations.

---

## 14. Testing strategy

`make test` runs the Python suites sequentially, each against a temporary data
directory:

| Test | What it verifies |
|---|---|
| `e2e_smoke.py` | Mock Prowlarr + qBittorrent; full search → grab → sync → import; info hash; library naming/placement; SPA serving; legacy hash self-healing. |
| `qbit_error_paths.py` | 403 ban message, 401 CSRF/Host message, bad credentials. |
| `torrent_hash.py` | Bencode decoding, magnet `btih` extraction, info-hash computation. |
| `background_loop.py` | Background queue poll updates progress without a manual sync (poll forced to 1 s). |
| `autosearch.py` | Relevance, de-duplication, cutoff, preferred format, grab cap. |
| `issues.py` | Schedule dates (weekly/monthly), date parsing (including French), scan, cover upload/delete, status transitions, cascade deletion. |

Tests set `NEWSARR_DATA_DIR` **before** importing `app.main`, because config and
the engine are initialized at import time.

Frontend verification is separate:

```bash
cd frontend
npm run typecheck
npm run build
```

---

## 15. Extension points

### Add publication metadata

1. Add columns in `models.py` and fields in `PublicationBase` /
   `PublicationUpdate` / `Publication` in `schemas.py`.
2. Extend `_migrate_publications()` in `database.py` for existing databases.
3. Add form controls in `PublicationForm.tsx` and types in `types.ts`.
4. Include the fields in the detail page's `initial` object.

### Replace or add a download client

`services/clients.py` is the construction point. A client needs at least:

- `test() -> dict`
- `add(release, save_path, category) -> str` (return an info hash if possible)
- `torrents() -> list[dict]`
- `delete(info_hash, delete_files) -> None`

Queue sync assumes qBittorrent-shaped fields (`hash`, `name`, `progress`,
`state`, `save_path`, `content_path`). A different client would need an adapter
or changes in `sync.py`. Add a client selector to settings if supporting more
than one.

### Add another indexer/search source

Implement a service that returns `list[Release]` and uses `grab_release()` for
acquisition. Keep `Release` as the boundary type so the queue/import layer does
not care where a release came from. `build_query`/`parse_categories` are
Prowlarr-oriented helpers; a new source can build its own query.

### Add historical/archive sources

The bulk missing search is the natural integration point: it already iterates
dated gaps. A new source can contribute candidate releases for an issue date,
then reuse `grab_release(..., issue_id=...)`. Metadata-only sources (ISSN,
Wikidata) belong in publication creation/edit, not the acquisition path.

### Introduce authentication

Add middleware/dependencies in `main.py` or a shared router dependency. The SPA
fallback and `/api/v1/*` routes need separate treatment if unauthenticated
users should not even load the UI. The current CORS setup should be tightened at
the same time.

### Replace SQLite or add migrations

`database.py` is isolated enough to swap the engine URL. For schema evolution,
introduce Alembic and replace `_migrate_publications()` with real revisions.
The current helper only handles additive publication columns.

### Add richer schedules

`generate_issue_dates()` is the single source of truth for expected dates. To
support multiple weekdays, holiday exceptions, or “daily except Sunday”, extend
the `Publication` schedule representation and this function; `sync_calendar()`
and the UI are the other touch points.

---

## 16. Known constraints and trade-offs

- **Single user / single process.** No auth, no tenancy, no distributed
  scheduler.
- **SQLite only in practice.** No migration framework; additive column helper.
- **qBittorrent only.** The schema includes a protocol enum but no usenet
  download client.
- **One publication day per weekly cadence.**
- **No future issue generation.** The calendar ends at today; upcoming issues
  are only those already generated in the current run.
- **Heuristic date matching.** Release and filename parsing can miss unusual
  formats; the UI provides manual status overrides.
- **No content validation for covers.** Extension and size checks only.
- **Blocking DB calls in async handlers.** Fine at this scale; a larger
  deployment would move to async SQLAlchemy or thread offload.
- **External search limits.** Prowlarr returns at most the configured limit
  (100 by default); very old backlog searches may need narrower date queries.
- **No built-in catalog.** The app ships with no newspaper metadata; titles and
  schedules are user-entered.
