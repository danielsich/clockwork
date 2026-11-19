"""Tests for the clockwork/v2 combined-provider export bundle.

These exercise ``export_data`` directly, stubbing each provider's ``all``
backend with fixed (path, timestamps) data so no real ~/.claude or ~/.codex
files are needed. Stdout is pure JSON (the receipt goes to stderr), so the
captured stdout parses back with ``json.loads``.
"""

import json
from datetime import datetime, timezone

import pytest

from clockwork_cli import PROVIDERS, export_data, _project_id


def _ts(*parts):
    """Build a UTC-aware datetime from (year, month, day, hour, minute)."""
    return datetime(*parts, tzinfo=timezone.utc)


def run_export(monkeypatch, capsys, provider, claude=None, codex=None,
               *, idle=30, detail="raw", anonymize=False,
               since=None, until=None, tokens=False):
    """Stub the provider backends, run an export, return the parsed JSON.

    Both the timing-only (`all`) and token-aware (`scan`) backends are stubbed,
    so the same fixtures drive an export with or without --tokens. Fixtures may
    be (path, timestamps) pairs, (path, timestamps, token events) triples, or
    (path, timestamps, token events, human timestamps). Without the fourth
    element every timestamp is treated as a human prompt.
    """
    def split(projects):
        rows = []
        for p in projects or []:
            events = p[2] if len(p) > 2 else []
            human = p[3] if len(p) > 3 else p[1]
            rows.append((p[0], p[1], events, human))
        return ([(label, ts, human) for label, ts, _, human in rows], rows)

    claude_all, claude_scan = split(claude)
    codex_all, codex_scan = split(codex)
    monkeypatch.setitem(PROVIDERS["claude"], "all", lambda: list(claude_all))
    monkeypatch.setitem(PROVIDERS["claude"], "scan", lambda: list(claude_scan))
    monkeypatch.setitem(PROVIDERS["codex"], "all", lambda: list(codex_all))
    monkeypatch.setitem(PROVIDERS["codex"], "scan", lambda: list(codex_scan))
    export_data(provider, idle, since, until, detail, anonymize, tokens)
    out = capsys.readouterr().out
    return json.loads(out)


# A couple of prompts on two different days for a project.
CLAUDE_PROJ = ("/Users/you/dev/alpha", [_ts(2026, 7, 1, 10, 0),
                                         _ts(2026, 7, 1, 10, 20),
                                         _ts(2026, 7, 2, 9, 0)])
CODEX_PROJ = ("/Users/you/dev/beta", [_ts(2026, 7, 3, 14, 0),
                                       _ts(2026, 7, 3, 14, 15)])


def test_single_provider_shape_is_backward_compatible(monkeypatch, capsys):
    data = run_export(monkeypatch, capsys, "claude", claude=[CLAUDE_PROJ])

    assert data["schema"] == "clockwork/v3"
    assert data["provider"] == "claude"
    assert data["providers"] == ["claude"]
    assert len(data["projects"]) == 1
    assert data["projects"][0]["provider"] == "claude"
    assert data["projects"][0]["path"] == CLAUDE_PROJ[0]
    assert set(data["totals"]["by_provider"]) == {"claude"}
    # Without --tokens the bundle carries no token fields at all.
    assert data["tokens"] is False
    assert "tokens" not in data["totals"]
    assert all("tokens" not in p for p in data["projects"])
    assert all("tokens" not in d for p in data["projects"] for d in p["daily"])


def test_both_provider_export(monkeypatch, capsys):
    data = run_export(monkeypatch, capsys, "both",
                      claude=[CLAUDE_PROJ], codex=[CODEX_PROJ])

    assert data["provider"] == "both"
    assert data["providers"] == ["claude", "codex"]

    providers_seen = {p["provider"] for p in data["projects"]}
    assert providers_seen == {"claude", "codex"}
    # Every project entry is attributed to exactly one provider.
    assert all(p["provider"] in ("claude", "codex") for p in data["projects"])
    assert set(data["totals"]["by_provider"]) == {"claude", "codex"}


def test_same_path_two_providers_yields_two_entries(monkeypatch, capsys):
    shared = "/Users/you/dev/shared"
    claude = [(shared, [_ts(2026, 7, 1, 10, 0), _ts(2026, 7, 1, 10, 30)])]
    codex = [(shared, [_ts(2026, 7, 2, 11, 0)])]

    data = run_export(monkeypatch, capsys, "both", claude=claude, codex=codex)

    entries = [p for p in data["projects"] if p["path"] == shared]
    assert len(entries) == 2
    assert {e["provider"] for e in entries} == {"claude", "codex"}
    # Distinct, provider-scoped ids for the same path.
    assert entries[0]["id"] != entries[1]["id"]
    assert data["totals"]["projects"] == 2


def test_by_provider_totals_sum_to_grand(monkeypatch, capsys):
    data = run_export(monkeypatch, capsys, "both",
                      claude=[CLAUDE_PROJ], codex=[CODEX_PROJ])

    by = data["totals"]["by_provider"]
    grand = data["totals"]

    assert by["claude"]["projects"] + by["codex"]["projects"] == grand["projects"]
    assert by["claude"]["prompts"] + by["codex"]["prompts"] == grand["prompts"]
    assert by["claude"]["sessions"] + by["codex"]["sessions"] == grand["sessions"]
    assert (round(by["claude"]["minutes"] + by["codex"]["minutes"], 2)
            == grand["minutes"])

    # Claude side: 3 prompts, two active days.
    assert by["claude"]["prompts"] == 3
    assert by["codex"]["prompts"] == 2


def test_id_is_provider_path_hash_and_stable_under_anonymize(monkeypatch, capsys):
    plain = run_export(monkeypatch, capsys, "both",
                       claude=[CLAUDE_PROJ], codex=[CODEX_PROJ])
    anon = run_export(monkeypatch, capsys, "both",
                      claude=[CLAUDE_PROJ], codex=[CODEX_PROJ], anonymize=True)

    def ids_by_provider(bundle):
        return {p["provider"]: p["id"] for p in bundle["projects"]}

    assert ids_by_provider(plain) == ids_by_provider(anon)
    # The id is the documented sha1(provider + "\0" + path) prefix.
    assert ids_by_provider(plain)["claude"] == _project_id("claude", CLAUDE_PROJ[0])
    assert ids_by_provider(plain)["codex"] == _project_id("codex", CODEX_PROJ[0])

    # Anonymized output drops the path and renames projects.
    assert all("path" not in p for p in anon["projects"])
    assert all(p["name"].startswith("project-") for p in anon["projects"])


def test_provider_filtering(monkeypatch, capsys):
    claude_only = run_export(monkeypatch, capsys, "claude",
                             claude=[CLAUDE_PROJ], codex=[CODEX_PROJ])
    assert claude_only["providers"] == ["claude"]
    assert {p["provider"] for p in claude_only["projects"]} == {"claude"}
    assert "codex" not in claude_only["totals"]["by_provider"]

    codex_only = run_export(monkeypatch, capsys, "codex",
                            claude=[CLAUDE_PROJ], codex=[CODEX_PROJ])
    assert codex_only["providers"] == ["codex"]
    assert {p["provider"] for p in codex_only["projects"]} == {"codex"}
    assert "claude" not in codex_only["totals"]["by_provider"]


def _event(ts, model, **counts):
    """A normalized token event, as the provider backends emit them."""
    event = {"ts": ts, "model": model, "input": 0, "output": 0,
             "cache_read": 0, "cache_write": 0, "reasoning": 0}
    event.update(counts)
    return event


CLAUDE_WITH_TOKENS = CLAUDE_PROJ + ([
    _event(_ts(2026, 7, 1, 10, 1), "claude-opus-5",
           input=5, output=100, cache_read=1000, cache_write=200),
    _event(_ts(2026, 7, 2, 9, 1), "claude-sonnet-5",
           input=7, output=50, cache_read=2000),
],)
CODEX_WITH_TOKENS = CODEX_PROJ + ([
    _event(_ts(2026, 7, 3, 14, 1), "gpt-5.6-sol",
           input=60, output=10, cache_read=40, reasoning=4),
],)


def test_tokens_are_opt_in_and_reconcile(monkeypatch, capsys):
    data = run_export(monkeypatch, capsys, "both",
                      claude=[CLAUDE_WITH_TOKENS], codex=[CODEX_WITH_TOKENS],
                      tokens=True)

    assert data["schema"] == "clockwork/v3"
    assert data["tokens"] is True

    grand = data["totals"]["tokens"]
    assert grand["responses"] == 3
    assert grand["total"] == sum(p["tokens"]["total"] for p in data["projects"])

    by = data["totals"]["by_provider"]
    assert (by["claude"]["tokens"]["total"] + by["codex"]["tokens"]["total"]
            == grand["total"])
    # total is the four counted fields; reasoning is a subset of output.
    assert grand["total"] == (grand["input"] + grand["output"]
                              + grand["cache_read"] + grand["cache_write"])
    assert grand["reasoning"] == 4


def test_per_day_tokens_sum_to_the_project_total(monkeypatch, capsys):
    data = run_export(monkeypatch, capsys, "claude",
                      claude=[CLAUDE_WITH_TOKENS], tokens=True)

    project = data["projects"][0]
    assert sum(d["tokens"]["total"] for d in project["daily"]) == project["tokens"]["total"]
    assert [d["date"] for d in project["daily"]] == ["2026-07-01", "2026-07-02"]


def test_tokens_carry_a_per_model_breakdown(monkeypatch, capsys):
    data = run_export(monkeypatch, capsys, "both",
                      claude=[CLAUDE_WITH_TOKENS], codex=[CODEX_WITH_TOKENS],
                      tokens=True)

    models = {m["model"] for m in data["totals"]["tokens"]["by_model"]}
    assert models == {"claude-opus-5", "claude-sonnet-5", "gpt-5.6-sol"}
    # Each project only reports the models it actually used.
    codex_project = next(p for p in data["projects"] if p["provider"] == "codex")
    assert [m["model"] for m in codex_project["tokens"]["by_model"]] == ["gpt-5.6-sol"]


def test_tokens_honour_the_date_window(monkeypatch, capsys):
    data = run_export(monkeypatch, capsys, "claude", claude=[CLAUDE_WITH_TOKENS],
                      tokens=True, since=_ts(2026, 7, 2, 0, 0))

    tokens = data["projects"][0]["tokens"]
    assert tokens["responses"] == 1
    assert [m["model"] for m in tokens["by_model"]] == ["claude-sonnet-5"]


def test_both_with_only_one_provider_present_keeps_single_name(monkeypatch, capsys):
    # Requested `both`, but only claude has activity.
    data = run_export(monkeypatch, capsys, "both", claude=[CLAUDE_PROJ], codex=[])
    assert data["provider"] == "claude"
    assert data["providers"] == ["claude"]
    assert set(data["totals"]["by_provider"]) == {"claude"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
