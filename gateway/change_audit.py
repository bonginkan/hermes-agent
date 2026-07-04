"""Lightweight audit trail for Discord-originated configuration/code changes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_USER_ID = "473730953735438336"
MAX_TEXT_CHARS = 4000


def _target_user_ids() -> set[str]:
    raw = os.environ.get("HERMES_DISCORD_AUDIT_USER_IDS", DEFAULT_AUDIT_USER_ID)
    return {part.strip() for part in raw.split(",") if part.strip()}


def should_audit_discord_user(user_id: Any) -> bool:
    return str(user_id or "").strip() in _target_user_ids()


def _run_git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _file_hash(path: Path) -> dict[str, Any] | None:
    try:
        data = path.read_bytes()
        stat = path.stat()
    except Exception:
        return None
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _hermes_repo_state(hermes_home: Path) -> dict[str, Any]:
    repo = hermes_home / "hermes-agent"
    state: dict[str, Any] = {"repo": str(repo)}
    if not (repo / ".git").exists():
        state["available"] = False
        return state
    state["available"] = True
    state["head"] = _run_git(repo, "rev-parse", "HEAD")
    state["branch"] = _run_git(repo, "branch", "--show-current")
    status = _run_git(repo, "status", "--porcelain")
    state["dirty_files"] = status.splitlines() if status else []
    return state


def record_discord_audit_event(
    *,
    hermes_home: Path,
    event: Any,
    message_preview: str,
    reply_to_text: str,
) -> None:
    source = getattr(event, "source", None)
    if not source or not should_audit_discord_user(getattr(source, "user_id", None)):
        return

    audit_dir = Path(os.environ.get("HERMES_DISCORD_AUDIT_DIR") or hermes_home / "audit")
    audit_dir.mkdir(parents=True, exist_ok=True)
    user_id = str(getattr(source, "user_id", "") or "unknown")
    audit_path = audit_dir / f"discord-user-{user_id}.jsonl"

    record = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "kind": "discord_inbound",
        "source": {
            "platform": getattr(getattr(source, "platform", None), "value", str(getattr(source, "platform", ""))),
            "user_id": user_id,
            "user_name": getattr(source, "user_name", None),
            "chat_id": getattr(source, "chat_id", None),
            "chat_name": getattr(source, "chat_name", None),
            "chat_type": getattr(source, "chat_type", None),
            "thread_id": getattr(source, "thread_id", None),
            "guild_id": getattr(source, "guild_id", None),
            "message_id": getattr(source, "message_id", None) or getattr(event, "message_id", None),
        },
        "message": {
            "text": str(getattr(event, "text", "") or "")[:MAX_TEXT_CHARS],
            "preview": message_preview,
            "reply_to_message_id": getattr(event, "reply_to_message_id", None),
            "reply_to_text": reply_to_text,
        },
        "state": {
            "hermes_agent": _hermes_repo_state(hermes_home),
            "config": _file_hash(hermes_home / "config.yaml"),
            "soul": _file_hash(hermes_home / "SOUL.md"),
            "env": _file_hash(hermes_home / ".env"),
        },
    }

    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def record_discord_intake_route(
    *,
    hermes_home: Path,
    event: Any,
    message_preview: str,
    route: dict[str, Any],
) -> None:
    """Record Kabosu's internal intake-route decision for later replay/judging."""
    source = getattr(event, "source", None)
    if not source or not should_audit_discord_user(getattr(source, "user_id", None)):
        return

    audit_dir = Path(os.environ.get("HERMES_DISCORD_AUDIT_DIR") or hermes_home / "audit")
    audit_dir.mkdir(parents=True, exist_ok=True)
    user_id = str(getattr(source, "user_id", "") or "unknown")
    audit_path = audit_dir / f"discord-user-{user_id}.jsonl"
    raw_text = str(getattr(event, "text", "") or "")

    record = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "kind": "discord_intake_route",
        "source": {
            "platform": getattr(getattr(source, "platform", None), "value", str(getattr(source, "platform", ""))),
            "user_id": user_id,
            "chat_id": getattr(source, "chat_id", None),
            "chat_type": getattr(source, "chat_type", None),
            "thread_id": getattr(source, "thread_id", None),
            "message_id": getattr(source, "message_id", None) or getattr(event, "message_id", None),
        },
        "message": {
            "sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "preview": message_preview[:MAX_TEXT_CHARS],
        },
        "route": route,
    }

    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
