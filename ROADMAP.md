# Roadmap

Known problems and decisions that outlive a single change. The proportions
quoted below come from one machine, mine, over a couple of months of daily use.
They are rough, and they will not be your numbers. How far off the prompt count
runs depends on how tool heavy your sessions are, so a style built around long
autonomous runs skews much harder than one built around conversation. Measure
your own logs before acting on any of this.

---

## 1. `prompts` counts tool results, not prompts (Claude side)

Status: the Claude prompt count is fixed and ships as a new field,
`human_prompts`. The matching Codex activity gap (below) is still open.

### The problem

`_claude_scan_files` treated every record whose `role`/`type` is `user` as a
prompt. Most of those records are tool results being fed back to the model, not
anything a person typed. Sorting my own logs by record shape, tool results were
the large majority of the count, actual human prompts were a small minority,
and the remainder was `isMeta` records plus slash-command output. The reported
prompt count came out several times higher than the number of things I had
typed.

The Codex reader does not have this problem. It counts canonical
`event_msg → user_message` records, or the `item_completed` → `UserMessage`
items that replaced them in newer rollouts, and never sees tool
output, because Codex logs that separately as
`response_item → function_call_output` / `custom_tool_call_output`, which the
reader ignores. In my rollouts the ignored tool outputs outnumbered the human
messages by more than ten to one.

So the two providers reported different units under one label.

### Why the obvious fix is wrong

Filtering tool results out of the timestamp stream also removes them from
session grouping, and they are what keeps a long autonomous tool run from
reading as idle. Dropping them from my logs cut total active time by a low
double-digit percentage while producing *more* sessions than before: runs
where Claude worked past the idle threshold without human input split at the
gap and lost the middle.

Those timestamps are worth keeping as activity data. The mistake was filing
them under a label that says a person typed something.

### What shipped

Every backend now returns two timestamp streams per project:

- Activity: every user-role record, unchanged. Session grouping and active
  time use these, so totals did not move.
- Human: messages a person sent. Counted as `human_prompts` everywhere
  `prompts` appears (totals, `daily[]`, `sessions[]`, `by_provider`, and the
  `--detail raw` timestamp list). For Codex the two streams are the same list.

`prompts` keeps its old meaning, so existing consumers do not break, and the
export stays `clockwork/v3`. The ASCII tables show `human_prompts` under
**Prompts**.

Classification (`_claude_is_human_prompt`), re-derived from the logs:

- Newer Claude Code versions tag real input with `origin.kind == "human"`.
  When `origin` is present it decides. It is not on every record, even in
  newer versions, so its absence means nothing.
- Untagged records are human unless they are `isMeta`, `isCompactSummary`, or
  lead with a wrapper: `<command-name>` (local slash commands such as `/model`,
  `/clear`), `<local-command-*>`, `<bash-input>` / `<bash-stdout>`
  (`!` shell), `<task-notification>`, `<system-reminder>`, or
  `[Request interrupted by user…]`. Skill-style commands lead with
  `<command-message>` instead and count.
- A tool result record is not a prompt unless it carries a plain text block:
  text typed while a tool was running is folded into that tool's result.
- Human prompts are deduplicated on record `uuid`, because a resumed session
  replays earlier messages into its new log. Activity is not deduplicated
  (duplicates cost no time).

### The same asymmetry runs backwards for active time (open)

`_codex_scan_file` builds its timestamp list from prompt records only
(`user_message`, then `UserMessage` items, then `response_item` user-role
messages); it never reads `function_call_output`, `custom_tool_call_output`,
or the tool-side `item_completed` items (`CommandExecution`, `McpToolCall`,
`FileChange`). Codex activity is therefore prompt only, which is exactly the
state the section above rejects for Claude, and for the same reason: a long
Codex tool run with no human input reads as idle and splits into separate
sessions.

Claude subagent transcripts (`<session>/subagents/*.jsonl`) sit in the same
gap. They are read for tokens only, since their user-role records are task
prompts and tool results; their timestamps belong in the activity stream.

That makes `both` mode compare a tool-aware timeline against a prompt-only one,
so Codex active time is understated relative to Claude by roughly the margin
that the filtering experiment above measured. The fix is to add the tool-side
records to the Codex activity stream, leaving its human stream as it is. That
changes Codex active time, so compare totals before and after.

### Still to decide

- meter's hourly heatmap reads `--detail raw` timestamps. Whether that view
  wants `human_prompts` (when you engage) or `prompts` (when the machine was
  busy) is a product question, and the two answer different things. Probably
  both, selectable.
- meter labels its number `PROMPTS`; it should read `human_prompts` when the
  bundle has it and fall back to `prompts` for older ones.

### Verification

Insights is not a like-for-like check. Its per-session data
(`~/.claude/usage-data/session-meta/*.json`, `user_message_timestamps`) counts
every user record that is not a bare tool result, including `/clear` echoes,
meta caveats, `!` shell output, task notifications, and interrupt markers. So
Insights runs higher than `human_prompts`, and diffing the two by timestamp
should only show those wrapper shapes. On my logs it also skipped about one
genuine-looking typed message per session in a minority of sessions, for
reasons I could not pin down (some, not all, sit on rewound branches). Those
stay counted.

The regression check that matters: active time, sessions and `prompts` must be
identical to the previous build, project by project, over a fixed `--until`
window. They were.

---

## Reference: token totals intentionally disagree with `/usage`

**Decided. Do not "fix" this to match.**

`clockwork --tokens` reports roughly half what Claude Code's `/usage` shows.
Neither number is wrong, they just count different things.

Claude Code writes one log line per content block (thinking, text, each
tool_use), and every line of a single API response repeats the *same* usage
object. Across every multi-line response on my machine, and there were
thousands, each line's usage block was byte-identical to its siblings and every
line shared one `requestId`. Assistant lines outnumbered distinct API responses
by roughly two to one.

Summing per line reproduces `/usage` almost exactly, down to matching per-model
figures. Counting once per `message.id` gives clockwork's number
(`_claude_token_event`). That identical-usage observation holds for main
session logs only. Subagent logs write a response's first line mid-stream with
a partial output count, so the dedup keeps the largest value per field rather
than the first line. The API bills per request, so the deduplicated figure is the
true count of tokens processed. `by_model` and tokens-per-response follow from
that.

Note also that `/usage` is Claude-only. If its total happens to resemble
clockwork's combined total, that is coincidence: clockwork's figure is Claude
plus Codex.

If this keeps surprising people, fix it with a line of UI copy ("counted once
per API response, not per logged line") rather than by changing the arithmetic.
