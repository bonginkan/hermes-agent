from __future__ import annotations

import json
from pathlib import Path


def test_record_tool_receipt_updates_state_card_and_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools.tool_receipts import build_task_state_context, record_tool_receipt

    evidence = tmp_path / "artifacts" / "tool-output" / "full.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("full redacted output", encoding="utf-8")

    result = json.dumps({
        "returncode": 1,
        "output": "CacheInvalidationTest failed",
        "output_artifact": {
            "path": str(evidence),
            "sha256": "abc123",
            "chars": 50_000,
        },
    })

    receipt = record_tool_receipt(
        tool_name="terminal",
        args={"command": "npm test TOKEN=super-secret-value"},
        result=result,
        task_id="task-1",
        session_id="session-1",
        tool_call_id="call-1",
        turn_id="turn-1",
        duration_ms=42,
    )

    assert receipt["status"] == "error"
    assert "super-secret-value" not in receipt["args_preview"]
    assert receipt["artifacts"][0]["path"] == str(evidence)

    cards = list((tmp_path / "task-state" / "cards").glob("*.json"))
    assert len(cards) == 1
    card = json.loads(cards[0].read_text(encoding="utf-8"))
    assert card["version"] == 1
    assert card["recent_receipts"][0]["receipt_id"] == receipt["receipt_id"]

    context = build_task_state_context(task_id="task-1", session_id="session-1")
    assert "<task_state_card>" in context
    assert "CacheInvalidationTest failed" in context
    assert str(evidence) in context
    assert "super-secret-value" not in context


def test_record_tool_receipt_is_idempotent_for_same_call_and_result(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools.tool_receipts import record_tool_receipt

    kwargs = {
        "tool_name": "read_file",
        "args": {"path": "/tmp/app.py"},
        "result": json.dumps({"status": "success", "content": "def main(): pass"}),
        "task_id": "task-2",
        "session_id": "session-2",
        "tool_call_id": "call-2",
        "turn_id": "turn-2",
    }

    first = record_tool_receipt(**kwargs)
    second = record_tool_receipt(**kwargs)

    assert first["receipt_id"] == second["receipt_id"]
    cards = list((tmp_path / "task-state" / "cards").glob("*.json"))
    card = json.loads(cards[0].read_text(encoding="utf-8"))
    assert card["version"] == 2
    assert [r["receipt_id"] for r in card["recent_receipts"]] == [first["receipt_id"]]


def test_persisted_output_path_is_promoted_as_evidence_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools.tool_receipts import build_task_state_context, record_tool_receipt

    persisted_path = "/tmp/hermes-results/call-3.txt"
    result = (
        "<persisted-output>\n"
        "This tool result was too large.\n"
        f"Full output saved to: {persisted_path}\n"
        "Preview:\n"
        "first failure line\n"
        "</persisted-output>"
    )

    receipt = record_tool_receipt(
        tool_name="search_files",
        args={"pattern": "CacheInvalidationTest"},
        result=result,
        task_id="task-3",
        session_id="session-3",
        tool_call_id="call-3",
    )

    assert receipt["artifacts"] == [{"path": persisted_path, "kind": "persisted_tool_result"}]
    context = build_task_state_context(task_id="task-3", session_id="session-3")
    assert persisted_path in context
    assert "first failure line" in context
