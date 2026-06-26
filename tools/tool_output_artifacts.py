"""Helpers for keeping large tool output out of model history.

Raw output is evidence, not working memory.  When a tool returns a large
stdout/stderr blob, keep the full redacted text as a local artifact and send
the model a bounded head/tail receipt with a pointer back to the evidence.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _artifact_root() -> Path:
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home())
    except Exception:
        home = Path.home() / ".hermes"
    return home / "artifacts" / "tool-output"


def _safe_label(label: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in label)
    cleaned = cleaned.strip("-_").lower()
    return cleaned[:40] or "tool-output"


def compact_output_with_artifact(
    output: str,
    *,
    max_chars: int,
    label: str,
    task_id: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Return bounded output and optional artifact metadata.

    ``output`` must already be safe for persistence (ANSI-stripped and
    redacted).  The returned text keeps a small head/tail window and a receipt
    that tells the model where the full local evidence lives.
    """

    if not output or len(output) <= max_chars:
        return output, None

    max_chars = max(1_000, int(max_chars or 1_000))
    encoded = output.encode("utf-8", errors="replace")
    digest = hashlib.sha256(encoded).hexdigest()
    day = time.strftime("%Y%m%d")
    created = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    label_part = _safe_label(label)
    root = _artifact_root() / day
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{created}-{label_part}-{digest[:12]}.txt"
    path.write_text(output, encoding="utf-8")

    artifact = {
        "path": str(path),
        "sha256": digest,
        "chars": len(output),
        "bytes": len(encoded),
        "truncated_to_chars": max_chars,
    }
    if task_id:
        artifact["task_id"] = task_id

    note = (
        "\n\n... [OUTPUT COMPACTED - "
        f"{len(output) - max_chars:,} chars omitted from model history; "
        f"full redacted output saved at {path} sha256:{digest[:12]}] ...\n\n"
    )
    head_chars = max(1, int(max_chars * 0.4))
    tail_chars = max(1, max_chars - head_chars)
    compact = output[:head_chars] + note + output[-tail_chars:]
    return compact, artifact
