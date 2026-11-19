"""Tests for mapping Claude log folders to and from project paths.

Claude Code names each project's log folder by replacing every character that
is not an ASCII letter or digit with `-`. That encoding is lossy, so the real
path has to come from the `cwd` the records carry, not from decoding the name.
"""

import json

import pytest

import clockwork_cli
from clockwork_cli import path_to_claude_folder, _claude_encode_path


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def user(ts, cwd):
    return {"type": "user", "timestamp": ts, "cwd": cwd}


@pytest.mark.parametrize("path, folder", [
    ("/Users/you/dev/team-5", "-Users-you-dev-team-5"),
    ("/Users/you/I2DL/exercise_01", "-Users-you-I2DL-exercise-01"),
    ("/Users/you/OneDrive/SEBA/Team 5", "-Users-you-OneDrive-SEBA-Team-5"),
    ("/Users/you/GoogleDrive-me@gmail.com/My Drive",
     "-Users-you-GoogleDrive-me-gmail-com-My-Drive"),
])
def test_encoding_matches_claude_code(path, folder):
    assert _claude_encode_path(path) == folder
    assert path_to_claude_folder(path) == folder[1:]


@pytest.fixture
def claude_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(clockwork_cli, "CLAUDE_DIR", str(tmp_path))
    return tmp_path


def test_scan_labels_projects_with_their_real_cwd(claude_dir):
    folder = claude_dir / "-Users-you-dev-team-5"
    write_jsonl(folder / "s1.jsonl", [
        # A session that later cd's elsewhere records the new cwd; the label
        # must still be the one that encodes to this folder.
        user("2026-07-01T10:00:00.000Z", "/Users/you/dev/team-5"),
        user("2026-07-01T10:05:00.000Z", "/Users/you/dev/team-5/Backend"),
    ])
    (claude_dir / ".DS_Store").write_text("")

    labels = [label for label, _, _, _ in clockwork_cli.claude_scan()]
    assert labels == ["/Users/you/dev/team-5"]


def test_scan_falls_back_to_decoded_name_without_a_matching_cwd(claude_dir):
    write_jsonl(claude_dir / "-Users-you-old" / "s1.jsonl", [
        {"type": "user", "timestamp": "2026-07-01T10:00:00.000Z"},
    ])
    labels = [label for label, _, _, _ in clockwork_cli.claude_scan()]
    assert labels == ["/Users/you/old"]


def test_scan_reads_subagent_logs_for_tokens(claude_dir):
    folder = claude_dir / "-Users-you-alpha"
    write_jsonl(folder / "sess.jsonl", [
        user("2026-07-01T10:00:00.000Z", "/Users/you/alpha"),
    ])
    write_jsonl(folder / "sess" / "subagents" / "agent-1.jsonl", [
        {"type": "assistant", "timestamp": "2026-07-01T10:01:00.000Z",
         "message": {"id": "msg_s", "model": "claude-haiku-5",
                     "usage": {"input_tokens": 1, "output_tokens": 9}}},
    ])
    [(label, ts, events, _)] = clockwork_cli.claude_scan()
    assert label == "/Users/you/alpha"
    assert len(ts) == 1
    assert [e["model"] for e in events] == ["claude-haiku-5"]


def test_single_project_path_with_special_characters_resolves(claude_dir):
    write_jsonl(claude_dir / "-Users-you-I2DL-exercise-01" / "s1.jsonl", [
        user("2026-07-01T10:00:00.000Z", "/Users/you/I2DL/exercise_01"),
    ])
    folder, count, ts, _, _ = clockwork_cli.claude_scan_single(
        "/Users/you/I2DL/exercise_01")
    assert folder == "-Users-you-I2DL-exercise-01"
    assert count == 1 and len(ts) == 1
