"""Receipt and state-card helpers for agent tool results.

Raw output is evidence.  Receipts are the durable facts extracted from that
evidence.  The state card is the current working projection built from recent
receipts and injected into model input at request time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

RECEIPT_VERSION = 1
STATE_CARD_SCHEMA_VERSION = 1
MAX_RECENT_RECEIPTS = 16
MAX_CONTEXT_RECEIPTS = 8
MAX_SUMMARY_CHARS = 700
MAX_CONTEXT_CHARS = 6_000

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

_PERSISTED_PATH_RE = re.compile(r"Full output saved to:\s*(?P<path>\S+)")
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization)\s*[:=]\s*([^\s'\";,]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{12,}")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path.home() / ".hermes"


def _state_root() -> Path:
    return _hermes_home() / "task-state"


def _safe_label(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value)
    cleaned = "-".join(part for part in cleaned.strip("-_").lower().split("-") if part)
    return cleaned[:48] or "task"


def _task_key(*, task_id: Optional[str], session_id: Optional[str]) -> str:
    raw = (session_id or task_id or "default").strip() or "default"
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{_safe_label(raw)}-{digest}"


def _receipt_id(tool_name: str, tool_call_id: str, result_sha: str) -> str:
    if tool_call_id:
        base = f"{tool_name}-{tool_call_id}-{result_sha[:12]}"
    else:
        base = f"{tool_name}-{time.time_ns()}-{result_sha[:12]}"
    return _safe_label(base)


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{threading.get_ident()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.debug("Could not read task-state json %s: %s", path, exc)
        return None


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _sanitize_text(text: str) -> str:
    text = _SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _OPENAI_KEY_RE.sub("sk-[REDACTED]", text)
    return text


def _compact_line(text: Any, *, limit: int = MAX_SUMMARY_CHARS) -> str:
    if text is None:
        return ""
    value = _sanitize_text(str(text)).replace("\r", "\n")
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if len(value) <= limit:
        return value
    head = max(1, int(limit * 0.7))
    tail = max(1, limit - head - 20)
    return f"{value[:head].rstrip()} ... {value[-tail:].lstrip()}"


def _iter_artifacts(parsed: Any, raw_text: str) -> Iterable[Dict[str, Any]]:
    if isinstance(parsed, dict):
        for key in ("output_artifact", "raw_result_artifact", "artifact"):
            value = parsed.get(key)
            if isinstance(value, dict):
                yield dict(value)
        artifacts = parsed.get("artifacts")
        if isinstance(artifacts, list):
            for item in artifacts:
                if isinstance(item, dict):
                    yield dict(item)

    for match in _PERSISTED_PATH_RE.finditer(raw_text):
        yield {"path": match.group("path"), "kind": "persisted_tool_result"}


def _status_from_result(parsed: Any, raw_text: str) -> str:
    if isinstance(parsed, dict):
        if parsed.get("error"):
            return "error"
        status = str(parsed.get("status", "")).lower()
        if status in {"error", "failed", "failure", "blocked"}:
            return status
        if status in {"ok", "success", "completed", "passed"}:
            return "success"
        returncode = parsed.get("returncode")
        if isinstance(returncode, int):
            return "success" if returncode == 0 else "error"
    lowered = raw_text.lower()
    if lowered.startswith("error ") or "error executing tool" in lowered:
        return "error"
    return "success"


def _args_preview(tool_name: str, args: Any) -> str:
    parsed = _parse_jsonish(args)
    if isinstance(parsed, dict):
        if tool_name in {"terminal", "execute_shell", "shell"} and parsed.get("command"):
            return f"command={_compact_line(parsed.get('command'), limit=220)}"
        for key in ("path", "file_path", "query", "pattern", "url"):
            if parsed.get(key):
                return f"{key}={_compact_line(parsed.get(key), limit=220)}"
        keys = ", ".join(sorted(str(k) for k in parsed.keys())[:8])
        return f"args_keys={keys}" if keys else ""
    return _compact_line(parsed, limit=220)


def _summary_from_result(tool_name: str, args: Any, parsed: Any, raw_text: str) -> str:
    arg_hint = _args_preview(tool_name, args)

    if isinstance(parsed, dict):
        if parsed.get("error"):
            return _compact_line(f"{arg_hint}: {parsed.get('error')}" if arg_hint else parsed.get("error"))

        parts: list[str] = []
        if arg_hint:
            parts.append(arg_hint)
        if parsed.get("returncode") is not None:
            parts.append(f"returncode={parsed.get('returncode')}")
        if parsed.get("status"):
            parts.append(f"status={parsed.get('status')}")
        if parsed.get("summary"):
            parts.append(str(parsed.get("summary")))
        elif parsed.get("message"):
            parts.append(str(parsed.get("message")))
        elif parsed.get("output"):
            parts.append(str(parsed.get("output")))
        elif parsed.get("content"):
            parts.append(str(parsed.get("content")))
        elif parsed.get("stdout"):
            parts.append(str(parsed.get("stdout")))
        elif parsed.get("stderr"):
            parts.append(str(parsed.get("stderr")))
        elif parsed:
            keys = ", ".join(sorted(str(k) for k in parsed.keys())[:10])
            parts.append(f"result_keys={keys}")
        return _compact_line("; ".join(part for part in parts if part))

    if arg_hint:
        return _compact_line(f"{arg_hint}: {raw_text}")
    return _compact_line(raw_text)


def _load_card(path: Path, *, task_key: str, task_id: str, session_id: str) -> Dict[str, Any]:
    card = _read_json(path) or {}
    if not card:
        card = {
            "schema_version": STATE_CARD_SCHEMA_VERSION,
            "task_key": task_key,
            "task_id": task_id,
            "session_id": session_id,
            "version": 0,
            "current_status": "No tool receipts recorded yet.",
            "recent_receipts": [],
            "blockers": [],
            "evidence_refs": [],
            "updated_at": None,
        }
    card.setdefault("schema_version", STATE_CARD_SCHEMA_VERSION)
    card.setdefault("task_key", task_key)
    card.setdefault("task_id", task_id)
    card.setdefault("session_id", session_id)
    card.setdefault("recent_receipts", [])
    card.setdefault("blockers", [])
    card.setdefault("evidence_refs", [])
    return card


def _update_state_card(card: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
    recent = [r for r in card.get("recent_receipts", []) if r.get("receipt_id") != receipt["receipt_id"]]
    recent.append({
        "receipt_id": receipt["receipt_id"],
        "created_at": receipt["created_at"],
        "tool_name": receipt["tool_name"],
        "status": receipt["status"],
        "summary": receipt["summary"],
        "artifacts": receipt.get("artifacts", [])[:3],
    })
    card["recent_receipts"] = recent[-MAX_RECENT_RECEIPTS:]

    artifacts = list(card.get("evidence_refs", []))
    for artifact in receipt.get("artifacts", []):
        path = artifact.get("path")
        if path and path not in artifacts:
            artifacts.append(path)
    card["evidence_refs"] = artifacts[-MAX_RECENT_RECEIPTS:]

    blockers = [b for b in card.get("blockers", []) if b.get("receipt_id") != receipt["receipt_id"]]
    if receipt["status"] in {"error", "failed", "failure", "blocked"}:
        blockers.append({
            "receipt_id": receipt["receipt_id"],
            "created_at": receipt["created_at"],
            "summary": receipt["summary"],
        })
    card["blockers"] = blockers[-8:]

    status_word = "failed" if receipt["status"] in {"error", "failed", "failure", "blocked"} else "completed"
    card["current_status"] = (
        f"Latest receipt: {receipt['tool_name']} {status_word}; {receipt['summary']}"
    )
    card["version"] = int(card.get("version") or 0) + 1
    card["updated_at"] = receipt["created_at"]
    card["task_id"] = receipt.get("task_id", card.get("task_id", ""))
    card["session_id"] = receipt.get("session_id", card.get("session_id", ""))
    return card


def record_tool_receipt(
    *,
    tool_name: str,
    args: Any,
    result: Any,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    turn_id: str = "",
    duration_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist a versioned receipt and update the task-state projection."""

    task_key = _task_key(task_id=task_id, session_id=session_id)
    raw_text = result if isinstance(result, str) else _stable_json(result)
    raw_text = raw_text or ""
    parsed = _parse_jsonish(result)
    result_sha = hashlib.sha256(raw_text.encode("utf-8", errors="replace")).hexdigest()
    args_sha = hashlib.sha256(_stable_json(args).encode("utf-8", errors="replace")).hexdigest()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    receipt_id = _receipt_id(tool_name, tool_call_id, result_sha)

    artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for artifact in _iter_artifacts(parsed, raw_text):
        path = str(artifact.get("path") or "")
        if path in seen_paths:
            continue
        if path:
            seen_paths.add(path)
        artifacts.append(artifact)

    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "receipt_id": receipt_id,
        "created_at": now,
        "task_key": task_key,
        "task_id": task_id or "",
        "session_id": session_id or "",
        "turn_id": turn_id or "",
        "tool_call_id": tool_call_id or "",
        "tool_name": tool_name,
        "status": _status_from_result(parsed, raw_text),
        "summary": _summary_from_result(tool_name, args, parsed, raw_text),
        "args_hash": args_sha,
        "args_preview": _args_preview(tool_name, args),
        "result_sha256": result_sha,
        "result_chars": len(raw_text),
        "duration_ms": duration_ms,
        "artifacts": artifacts,
    }

    root = _state_root()
    receipt_path = root / "receipts" / task_key / f"{receipt_id}.json"
    card_path = root / "cards" / f"{task_key}.json"

    with _lock_for(task_key):
        if not receipt_path.exists():
            _atomic_write_json(receipt_path, receipt)
        card = _load_card(card_path, task_key=task_key, task_id=task_id or "", session_id=session_id or "")
        card = _update_state_card(card, receipt)
        _atomic_write_json(card_path, card)

    return receipt


def build_task_state_context(
    *,
    task_id: str = "",
    session_id: str = "",
    max_receipts: int = MAX_CONTEXT_RECEIPTS,
) -> str:
    """Return a bounded state-card block for API-call-time context injection."""

    task_key = _task_key(task_id=task_id, session_id=session_id)
    card = _read_json(_state_root() / "cards" / f"{task_key}.json")
    if not card or not card.get("recent_receipts"):
        return ""

    lines: List[str] = [
        "<task_state_card>",
        "Use this as the current working-state projection. Raw artifacts are evidence refs; read them only when needed.",
        f"task_key: {card.get('task_key', task_key)}",
        f"version: {card.get('version', 0)}",
        f"updated_at: {card.get('updated_at') or ''}",
        f"current_status: {_compact_line(card.get('current_status', ''), limit=900)}",
    ]

    blockers = card.get("blockers") or []
    if blockers:
        lines.append("blockers:")
        for blocker in blockers[-4:]:
            lines.append(f"- {_compact_line(blocker.get('summary', ''), limit=500)}")

    lines.append("recent_receipts:")
    for receipt in (card.get("recent_receipts") or [])[-max(1, max_receipts):]:
        summary = _compact_line(receipt.get("summary", ""), limit=520)
        lines.append(
            f"- {receipt.get('created_at', '')} {receipt.get('tool_name', '')} "
            f"{receipt.get('status', '')}: {summary}"
        )
        artifacts = receipt.get("artifacts") or []
        for artifact in artifacts[:2]:
            path = artifact.get("path")
            if path:
                lines.append(f"  evidence_ref: {path}")

    lines.append("</task_state_card>")
    context = "\n".join(lines)
    if len(context) <= MAX_CONTEXT_CHARS:
        return context
    return context[:MAX_CONTEXT_CHARS] + "\n... [task_state_card compacted]\n</task_state_card>"


__all__ = [
    "build_task_state_context",
    "record_tool_receipt",
]
