# clockwork

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
| `claude` | `~/.claude/projects/<encoded-path>/*.jsonl` |
| `codex`  | `$CODEX_HOME/sessions/**/rollout-*.jsonl` (default `~/.codex/sessions`) |

> **Note:** "active time" is a proxy. It measures time *within* sessions, so
> thinking and response time between prompts counts as active, and a session
> with a single prompt is floored to one minute. Treat the totals as a
> reasonable estimate, not a stopwatch.

## Requirements

- Python 3.7+ (standard library only — no `pip install` needed)

## Install

Clone the repo and put the script on your `PATH`:

```bash
git clone https://github.com/danielsich/clockwork.git
cd clockwork
chmod +x clockwork

# option A: symlink into a directory already on your PATH
ln -s "$PWD/clockwork" ~/.local/bin/clockwork

# option B: just run it directly
./clockwork claude all
```

## Usage

```
clockwork <provider> <project-path> [idle-min]   Analyze one project
clockwork <provider> all [idle-min]              Rank all projects
clockwork <provider> list                        List project folders

  <provider> is one of: claude | codex
```

### Examples

```bash
# Time spent on a single project (Claude Code)
clockwork claude ~/dev/myproject

# Same, but treat gaps under 45 min as the same session (Codex)
clockwork codex ~/dev/myproject 45

# Rank every project you've worked on, most time first
clockwork codex all

# List the projects clockwork can see
clockwork claude list
```

The optional trailing number overrides the idle threshold in minutes
(default `30`). A larger threshold merges short breaks into one session; a
smaller one splits work into more, shorter sessions.

## License

[MIT](LICENSE) © 2026 Daniel Sich
