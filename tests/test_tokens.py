"""Tests for token/model usage extraction.

The two providers log usage in shapes that both need correcting before they
can be summed, and each has a way of overstating the total if read naively:

  claude → one API response is written as several lines (thinking, text, each
           tool_use) that all repeat the *same* usage block
  codex  → aborted and no-op turns re-emit a stale `last_token_usage` that the
           cumulative counter never absorbs

These exercise the readers against small hand-written log fixtures, so the
expected numbers are checkable by eye.
"""

import json
from datetime import datetime, timezone

import pytest

from clockwork_cli import (
    _claude_scan_files,
    _codex_scan_file,
    summarize_tokens,
    tokens_by_day,
    _filter_events,
    fmt_tokens,
)


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return str(path)


# --------------------------------------------------------------------------- #
# Claude
# --------------------------------------------------------------------------- #

def claude_assistant(msg_id, model, ts, usage, block="text"):
    return {
        "type": "assistant",
        "timestamp": ts,
        "requestId": "req_" + msg_id,
        "message": {"id": msg_id, "model": model, "role": "assistant",
                    "content": [{"type": block}], "usage": usage},
    }


CLAUDE_USAGE_1 = {"input_tokens": 5, "output_tokens": 100,
                  "cache_read_input_tokens": 1000,
                  "cache_creation_input_tokens": 200}
CLAUDE_USAGE_2 = {"input_tokens": 7, "output_tokens": 50,
                  "cache_read_input_tokens": 2000,
                  "cache_creation_input_tokens": 0}


@pytest.fixture
def claude_log(tmp_path):
    ts1 = "2026-07-01T10:00:00.000Z"
    ts2 = "2026-07-02T11:00:00.000Z"
    return write_jsonl(tmp_path / "session.jsonl", [
        {"type": "user", "timestamp": "2026-07-01T09:59:00.000Z"},
        # One response, three content blocks, identical usage on every line.
        claude_assistant("msg_1", "claude-opus-5", ts1, CLAUDE_USAGE_1, "thinking"),
        claude_assistant("msg_1", "claude-opus-5", ts1, CLAUDE_USAGE_1, "text"),
        claude_assistant("msg_1", "claude-opus-5", ts1, CLAUDE_USAGE_1, "tool_use"),
        {"type": "user", "timestamp": "2026-07-02T10:59:00.000Z"},
        claude_assistant("msg_2", "claude-sonnet-5", ts2, CLAUDE_USAGE_2),
        # Locally generated message — never hit the API.
        claude_assistant("msg_3", "<synthetic>", ts2,
                         {"input_tokens": 0, "output_tokens": 0}),
        # Older/partial records with no usage block at all.
        {"type": "assistant", "timestamp": ts2,
         "message": {"id": "msg_4", "model": "claude-opus-5", "content": []}},
    ])


def test_claude_counts_each_response_once(claude_log):
    _, events = _claude_scan_files([claude_log])

    # Three lines for msg_1 plus one for msg_2 — two API responses.
    assert len(events) == 2
    assert [e["model"] for e in events] == ["claude-opus-5", "claude-sonnet-5"]


def test_claude_maps_cache_fields_and_leaves_input_alone(claude_log):
    _, events = _claude_scan_files([claude_log])
    first = events[0]

    # Claude reports cache reads/writes *outside* input_tokens, so input passes
    # through untouched and the cache fields land in their own slots.
    assert first["input"] == 5
    assert first["output"] == 100
    assert first["cache_read"] == 1000
    assert first["cache_write"] == 200
    assert first["reasoning"] == 0  # thinking is folded into output


def test_claude_skips_synthetic_and_usageless_records(claude_log):
    _, events = _claude_scan_files([claude_log])
    assert all(e["model"] not in ("<synthetic>", None) for e in events)


def test_claude_prompts_still_parsed_alongside_tokens(claude_log):
    timestamps, _ = _claude_scan_files([claude_log])
    assert len(timestamps) == 2  # the two user turns, assistants excluded


def test_claude_dedup_spans_files(tmp_path):
    """A response replayed into a resumed session's log is still counted once."""
    usage = dict(CLAUDE_USAGE_1)
    a = write_jsonl(tmp_path / "a.jsonl",
                    [claude_assistant("msg_1", "claude-opus-5",
                                      "2026-07-01T10:00:00.000Z", usage)])
    b = write_jsonl(tmp_path / "b.jsonl",
                    [claude_assistant("msg_1", "claude-opus-5",
                                      "2026-07-01T10:00:00.000Z", usage)])
    _, events = _claude_scan_files([a, b])
    assert len(events) == 1


# --------------------------------------------------------------------------- #
# Codex
# --------------------------------------------------------------------------- #

def codex_token_count(ts, input_tokens, cached, output, reasoning):
    """A token_count record; `last` is deliberately independent of `total`."""
    totals = {"input_tokens": input_tokens, "cached_input_tokens": cached,
              "output_tokens": output, "reasoning_output_tokens": reasoning,
              "total_tokens": input_tokens + output}
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "token_count",
                        "info": {"total_token_usage": totals,
                                 "last_token_usage": totals,
                                 "model_context_window": 353400}}}


@pytest.fixture
def codex_log(tmp_path):
    return write_jsonl(tmp_path / "rollout-test.jsonl", [
        {"type": "session_meta", "timestamp": "2026-07-01T09:00:00.000Z",
         "payload": {"cwd": "/Users/you/dev/alpha", "model_provider": "openai"}},
        # Logged before the first turn_context — model unknown at the time.
        codex_token_count("2026-07-01T09:01:00.000Z", 100, 40, 10, 4),
        {"type": "turn_context", "timestamp": "2026-07-01T09:02:00.000Z",
         "payload": {"model": "gpt-A", "cwd": "/Users/you/dev/alpha"}},
        {"type": "event_msg", "timestamp": "2026-07-01T09:03:00.000Z",
         "payload": {"type": "user_message", "message": "hi"}},
        codex_token_count("2026-07-01T09:04:00.000Z", 300, 140, 30, 10),
        # Aborted turn: last_token_usage is re-emitted, cumulative never moves.
        {"type": "event_msg", "timestamp": "2026-07-01T09:05:00.000Z",
         "payload": {"type": "turn_aborted"}},
        codex_token_count("2026-07-01T09:06:00.000Z", 300, 140, 30, 10),
        {"type": "turn_context", "timestamp": "2026-07-01T09:07:00.000Z",
         "payload": {"model": "gpt-B", "cwd": "/Users/you/dev/alpha"}},
        codex_token_count("2026-07-01T09:08:00.000Z", 500, 240, 50, 15),
    ])


def test_codex_ignores_stale_reemitted_usage(codex_log):
    _, _, events = _codex_scan_file(codex_log)

    # Four token_count records, but the aborted turn moved nothing.
    assert len(events) == 3
    assert sum(e["output"] for e in events) == 50


def test_codex_splits_cache_out_of_input(codex_log):
    _, _, events = _codex_scan_file(codex_log)
    first = events[0]

    # Codex counts cached_input_tokens *inside* input_tokens; clockwork pulls it
    # back out so `input` means fresh input on both providers.
    assert first["input"] == 60      # 100 reported - 40 cached
    assert first["cache_read"] == 40
    assert first["cache_write"] == 0  # never reported by Codex
    assert first["reasoning"] == 4    # a subset of output, kept out of `total`


def test_codex_attributes_turns_to_the_preceding_model(codex_log):
    _, _, events = _codex_scan_file(codex_log)
    # The pre-turn_context turn is back-filled with the session's first model
    # rather than being lost to "unknown".
    assert [e["model"] for e in events] == ["gpt-A", "gpt-A", "gpt-B"]


def test_codex_returns_cwd_and_prompts(codex_log):
    cwd, timestamps, _ = _codex_scan_file(codex_log)
    assert cwd == "/Users/you/dev/alpha"
    assert len(timestamps) == 1


def codex_user_item(ts, text):
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "item_completed",
                        "item": {"type": "UserMessage",
                                 "content": [{"type": "text", "text": text}]}}}


def codex_response_user(ts, text):
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": text}]}}


def test_codex_newer_rollouts_read_prompts_from_user_message_items(tmp_path):
    """Newer rollouts dropped `user_message`; typed input is a `UserMessage`
    item. The `response_item` copies, which include injected context, must
    not be counted alongside or instead of it."""
    path = write_jsonl(tmp_path / "rollout-new.jsonl", [
        {"type": "session_meta", "timestamp": "2026-11-09T14:22:00.000Z",
         "payload": {"cwd": "/Users/you/dev/alpha"}},
        codex_response_user("2026-11-09T14:22:01.000Z",
                            "<environment_context>…</environment_context>"),
        codex_response_user("2026-11-09T14:22:02.000Z", "first prompt"),
        codex_user_item("2026-11-09T14:22:02.000Z", "first prompt"),
        # Tool work is logged as items too and must not count as prompts.
        {"timestamp": "2026-11-09T14:22:05.000Z", "type": "event_msg",
         "payload": {"type": "item_completed",
                     "item": {"type": "CommandExecution"}}},
        codex_response_user("2026-11-09T14:30:00.000Z", "second prompt"),
        codex_user_item("2026-11-09T14:30:00.000Z", "second prompt"),
    ])
    _, timestamps, _ = _codex_scan_file(path)

    assert [t.minute for t in timestamps] == [22, 30]


def test_codex_falls_back_to_response_items_when_nothing_else(tmp_path):
    path = write_jsonl(tmp_path / "rollout-old.jsonl", [
        {"type": "session_meta", "timestamp": "2026-07-01T09:00:00.000Z",
         "payload": {"cwd": "/Users/you/dev/alpha"}},
        codex_response_user("2026-07-01T09:01:00.000Z", "hi"),
    ])
    _, timestamps, _ = _codex_scan_file(path)
    assert len(timestamps) == 1


def test_codex_missing_file_is_survivable(tmp_path):
    cwd, timestamps, events = _codex_scan_file(str(tmp_path / "nope.jsonl"))
    assert (cwd, timestamps, events) == (None, [], [])


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def test_summary_reconciles_with_per_model_breakdown(codex_log):
    _, _, events = _codex_scan_file(codex_log)
    summary = summarize_tokens(events)

    assert summary["responses"] == 3
    assert summary["input"] == 260
    assert summary["output"] == 50
    assert summary["cache_read"] == 240
    assert summary["reasoning"] == 15
    # total excludes reasoning, which is already inside output.
    assert summary["total"] == 260 + 50 + 240

    by_model = {m["model"]: m for m in summary["by_model"]}
    assert set(by_model) == {"gpt-A", "gpt-B"}
    assert by_model["gpt-A"]["responses"] == 2
    assert sum(m["total"] for m in summary["by_model"]) == summary["total"]
    # Biggest consumer first.
    assert summary["by_model"][0]["model"] == "gpt-A"


def test_daily_buckets_sum_to_the_total(claude_log):
    _, events = _claude_scan_files([claude_log])
    daily = tokens_by_day(events)
    summary = summarize_tokens(events)

    assert sorted(str(d) for d in daily) == ["2026-07-01", "2026-07-02"]
    assert sum(d["total"] for d in daily.values()) == summary["total"]
    assert sum(d["responses"] for d in daily.values()) == summary["responses"]


def test_events_respect_since_until(claude_log):
    _, events = _claude_scan_files([claude_log])
    cutoff = datetime(2026, 7, 2, tzinfo=timezone.utc)

    assert len(_filter_events(events, cutoff, None)) == 1
    assert len(_filter_events(events, None, cutoff)) == 1
    assert len(_filter_events(events, None, None)) == 2


def test_empty_input_summarizes_to_zeroes():
    summary = summarize_tokens([])
    assert summary["total"] == 0
    assert summary["responses"] == 0
    assert summary["by_model"] == []


@pytest.mark.parametrize("value,expected", [
    (0, "0"), (999, "999"), (1000, "1.0k"), (21_652_373, "21.7M"),
    (801_368_199, "801.4M"), (1_500_000_000, "1.5B"),
])
def test_fmt_tokens(value, expected):
    assert fmt_tokens(value) == expected


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
