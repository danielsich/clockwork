# Roadmap

Known problems and decisions that outlive a single change.

The proportions quoted below come from one machine, mine, over a couple of
months of daily use. They are rough, and they will not be your numbers. How far
off the prompt count runs depends entirely on how tool-heavy your sessions are,
so a session style built around long autonomous runs will skew much harder than
one built around conversation. Measure your own logs before acting on any of
this.

---

## 1. `prompts` counts tool results, not prompts (Claude side)

Status: open, not started. Impact: the headline number in every view is
inflated on Claude by a large multiple, and it does not mean the same thing as
the Codex number printed beside it.

### The problem

`_claude_scan_files` treats every record whose `role`/`type` is `user` as a
prompt (`clockwork:425`). Most of those records are tool results being fed back
to the model, not anything a person typed. Sorting my own logs by record shape,
tool results were the large majority of the count, actual human prompts were a
small minority, and the remainder was `isMeta` records plus slash-command
output. The reported prompt count came out several times higher than the number
of things I had typed.

Filtering to non-tool-result, non-meta records lands very close to what Claude
Code's own Insights report shows for the same window, close enough that the
residual is edge-case classification (pasted attachments, some meta records)
rather than a different definition.

The Codex reader does not have this problem. It counts canonical
`event_msg → user_message` records (`clockwork:566`) and never sees tool
output, because Codex logs that separately as
`response_item → function_call_output` / `custom_tool_call_output`, which the
reader ignores. In my rollouts the ignored tool outputs outnumbered the human
messages by more than ten to one.

So the two providers report different units under one label. Any per-provider
prompt comparison is currently meaningless, whether it comes from `both` mode,
the export, or meter.

### Why the obvious fix is wrong

Filtering tool results out of the timestamp stream also removes them from
session grouping, and they are what keeps a long autonomous tool run from
reading as idle. Dropping them from my logs cut total active time by a low
double-digit percentage and produced *more* sessions, not fewer: runs where
Claude worked past the idle threshold without human input split at the gap and
lost the middle.

The tool-result timestamps are good activity data. They are just not prompts.

### Proposed shape

Separate the two concepts the code currently conflates:

- Activity timestamps: every user-role record, unchanged. Session grouping and
  active time keep using these, so today's totals stay put.
- `prompts`: human-authored messages only, defined the same way on both
  providers, so the number means "things I typed" and lines up with Insights.
- Optionally keep the raw count as a second field (`turns`, or `events`). It is
  a reasonable proxy for how tool-heavy a stretch of work was, and it is what
  today's `prompts` field actually measures.

Classification for Claude: a user record is human-authored unless it carries a
`tool_result` content block, is `isMeta`, or is slash-command output
(`<command-name>` / `<local-command-stdout>` text). Worth re-deriving from the
logs rather than trusting this list, since the record shapes drift between
versions.

### The same asymmetry runs backwards for active time

Fixing `prompts` alone leaves a matching defect in place, pointing the other
way. `_codex_scan_file` builds its timestamp list from `user_message` events
only, falling back to `response_item` user-role messages; it never reads
`function_call_output` or `custom_tool_call_output`. Codex activity is
therefore already prompt-only, which is exactly the state the section above
rejects for Claude, and for the same reason: a long Codex tool run with no
human input reads as idle and splits into separate sessions.

That makes `both` mode compare a tool-aware timeline against a prompt-only one,
so Codex active time is understated relative to Claude by roughly the margin
that the filtering experiment above measured. Whichever activity definition
Claude keeps, Codex needs the matching one, which means adding tool-output
records to its timestamp stream. Different code path, same root confusion, and
it should ship alongside the prompt work rather than after it.

### Knock-on effects

- Export schema. `prompts` changes meaning, which breaks any consumer that has
  been reading it, unlike the additive v3 token work. Either bump
  `clockwork/v3` to `clockwork/v4` (`clockwork:1357`) or introduce the
  corrected field under a new name and leave `prompts` alone. Decide before
  implementing.
- `daily[].prompts` and `sessions[].prompts` carry the same defect and need the
  same treatment.
- `--detail raw` `prompts[]` timestamps (`clockwork:1315`). meter's hourly
  heatmap reads these. Whether that view wants human prompts (when you engage)
  or all activity (when the machine was busy) is a real product question, and
  the two answer different things. Probably both, selectable.
- meter displays the number as `PROMPTS`; it will need the new field and a
  label that matches whichever definition wins.

### Verification

Compare against Claude Code's Insights report (`~/.claude/usage-data/report.html`)
over a matched date window; the corrected count should land within a few percent.
Confirm the active-time total is unchanged from the current build, project by
project. That is the regression that matters most.

---

## Reference: token totals intentionally disagree with `/usage`

**Decided. Do not "fix" this to match.**

`clockwork --tokens` reports roughly half what Claude Code's `/usage` shows.
The gap is not an error in either tool. They count different things.

Claude Code writes one log line per content block (thinking, text, each
tool_use), and every line of a single API response repeats the *same* usage
object. Across every multi-line response on my machine, and there were
thousands, each line's usage block was byte-identical to its siblings and every
line shared one `requestId`. Assistant lines outnumbered distinct API responses
by roughly two to one.

Summing per line reproduces `/usage` almost exactly, down to matching per-model
figures. Counting once per `message.id` gives clockwork's number
(`clockwork:386`). The API bills per request, so the deduplicated figure is the
true count of tokens processed. `by_model` and tokens-per-response follow from
that.

Note also that `/usage` is Claude-only. If its total happens to resemble
clockwork's combined total, that is coincidence: clockwork's figure is Claude
plus Codex.

If this keeps surprising people, fix it with a line of UI copy ("counted once
per API response, not per logged line") rather than by changing the arithmetic.
