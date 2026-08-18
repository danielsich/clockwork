# Roadmap

Known problems and decisions that outlive a single change. Numbers here were
measured on 2026-08-18 against one machine's logs (171 Claude session files and
167 Codex rollouts, spanning 2026-06-08 → 2026-08-18). Re-measure before acting
on any of them.

---

## 1. `prompts` counts tool results, not prompts (Claude side)

**Status:** open, not started. **Impact:** the headline number in every view is
~6x too high on Claude, and is not comparable to the Codex number beside it.

### The problem

`_claude_scan_files` treats every record whose `role`/`type` is `user` as a
prompt. Most of those records are tool results being fed back to the model, not
anything a person typed:

```
records counted as a "prompt": 7,923

  tool_result            6,477  (81.7%)   ← tool output returned to the model
  HUMAN PROMPT           1,160  (14.6%)
  isMeta                   152  ( 1.9%)
  slash-command output     134  ( 1.7%)
```

Non-tool-result, non-meta records come to 1,294, against the 1,318 messages
Claude Code's own Insights report shows for a slightly narrower window. Same
quantity; the residual is edge-case classification (pasted attachments, some
meta records).

The Codex reader does not have this problem — it counts canonical
`event_msg → user_message` records and never sees tool output, because Codex
logs that as `response_item → function_call_output` / `custom_tool_call_output`:

```
codex   human messages counted        637
        tool outputs NOT counted    8,095
```

So the two providers report different units under one label. Any per-provider
prompt comparison — in `both` mode, in the export, or in meter — is currently
meaningless.

### Why the obvious fix is wrong

Filtering tool results out of the timestamp stream also removes them from
session grouping, and they are what keeps a long autonomous tool run from
reading as idle:

```
all user records   102.5h   155 sessions   ← current behaviour
human prompts only  89.6h   162 sessions
                   −12.9h (12.6%), and MORE sessions
```

Runs where Claude worked for longer than the idle threshold without human input
would split at the gap and lose the middle. The tool-result timestamps are good
activity data; they are just not prompts.

### Proposed shape

Separate the two concepts the code currently conflates:

- **Activity timestamps** — every user-role record, unchanged. Session grouping
  and active time keep using these, so `102.5h` stays `102.5h`.
- **`prompts`** — human-authored messages only, defined the same way on both
  providers, so the number means "things I typed" and lines up with Insights.
- Optionally keep the raw count as a second field (`turns`, or `events`) — it is
  a reasonable proxy for how tool-heavy a stretch of work was, and it is what
  today's `prompts` field actually measures.

Classification for Claude: a user record is human-authored unless it carries a
`tool_result` content block, is `isMeta`, or is slash-command output
(`<command-name>` / `<local-command-stdout>` text). Worth re-deriving from the
logs rather than trusting this list — the record shapes drift between versions.

### Knock-on effects

- **Export schema.** `prompts` changes meaning, which is a breaking change for
  any consumer that has been reading it — unlike the additive v3 token work.
  Either bump to `clockwork/v4` or introduce the corrected field under a new
  name and leave `prompts` alone. Decide before implementing.
- **`daily[].prompts` and `sessions[].prompts`** carry the same defect and need
  the same treatment.
- **`--detail raw` `prompts[]` timestamps.** meter's hourly heatmap reads these.
  Whether that view wants human prompts (when you engage) or all activity (when
  the machine was busy) is a real product question — they answer different
  things. Probably both, selectable.
- **meter** displays the number as `PROMPTS`; it will need the new field and a
  label that matches whichever definition wins.

### Verification

Compare against Claude Code's Insights report (`~/.claude/usage-data/report.html`)
over a matched date window; the corrected count should land within a few percent.
Confirm the active-time total is unchanged from the current build, project by
project — that is the regression that matters most.

---

## Reference: token totals intentionally disagree with `/usage`

**Decided. Do not "fix" this to match.**

`clockwork --tokens` reports roughly half what Claude Code's `/usage` shows
(765.6M vs 1.6b on this machine). The gap is not an error in either tool — they
count different things.

Claude Code writes one log line per content block (thinking, text, each
tool_use), and every line of a single API response repeats the *same* usage
object. Checked across all multi-line responses on this machine:

```
responses logged across >1 line: 4,657 of 6,778
  every line's usage byte-identical : 4,657 (100.0%)
  every line shares one requestId   : 4,657 (100.0%)

assistant lines 14,268 | unique API responses 6,776 | 2.11 lines per response
```

Summing per line reproduces `/usage` (1.59b vs its 1.6b, and Claude Opus 4.8
matches on all four fields to three significant figures). Counting once per
`message.id` gives clockwork's number. Since the API bills per request and there
were 6,776 requests, the deduplicated figure is the true count of tokens
processed — so clockwork deduplicates, and `by_model` / tokens-per-response
follow from that.

Note also that `/usage` is Claude-only. Its 1.6b resembling clockwork's 1.56b
combined total is coincidence: clockwork's figure is Claude 765.6M **plus**
Codex 801.4M.

If this keeps surprising people, the fix is a line of UI copy — "counted once
per API response, not per logged line" — not a change to the arithmetic.
