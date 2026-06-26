"""Kabosu Discord response visibility routing."""

from types import SimpleNamespace

from gateway.config import Platform
from gateway.run import (
    _looks_like_discord_runtime_settings_request,
    _looks_like_kabosu_discord_owner_question,
    _is_kabosu_discord_simple_response_source,
    _kabosu_discord_lightweight_runtime_reply,
    _kabosu_response_visibility_context,
)


def _source(user_id: str, platform=Platform.DISCORD):
    return SimpleNamespace(platform=platform, user_id=user_id)


def test_kabosu_named_full_mode_users_keep_richer_discord_responses():
    assert not _is_kabosu_discord_simple_response_source(
        _source("473730953735438336"),
        {},
    )
    assert not _is_kabosu_discord_simple_response_source(
        _source("804646947029254185"),
        {},
    )

    context = _kabosu_response_visibility_context(
        _source("473730953735438336"),
        {},
    )

    assert "full_mode" in context
    assert "Richer reasoning" in context
    assert "Remove repeated meaning" in context


def test_kabosu_other_discord_users_get_simple_dense_responses():
    assert _is_kabosu_discord_simple_response_source(
        _source("999999999999999999"),
        {},
    )

    context = _kabosu_response_visibility_context(
        _source("999999999999999999"),
        {},
    )

    assert "simple_mode" in context
    assert "about 500 characters" in context
    assert "Every sentence must add one new useful fact" in context
    assert "Do not mention commands, tools, files, tests, logs" in context


def test_kabosu_visibility_is_discord_only():
    assert not _is_kabosu_discord_simple_response_source(
        _source("999999999999999999", platform=Platform.TELEGRAM),
        {},
    )
    assert _kabosu_response_visibility_context(
        _source("999999999999999999", platform=Platform.TELEGRAM),
        {},
    ) == ""


def test_kabosu_full_mode_allowlist_can_come_from_config():
    config = {"kabosu": {"discord": {"full_response_user_ids": ["custom-user"]}}}

    assert not _is_kabosu_discord_simple_response_source(
        _source("custom-user"),
        config,
    )
    assert _is_kabosu_discord_simple_response_source(
        _source("473730953735438336"),
        config,
    )


def test_kabosu_lightweight_reply_reports_owner_and_codex_native_compaction(monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_SETTINGS_OWNER_IDS", "owner-user")
    config = {
        "model": {
            "default": "gpt-5.5",
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
        },
        "compression": {
            "enabled": True,
            "codex_native_first": True,
            "overflow_fallback_max_attempts": "auto",
        },
    }

    reply = _kabosu_discord_lightweight_runtime_reply(
        _source("owner-user"),
        "この処理は実装した。正しく実装されているか自分でも確認して。あと、ownerは誰なの？",
        config,
    )

    assert reply is not None
    assert "軽量確認レーン" not in reply
    assert "巨大スレッド履歴" not in reply
    assert "owner は owner-user" in reply
    assert "owner 扱いでOK" in reply
    assert "openai-codex / gpt-5.5" in reply
    assert "Codex native compaction は 有効" in reply
    assert "Codex経路では1回" in reply


def test_kabosu_lightweight_reply_reports_non_owner(monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_SETTINGS_OWNER_IDS", "owner-user")

    reply = _kabosu_discord_lightweight_runtime_reply(
        _source("other-user"),
        "ownerは誰なの？",
        {},
    )

    assert reply is not None
    assert "owner は owner-user" in reply
    assert "other-user は owner と一致してない" in reply


def test_kabosu_lightweight_reply_catches_stuck_runtime_check():
    reply = _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        "また処理が終わらない。同じスレッドで内容を確認させてるだけなんだけど、何で詰まってる？？？",
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    )

    assert reply is not None
    assert "軽量確認レーン" not in reply
    assert "openai-codex / gpt-5.5" in reply


def test_kabosu_owner_reflection_is_not_treated_as_owner_check():
    text = "ownerの性格と、自分自身の性格って似通ってると思う？"

    assert not _looks_like_kabosu_discord_owner_question(text)
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        text,
        {},
    ) is None


def test_kabosu_runtime_settings_discussion_is_not_block_request():
    assert not _looks_like_discord_runtime_settings_request(
        "MISA 3 側でも、他エージェントの runtime owner 設定をこっちの Jun 判定で上書きしない。"
    )
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        "MISA 3 側でも、他エージェントの runtime owner 設定をこっちの Jun 判定で上書きしない。",
        {},
    ) is None
    assert not _looks_like_discord_runtime_settings_request(
        "カボス側 runtime owner について、カボス自身の一次設定変更が出た場合だけ再評価する。"
    )
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        "カボス側 runtime owner について、カボス自身の一次設定変更が出た場合だけ再評価する。",
        {},
    ) is None
    assert _looks_like_discord_runtime_settings_request(
        "カボス本体のruntime設定を変更して"
    )


def test_kabosu_lightweight_reply_ignores_normal_work_requests():
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        "実装して",
        {},
    ) is None


def test_kabosu_lightweight_reply_is_discord_only():
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336", platform=Platform.TELEGRAM),
        "ownerは誰なの？",
        {},
    ) is None
