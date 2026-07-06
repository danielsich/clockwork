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
               since=None, until=None):
    """Stub the provider backends, run an export, return the parsed JSON."""
    monkeypatch.setitem(PROVIDERS["claude"], "all", lambda: list(claude or []))
    monkeypatch.setitem(PROVIDERS["codex"], "all", lambda: list(codex or []))
    export_data(provider, idle, since, until, detail, anonymize)
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

    assert data["schema"] == "clockwork/v2"
    assert data["provider"] == "claude"
    assert data["providers"] == ["claude"]
    assert len(data["projects"]) == 1
    assert data["projects"][0]["provider"] == "claude"
    assert data["projects"][0]["path"] == CLAUDE_PROJ[0]
    assert set(data["totals"]["by_provider"]) == {"claude"}


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


def test_both_with_only_one_provider_present_keeps_single_name(monkeypatch, capsys):
    # Requested `both`, but only claude has activity.
    data = run_export(monkeypatch, capsys, "both", claude=[CLAUDE_PROJ], codex=[])
    assert data["provider"] == "claude"
    assert data["providers"] == ["claude"]
    assert set(data["totals"]["by_provider"]) == {"claude"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
