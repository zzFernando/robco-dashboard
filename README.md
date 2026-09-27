# ROBCO Operations Terminal

A lightweight ROBCO-inspired display for a first-generation iPad in landscape.
Flask and psutil run on the host computer; the iPad only renders cached telemetry.
No frontend packages, bundler, external fonts, or build step.

## Run

Python 3.10+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

On macOS/Linux, use `.venv/bin/python` instead.
Open http://localhost:8080 or http://HOST_LAN_IP:8080 from the iPad on the same LAN.
The Flask development server binds to all interfaces; this unauthenticated personal
terminal is intended for a trusted LAN only.

## iPad setup

1. Open the URL in Safari, choose Share > Add to Home Screen, then open that icon.
   The included Apple web-app meta tags enable standalone display on old iOS.
2. For continuous use on original iPad/iOS 5, set Settings > General > Auto-Lock >
   Never (Ajustes > Geral > Bloqueio Automático > Nunca).
3. Keep the iPad powered during continuous use.

The dashboard is intentionally border-to-border: it has no application header or
top action bar. The device's own Safari status bar may still be visible unless the
page is opened from the Home Screen.

## Screens and display

- The single view contains Weather, System, Now Playing, Codex, Claude and Pomodoro cards.
- The cards fill the viewport and use an ES5/WebKit-compatible layout for old iPads.
- The System card shows CPU, memory and disk as visual bars.
- Weather uses the host/device location, server-side weather lookup and a local JPEG
  city photo. If device GPS is unavailable, the location falls back to an approximate IP location.
- One XMLHttpRequest polls telemetry every three seconds. Previous readings remain
  visible during temporary failures.
- No frontend packages, bundler or external fonts are required.

## Backend organization

`app.py` serves the existing HTML/static routes and `GET /api/status`.
`services/state.py` starts one daemon sampler on the first API request, samples
every approximately three seconds, and shares a locked snapshot across requests.
CPU sampling stays on that thread. Collector failures retain that collector's
prior data and add its name to `errors`; the UI shows DATA [PARTIAL].

`collectors/` independently inspects processes, the dashboard repository and host
metrics. `services/events.py` records online/offline and Git status/commit
transitions in a bounded deque, rather than repeating events each poll. Git's
initial sample establishes a baseline. The worktree signature uses porcelain
status (paths and statuses), not file contents, so editing an already modified
file without changing its Git status does not create another event.

The API includes timestamp, agents, system, git, events and collector errors.
Private process samples and Git fingerprints are never serialized.
Event history is memory-only and resets on restart. Run one application process
for one coherent event history; each additional WSGI worker would have its own.

## What agent data means

Exact executable names and known Node/Bun CLI script paths identify Codex/Claude
processes. Arbitrary command-line mentions do not count.

- `online`: one or more matching processes are visible.
- `status`: OFFLINE without a detected process; otherwise UNKNOWN unless a recent
  session event (within 120 seconds) and matching process directory support
  WORKING, IDLE or WAITING. This is directory correlation, not exact PID/session binding.
- `started_at`, `session_seconds`: oldest readable matching process start/lifetime,
  not a confirmed conversation session. Process count is included.
- `working_directory`, `project`: shared readable process cwd and its basename.
  Null when missing or ambiguous; cwd is not proof of the active repository.
- `last_seen`: most recent successful sample with a matching process.
- `last_activity`: last observed CPU-time increase for a matching PID/start-time
  pair. Null until a delta is observed. This is process activity, not a tool action.
- `action`: null. File edits, command arguments and test results are not exposed.

## Local session usage

`collectors/usage.py` incrementally reads Codex `sessions/**/*.jsonl` and Claude
`projects/**/*.jsonl`. It discovers the default user homes, `CODEX_HOME` and
`CLAUDE_CONFIG_DIR` overrides, and home overrides from detected processes.
This includes Orca-managed Codex homes without hardcoding an Orca installation path.
The host server must have read access to those directories. No credentials,
agent settings or conversations are modified.

Each agent's `usage` contains the selected session ID/model/project, session token
categories, daily token categories and session count, freshness, context, recorded
rate limits/reset times, and source scope. `MATCHED DIRECTORY` prefers the newest
log with a detected process cwd; otherwise `LATEST LOG` is historical context,
not evidence that this process owns that session. WORK counts only recent working
logs matched to visible process directories, not all active sessions on an account.

- Codex cumulative snapshots replace earlier totals; repeated `token_count` and
  `token_usage_record` snapshots are not summed. Lower delayed snapshots are
  ignored and flagged partial. Daily totals use cumulative deltas by host-local date.
- Claude usage is deduplicated by API message ID, including copied responses across
  logs for daily totals. Input is normalized to include cache reads and writes;
  Codex already includes cache in input. Cache is a subset, never added twice.
- TODAY covers discovered local logs only, not billing or usage on other machines.
  Claude logs without usage yield UNKNOWN, not zero. A complete historical scan
  with no records for today yields zero. Forked Codex totals are not attributed to
  daily usage, and coverage is flagged partial rather than inventing a delta.
- CONTEXT is the most recent request's input count divided by the recorded context
  window, when available. It is not a measurement of exact live context occupancy.
- Claude's official `claude -p /usage --output-format json` command supplies the
  current and weekly usage percentages and reset times. If the command is unavailable,
  those values remain unavailable rather than being invented.
- Codex limit snapshots carry their own timestamps; snapshots older than ten minutes
  or past a reset are labeled OLD. No reset is simulated and no percentage is invented.
- Source discovery runs every 30 seconds; appended records are read on the normal
  sampler cadence, with an 8 MiB budget per agent/sample and at most 512 newest files.
  Incomplete, denied, malformed, oversized or forked logs are marked PARTIAL.
  Tokens in a selected partial log may be incomplete. Subsequent samples catch up
  automatically, including when a JSON line is still being written.
- Only allowlisted numerical usage and metadata are retained. Prompt text, tool
  inputs/outputs, account credentials and raw JSON records never enter `/api/status`.

The local formats are version-dependent. Reference documentation:
[Codex app-server events](https://learn.chatgpt.com/docs/app-server) and
[Claude's local directory](https://code.claude.com/docs/en/claude-directory).
The adapters use the formats observed on this host; unknown fields stay unknown.

Network availability means an up interface with a usable non-loopback,
non-link-local IP. It does not verify Internet connectivity. Disk usage describes
the volume containing this dashboard. Unborn repositories return a null commit.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Optional browser checks use the locally installed Chrome and a development-only
Python helper (not a frontend or runtime dependency):

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
# Leave app.py running in another terminal.
.\.venv\Scripts\python.exe tests/check_browser.py
```

The current city-photo smoke check validates the local weather response and that a
JPEG is decoded by a browser. A modern browser check does not substitute for testing
on the physical iPad, especially for old Safari cache and layout behavior.
