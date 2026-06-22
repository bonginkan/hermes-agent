import sys
from types import SimpleNamespace

import pytest

from gateway import run


def _discord_source():
    return SimpleNamespace(platform=SimpleNamespace(value="discord"))


@pytest.mark.asyncio
async def test_kabosu_harness_mode_runs_for_explicit_discord_request(tmp_path, monkeypatch):
    script = tmp_path / "harness_mode.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({'enabled': True, 'content': 'HARNESS CONTEXT'}))\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("KABOSU_HARNESS_MODE_NODE", sys.executable)
    monkeypatch.setenv("KABOSU_HARNESS_MODE_SCRIPT", str(script))
    monkeypatch.setenv("KABOSU_HARNESS_MODE_DIR", str(tmp_path))
    monkeypatch.setenv("KABOSU_HARNESS_MODE_CWD", str(tmp_path))

    content = await run._build_kabosu_harness_mode_context(
        "harness-initで実装して",
        _discord_source(),
    )

    assert content == "HARNESS CONTEXT"


@pytest.mark.asyncio
async def test_kabosu_harness_mode_skips_non_trigger(monkeypatch):
    monkeypatch.setenv("KABOSU_HARNESS_MODE_SCRIPT", "/missing/kabosu-harness-mode.mjs")

    content = await run._build_kabosu_harness_mode_context(
        "普通に実装して",
        _discord_source(),
    )

    assert content is None


@pytest.mark.asyncio
async def test_kabosu_harness_mode_skips_non_discord(monkeypatch):
    monkeypatch.setenv("KABOSU_HARNESS_MODE_SCRIPT", "/missing/kabosu-harness-mode.mjs")

    content = await run._build_kabosu_harness_mode_context(
        "harness-initで実装して",
        SimpleNamespace(platform=SimpleNamespace(value="telegram")),
    )

    assert content is None


def test_kabosu_harness_mode_append_keeps_original_request():
    message = run._append_kabosu_harness_mode_context(
        "harness-initで実装して",
        "HARNESS CONTEXT",
    )

    assert "harness-initで実装して" in message
    assert "HARNESS CONTEXT" in message
