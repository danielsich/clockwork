# clockwork

[![PyPI](https://img.shields.io/pypi/v/clockwork-cli)](https://pypi.org/project/clockwork-cli/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/danielsich/clockwork)

A tiny, dependency-free CLI that mines your **Claude Code** and **Codex**
session logs to estimate how much *active* time you've actually spent — per
project, per day — and renders it as ASCII bar charts in your terminal.

No config, no database, no telemetry. Just Python 3 and the log files those
tools already write to your machine.

```
====================================================
  CLOCKWORK — CLAUDE SESSION ANALYSIS
====================================================
  Project : ~/dev/clockwork
  First   : 2026-06-28 09:12
  Last    : 2026-07-05 23:34
  Span    : 8 calendar days
  Prompts : 214 total
  Sessions: 19 (idle threshold: 30 min)
  Active  : 6 days
  Total   : 11h 42m
====================================================

DATE           ACTIVE TIME    PROMPTS    BAR
----------------------------------------------------
  2026-06-28   2h 05m         38         ████████████████████
  2026-06-29   1h 12m         21         ███████████
  2026-07-01   0h 48m         14         ███████
  ...
```

## How it works

`clockwork` reads the JSONL transcripts each tool writes, extracts the
timestamps of your **prompts** (not the assistant's replies), and groups them
into sessions. Any gap longer than the *idle threshold* (default 30 minutes)
starts a new session. A session's duration is the time from its first to its
last prompt, split across calendar-day boundaries so a session that crosses
midnight is credited to each day it spans.

**Data sources**

| Provider | Location |
| -------- | -------- |
| `claude` | `~/.claude/projects/<encoded-path>/*.jsonl` (macOS/Linux)<br>`%APPDATA%\Claude\projects\<encoded-path>\*.jsonl` (Windows) |
| `codex`  | `$CODEX_HOME/sessions/**/rollout-*.jsonl` (default `~/.codex/sessions`) |
| `both`   | merges the two sources per project |

> **Note:** "active time" is a proxy. It measures time *within* sessions, so
> thinking and response time between prompts counts as active, and a session
> with a single prompt is floored to one minute. Treat the totals as a
> reasonable estimate, not a stopwatch.

> **`both` and path matching:** `both` combines Claude and Codex prompts by
> project path. Single-project mode (`clockwork both ~/dev/x`) is exact,
> because it encodes the path you pass. In `all` / `export` / `list`, projects
> are matched by their displayed path — and Claude stores paths dash-encoded,
> so one containing spaces or dashes can't always be reversed to match Codex's
> real path. Such a project may appear as two rows rather than merging.

## Requirements

- Python 3.7+ (standard library only — no dependencies)

## Install

**pip (recommended — works on macOS, Linux, and Windows)**

```bash
pip install clockwork-cli
```

This puts `clockwork` on your PATH. Done.

**From source — macOS / Linux**

```bash
git clone https://github.com/danielsich/clockwork.git
cd clockwork
chmod +x clockwork

# option A: symlink into a directory already on your PATH
ln -s "$PWD/clockwork" ~/.local/bin/clockwork

# option B: just run it directly
./clockwork claude all
```

**From source — Windows**

```powershell
git clone https://github.com/danielsich/clockwork.git
cd clockwork

# Run directly with Python (the shebang line is ignored on Windows)
python clockwork claude all
```

> On Windows, clockwork looks for Claude logs in `%APPDATA%\Claude\projects`
> first, then `~\.claude\projects`.

## Usage

```
clockwork <provider> <project-path> [idle-min] [options]  Analyze one project
clockwork <provider> all [idle-min] [options]             Rank all projects
clockwork <provider> today [idle-min] [options]           Today, all projects
clockwork <provider> week [idle-min] [options]            Last 7 days, all projects
clockwork <provider> export [idle-min] [options]          Bundle all projects as JSON
clockwork <provider> list [options]                       List project folders

  <provider> is one of: claude | codex | both

Options:
  --json            Emit machine-readable JSON instead of ASCII tables
  --since <when>    Only count prompts on/after this point in time
  --until <when>    Only count prompts on/before this point in time
                    <when> is YYYY-MM-DD, an ISO timestamp, or a relative
                    form like 7d (7 days ago) or 2w (2 weeks ago)
  --detail <level>  export granularity: raw | sessions | daily (default raw)
  --anonymize       export: replace project paths with a hash id + generic name
```

### Examples

```bash
# Time spent on a single project (Claude Code)
clockwork claude ~/dev/myproject

# Same, but treat gaps under 45 min as the same session (Codex)
clockwork codex ~/dev/myproject 45

# Both tools at once — combined time on one project, or ranked across all
clockwork both ~/dev/myproject
clockwork both today

# Rank every project you've worked on, most time first
clockwork codex all

# List the projects clockwork can see
clockwork claude list

# Daily check-in: everything you did today, across all projects
clockwork claude today

# Your week at a glance (per-project + a day-by-day breakdown)
clockwork codex week

# Only the last 7 days, across all projects
clockwork claude all --since 7d

# A specific date range for one project
clockwork claude ~/dev/myproject --since 2026-07-01 --until 2026-07-05

# Machine-readable output — pipe into jq, a spreadsheet, or a dashboard
clockwork codex all --json | jq '.projects[] | {project, minutes}'
```

The optional trailing number overrides the idle threshold in minutes
(default `30`). A larger threshold merges short breaks into one session; a
smaller one splits work into more, shorter sessions.

### Daily & weekly summaries

`today` and `week` aggregate **every** project into a single check-in instead
of analyzing one at a time. `today` covers local midnight to now; `week` is a
rolling 7-day window ending today. Both show a per-project breakdown, and
`week` adds a day-by-day view so you can see your week at a glance. Day
boundaries are **local time**, so "today" means your calendar day, not UTC's.
They honor the optional `idle-min` and pair with `--json`.

### Filtering by date

`--since` and `--until` restrict which prompts are counted. Each accepts a
bare date (`2026-07-01`), a full ISO timestamp, or a relative form — `7d`
(7 days ago) or `2w` (2 weeks ago). A bare `--until` date is inclusive of the
whole day. This works in every mode (`<project>`, `all`, and `list`-adjacent
analysis).

### JSON output

`--json` swaps the ASCII tables for structured JSON on stdout (errors and
usage still go to stderr), so clockwork composes with `jq`, cron jobs, or any
dashboard. Exit codes are script-friendly: `0` on success, `1` when nothing
matched, `2` for bad arguments.

## Exporting for external tools

`clockwork <provider> export` writes a single **self-describing, versioned**
JSON bundle covering every project at once — the format a companion web app or
dashboard would ingest. Unlike `--json` on the analysis commands (which emits
one pre-aggregated view), the export is designed to be re-analyzed downstream.

```bash
# Full-fidelity export you can re-analyze anywhere
clockwork claude export > clockwork.json

# Both tools in one bundle, attributed per provider (see "Provider attribution")
clockwork both export > clockwork.json

# Smaller / shareable: grouped sessions only, with paths stripped
clockwork codex export --detail sessions --anonymize > share.json

# Export honors --since/--until too
clockwork claude export --since 30d > last-month.json
```

**Detail levels** (`--detail`, default `raw`). Each level is a superset of the
one below, so a consumer can start with the aggregates and drill down:

| Level | Adds | Lets a consumer… |
| ----- | ---- | ---------------- |
| `daily` | per-day `minutes` / `prompts` | draw timelines and totals |
| `sessions` | grouped `sessions` (start/end + prompt count) | re-bucket by timezone / date range |
| `raw` | every prompt as an epoch-second timestamp | re-apply **any** idle threshold, build hour-of-day heatmaps, streaks — anything |

**Privacy.** Paths are included by default (it's your own data). `--anonymize`
drops the `path`, renames projects to `project-N`, and keeps only a stable
hash `id` — so an uploaded file leaks nothing identifying while still letting a
tool tell projects apart across exports.

### Provider attribution

`clockwork both export` carries **both tools in one bundle** without merging
them: attribution lives at the project level. Every project entry has a
`provider`, and if the same path was touched by both Claude and Codex it emits
**one entry per (path, provider)** — each with its own `totals`, `daily`,
`sessions`, and `prompts`. A viewer can filter by provider or re-merge by path
for a combined view, so nothing is lost either way.

- Top-level `provider` is `"both"` when more than one provider contributed,
  otherwise the single provider name (so a `both` export with only Claude
  activity still reads `"claude"`).
- `providers` lists the sorted, distinct providers included (always present,
  one element for a single-provider export).
- `totals.by_provider` breaks the grand totals down per provider; the grand
  `totals` stay the cross-provider sum.

### Export schema (`clockwork/v2`)

```jsonc
{
  "schema": "clockwork/v2",
  "generated_at": "2026-07-06T00:30:00+02:00",  // local ISO-8601
  "provider": "both",         // "claude" | "codex" | "both"
  "providers": ["claude", "codex"],  // sorted, distinct; ≥ 1 element
  "idle_threshold_min": 30,
  "detail": "raw",           // raw | sessions | daily
  "anonymized": false,
  "daily_tz": "UTC",         // the "daily" buckets use UTC calendar dates
  "since": null,             // ISO bound if --since was given, else null
  "until": null,
  "projects": [
    {
      "id": "0ac6be84",      // stable sha1(provider + "\0" + path) prefix; survives --anonymize
      "provider": "claude",  // the single tool this entry's activity belongs to
      "name": "myproject",   // basename, or "project-N" when anonymized
      "path": "/Users/you/dev/myproject",   // omitted when anonymized
      "totals": {
        "minutes": 1234.76, "prompts": 1646, "sessions": 27,
        "active_days": 12,
        "first": 1780521570, "last": 1782130426   // epoch seconds
      },
      "daily":    [ { "date": "2026-06-03", "minutes": 4.34, "prompts": 27 } ],
      "sessions": [ { "start": 1780521570, "end": 1780521830,
                      "minutes": 4.34, "prompts": 27 } ],  // detail >= sessions
      "prompts":  [ 1780521570, 1780521582 ]               // detail == raw
    }
  ],
  "totals": {
    "projects": 6, "minutes": 3392.97, "prompts": 4588, "sessions": 64,
    "by_provider": {
      "claude": { "projects": 4, "minutes": 2500.0, "prompts": 3000, "sessions": 40 },
      "codex":  { "projects": 2, "minutes": 892.97, "prompts": 1588, "sessions": 24 }
    }
  }
}
```

All instants are **UTC-based epoch seconds** (`new Date(sec * 1000)` in JS), so
the consumer picks the display timezone. The `schema` field is the version
contract — `clockwork/v2` is a breaking bump over `v1` (provider moved to the
project level), so tools should guard on it.

## License

[MIT](LICENSE) © 2026 Daniel Sich
