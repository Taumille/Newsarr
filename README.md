# Newsarr

**Newsarr** is a self-hosted newspaper & magazine collection manager — think
*Radarr/Sonarr, but for print*. You track the publications you care about, and
Newsarr searches your **Prowlarr** instance for new issues, grabs them into
**qBittorrent**, and files the finished PDFs/EPUBs into a tidy library.

It borrows the *patterns* of the Servarr family (publications ≈ movies/series,
a provider-agnostic indexer layer, a download-client layer, a queue, and a
library importer) but is a small, readable standalone codebase.

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

## Features (v0.1)

- **Track publications** — title, keywords, Newznab categories, language,
  country, preferred format, monitored flag, per-publication library folder.
- **Search Prowlarr** — aggregate search across every indexer in your Prowlarr
  instance, right from a publication's page.
- **Grab releases** into qBittorrent (magnet links and `.torrent` URLs both work).
- **Queue & history** — live progress, retry, remove, and status per grab.
- **Automatic import** — completed downloads are moved into the library with a
  configurable naming scheme (e.g. `The Guardian - 2026-10-21.pdf`).
- **Web UI** — library grid, add/edit forms, search results, queue, settings.
- **Runtime configuration** — Prowlarr and qBittorrent credentials live in the
  database and are edited in the UI; secrets are never returned to the browser.

## Tech stack

| Layer     | Choice                                            |
|-----------|---------------------------------------------------|
| Backend   | Python 3.12+ / FastAPI / SQLAlchemy 2 / SQLite    |
| Frontend  | React 19 + TypeScript + Vite (react-router)       |
| HTTP      | httpx                                             |
| Storage   | SQLite at `~/.config/newsarr/newsarr.db`          |

## Quick start

### 1. Backend

```bash
cd newsarr/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py          # http://localhost:7878
```

### 2. Frontend (development)

```bash
cd newsarr/frontend
npm install
npm run dev                      # http://localhost:5173  (proxies /api to :7878)
```

Open <http://localhost:5173>, go to **Settings**, and enter:

- **Prowlarr URL** — e.g. `http://prowlarr:9696` (may be a remote host) and its
  **API key** (Prowlarr → Settings → General).
- **qBittorrent URL** — e.g. `http://qbittorrent:8080` plus username/password.

Both sections have a **Test connection** button.

### 3. Production (single process)

```bash
cd newsarr/frontend && npm run build     # emits frontend/dist
cd ../backend && .venv/bin/python run.py # API serves the built UI at :7878
```

### Using the app

1. **Add publication** → e.g. "The Guardian", keywords `pdf`, categories `7010`.
2. Open it and click **🔍 Search for releases**.
3. Pick a result and **Grab** it. It lands in the **Queue**.
4. Newsarr polls qBittorrent in the background; when the download finishes it is
   imported into your library root and the queue row becomes *imported*.

## Configuration reference

| Setting | Meaning |
|---|---|
| `NEWSARR_DATA_DIR` | Where the DB and default library live (default `~/.config/newsarr`). |
| `NEWSARR_PORT` | API port (default `7878`). |
| `NEWSARR_FRONTEND_DIR` | Location of the built UI (default `frontend/dist`). |
| `NEWSARR_QUEUE_POLL_SECONDS` | Background queue poll interval (default `20`). |

User-facing Prowlarr / qBittorrent / library settings are stored in the DB and
edited from the **Settings** page — nothing is hard-coded and no secrets are
committed.

## API

All endpoints are under `/api/v1` (interactive docs at `/docs`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/system/status` | Version, counts, configuration status. |
| GET/POST | `/publications` | List / create publications. |
| GET/PUT/DELETE | `/publications/{id}` | Read / update / remove. |
| POST | `/publications/{id}/search` | Search Prowlarr for that publication. |
| GET | `/search?query=` | Ad-hoc Prowlarr search. |
| GET/POST | `/queue` | List the queue / grab a release. |
| GET/DELETE | `/queue/{id}` | Inspect / remove a download. |
| POST | `/queue/{id}/retry` | Re-check a failed download. |
| POST | `/queue/sync` | Force a queue/client reconcile. |
| GET/PUT | `/settings` | Read / update configuration. |
| POST | `/settings/test/{prowlarr,qbittorrent}` | Connection tests. |

## Tests

```bash
cd newsarr/backend
PYTHONPATH=. .venv/bin/python tests/e2e_smoke.py
```

The smoke test stands up mock Prowlarr + qBittorrent servers and exercises the
full `search → grab → sync → import` pipeline. `qbit_error_paths.py` checks that
login failures produce accurate messages, and `torrent_hash.py` checks the
info-hash maths against independently computed SHA-1 values.

## Troubleshooting

### A download stays at 0% in the Queue

Newsarr identifies a grabbed download by its BitTorrent **info hash**, computed
directly from the `.torrent` file (or the `btih` in a magnet link). If a record
was grabbed by an older build that guessed the hash by torrent *name*, its
`client_hash` may be wrong or empty. The queue sync now fetches the full torrent
list, recovers hashes from stored magnets, and matches by name as a fallback.

If a single old row still sits at 0%, use **Queue → Refresh now**; if it doesn't
clear, remove it and grab the release again — new grabs always store the correct
hash.

## Troubleshooting

### qBittorrent test fails with 403 / 401

qBittorrent requires authentication on **every** API endpoint except
`/api/v2/auth/login`, and when its CSRF protection is on (the default) it also
checks the `Origin`/`Referer` header against the request's `Host`. Newsarr logs
in first and sends a matching `Referer`, so a 403/401 now points at a real cause:

- **"Your IP is most likely temporarily banned"** — too many failed logins. Wait
  a few minutes and re-check the username/password.
- **"401 ... CSRF / Host-header protection"** — the URL host doesn't match how you
  reach qBittorrent. Use the same host/IP you type in the browser, or in
  qBittorrent's **Options → WebUI** turn off *Host header validation* and
  *CSRF protection* (or add your host to the validation whitelist).
- **"Incorrect qBittorrent username or password"** — credentials are wrong.

If Newsarr and qBittorrent run on the same host, enabling *Bypass authentication
for clients on localhost* in qBittorrent is the simplest fix.

## Notes

- **Naming template tokens:** `{title}` (publication name) and `{date}`
  (release/publish date). Files are placed under
  `<library_root>/<publication folder or slug>/`.
- **Library root** must be reachable by the Newsarr process. If qBittorrent runs
  elsewhere, point the qBittorrent **save path** and this root at the same
  storage (or a shared mount).

### Roadmap

- RSS / scheduled auto-search for monitored publications.
- Newznab/Torznab indexers added directly (not only via Prowlarr).
- Post-processing hooks and notification integrations (Discord, ntfy…).
- Authentication for the web UI.

### Broken system npm on this machine

`npm install` here fails with *"Class extends value undefined is not a constructor
or null"* because the system npm ships a stale nested `minipass@3` (see
`tools/npm.js` for the full explanation). If your npm is healthy, ignore this.
Otherwise use the bundled wrapper instead of `npm`:

```bash
cd newsarr/frontend
node ../tools/npm.js install
node ../tools/npm.js run build
# or: ../tools/npm install
```
