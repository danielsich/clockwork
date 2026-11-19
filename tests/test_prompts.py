"""Tests for telling human prompts apart from other user-role records.

The Claude API sends every tool result back to the model as a user message,
and Claude Code logs injected context and command output under the same role.
So `prompts` (every user-role record) overstates what a person typed, often
several times over. `human_prompts` counts only messages a person sent, while
activity (sessions, active time) keeps using every record.
"""

import json
from datetime import datetime, timezone

import pytest

from clockwork_cli import (
    PROVIDERS,
    _claude_is_human_prompt,
    _claude_scan_files,
    analyze_all,
    export_data,
)


def user(ts, content, **extra):
    record = {"type": "user", "timestamp": ts,
              "message": {"role": "user", "content": content}}
    record.update(extra)
    return record


def tool_result(ts):
    return user(ts, [{"type": "tool_result", "tool_use_id": "t1",
                      "content": "ok"}], toolUseResult={"stdout": "ok"})


HUMAN = {"kind": "human"}


@pytest.mark.parametrize("record, expected", [
    # Tagged records: the origin decides, whatever the content looks like.
    (user("t", "fix the tests", origin=HUMAN), True),
    (user("t", [{"type": "image"}, {"type": "text", "text": "[Image #1] why?"}],
          origin=HUMAN), True),
    (user("t", "<command-message>humanizer</command-message>", origin=HUMAN), True),
    (user("t", "<task-notification>…", origin={"kind": "task-notification"}), False),
    # Untagged records (older logs): classified by shape.
    (user("t", "fix the tests"), True),
    (user("t", "/compact"), True),
    (user("t", "<command-message>insights</command-message>"), True),
    (tool_result("t"), False),
    (user("t", "Base directory for this skill: …", isMeta=True), False),
    (user("t", "This session is being continued…", isCompactSummary=True), False),
    (user("t", "<command-name>/model</command-name>"), False),
    (user("t", "<local-command-stdout>Set model</local-command-stdout>"), False),
    (user("t", "<local-command-caveat>Caveat: …</local-command-caveat>"), False),
    (user("t", "<bash-input>ls</bash-input>"), False),
    (user("t", "<bash-stdout>a b</bash-stdout>"), False),
    (user("t", "<task-notification><task-id>x</task-id>"), False),
    (user("t", [{"type": "text", "text": "[Request interrupted by user]"}]), False),
    (user("t", [{"type": "text",
                 "text": "[Request interrupted by user for tool use]"}]), False),
    # Typed while a tool ran: folded into the tool result as a text block.
    (user("t", [{"type": "tool_result", "content": "ok"},
                {"type": "text", "text": "and don't preview the screenshots"}]), True),
    (user("t", [{"type": "tool_result", "content": "ok"},
                {"type": "text", "text": "<system-reminder>…</system-reminder>"}]), False),
    # Injected wrapper ahead of the typed text does not hide it.
    (user("t", [{"type": "text", "text": "<system-reminder>…</system-reminder>"},
                {"type": "text", "text": "what next?"}]), True),
    (user("t", [{"type": "image", "source": {}}]), True),
])
def test_classifier(record, expected):
    assert _claude_is_human_prompt(record) is expected


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return str(path)


def test_scan_keeps_all_records_as_activity_and_counts_humans_apart(tmp_path):
    log = write_jsonl(tmp_path / "s.jsonl", [
        user("2026-07-01T10:00:00.000Z", "do the thing", uuid="u1", origin=HUMAN),
        tool_result("2026-07-01T10:01:00.000Z"),
        tool_result("2026-07-01T10:02:00.000Z"),
        user("2026-07-01T10:03:00.000Z", "<command-name>/model</command-name>"),
        user("2026-07-01T10:05:00.000Z", "now this", uuid="u2", origin=HUMAN),
    ])
    activity, _, human = _claude_scan_files([log])
    assert len(activity) == 5
    assert [t.minute for t in human] == [0, 5]


def test_replayed_prompts_are_counted_once(tmp_path):
    """A resumed session copies earlier messages into its new log."""
    first = user("2026-07-01T10:00:00.000Z", "hello", uuid="u1", origin=HUMAN)
    a = write_jsonl(tmp_path / "a.jsonl", [first])
    b = write_jsonl(tmp_path / "b.jsonl", [
        first,
        user("2026-07-02T09:00:00.000Z", "again", uuid="u2", origin=HUMAN),
    ])
    _, _, human = _claude_scan_files([a, b])
    assert len(human) == 2


# --------------------------------------------------------------------------- #
# Output: `prompts` keeps its meaning, `human_prompts` rides alongside
# --------------------------------------------------------------------------- #

def _ts(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


# One session: a human prompt, three tool results, a second human prompt; then
# a second session the next day with one human prompt and one tool result.
ACTIVITY = [_ts(2026, 7, 1, 10, 0), _ts(2026, 7, 1, 10, 1), _ts(2026, 7, 1, 10, 2),
            _ts(2026, 7, 1, 10, 3), _ts(2026, 7, 1, 10, 20),
            _ts(2026, 7, 2, 9, 0), _ts(2026, 7, 2, 9, 5)]
HUMAN_TS = [_ts(2026, 7, 1, 10, 0), _ts(2026, 7, 1, 10, 20), _ts(2026, 7, 2, 9, 0)]
PROJECT = ("/Users/you/dev/alpha", ACTIVITY, [], HUMAN_TS)


@pytest.fixture
def stub_claude(monkeypatch):
    monkeypatch.setitem(PROVIDERS["claude"], "all",
                        lambda: [(PROJECT[0], PROJECT[1], PROJECT[3])])
    monkeypatch.setitem(PROVIDERS["claude"], "scan", lambda: [PROJECT])
    monkeypatch.setitem(PROVIDERS["codex"], "all", lambda: [])
    monkeypatch.setitem(PROVIDERS["codex"], "scan", lambda: [])


def test_export_carries_both_counts_everywhere(stub_claude, capsys):
    export_data("claude", 30, None, None, "raw", False)
    data = json.loads(capsys.readouterr().out)
    proj = data["projects"][0]

    assert data["schema"] == "clockwork/v3"  # additive, no bump
    assert proj["totals"]["prompts"] == 7
    assert proj["totals"]["human_prompts"] == 3
    assert [(d["prompts"], d["human_prompts"]) for d in proj["daily"]] == [(5, 2), (2, 1)]
    assert [(s["prompts"], s["human_prompts"]) for s in proj["sessions"]] == [(5, 2), (2, 1)]
    assert len(proj["prompts"]) == 7
    assert len(proj["human_prompts"]) == 3
    assert data["totals"]["human_prompts"] == 3
    assert data["totals"]["by_provider"]["claude"]["human_prompts"] == 3


def test_active_time_is_built_on_activity_not_human_prompts(stub_claude, capsys):
    export_data("claude", 30, None, None, "sessions", False)
    proj = json.loads(capsys.readouterr().out)["projects"][0]
    # 10:00 → 10:20 and 09:00 → 09:05: the tool results extend the sessions.
    assert [s["minutes"] for s in proj["sessions"]] == [20.0, 5.0]


def test_tables_show_human_prompts(stub_claude, capsys):
    analyze_all("claude", 30, None, None, as_json=False)
    out = capsys.readouterr().out
    assert "Prompts : 3 total" in out


def test_json_keeps_prompts_and_adds_human_prompts(stub_claude, capsys):
    analyze_all("claude", 30, None, None, as_json=True)
    data = json.loads(capsys.readouterr().out)
    assert data["totals"]["prompts"] == 7
    assert data["totals"]["human_prompts"] == 3
    assert data["projects"][0]["human_prompts"] == 3
