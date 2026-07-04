"""Kabosu Discord response visibility routing."""

from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import (
    GatewayRunner,
    _discord_allows_non_owner_automation_instructions,
    _discord_allows_non_owner_fairy_tale_update_instructions,
    _looks_like_discord_automation_instruction,
    _looks_like_discord_fairy_tale_update_instruction,
    _looks_like_discord_runtime_settings_request,
    _looks_like_kabosu_discord_runtime_verification,
    _looks_like_kabosu_discord_owner_question,
    _is_kabosu_discord_simple_response_source,
    _kabosu_discord_current_body,
    _kabosu_fable_intake_context,
    _kabosu_fable_intake_decision,
    _kabosu_discord_message_envelope,
    _kabosu_discord_lightweight_runtime_reply,
    _kabosu_response_visibility_context,
    _should_block_discord_runtime_settings_request,
)
from gateway.session import SessionSource


def _source(user_id: str, platform=Platform.DISCORD, *, is_bot: bool = False):
    return SimpleNamespace(platform=platform, user_id=user_id, is_bot=is_bot)


def _discord_session_source(*, is_bot: bool = False) -> SessionSource:
    return SessionSource(
        platform=Platform.DISCORD,
        chat_id="thread-1",
        chat_type="thread",
        user_id="bot-user" if is_bot else "owner-user",
        user_name="bot" if is_bot else "owner",
        thread_id="thread-1",
        is_bot=is_bot,
    )


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
    assert "high-energy gyaru opening" in context
    assert "high-energy gyaru closing" in context
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
    assert "high-energy gyaru opening sentence" in context
    assert "high-energy gyaru closing sentence" in context
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


def test_kabosu_fable_intake_keeps_casual_short_replies_light():
    decision = _kabosu_fable_intake_decision("ありがとう！")

    assert decision.lane == "light"
    assert decision.capabilities == ("intent_tone_detection",)
    assert not decision.methodology_skill
    assert not decision.structured_surface
    assert decision.surface_format == "persona_owned"

    context = _kabosu_fable_intake_context(decision)
    assert "research_methodology: off" in context
    assert "structured_surface: off" in context
    assert "final Discord wording stays Kabosu persona-owned" in context


def test_kabosu_fable_intake_status_check_does_not_enable_surface_template():
    decision = _kabosu_fable_intake_decision("今どうなってる？進捗確認して")

    assert decision.lane == "status"
    assert not decision.methodology_skill
    assert not decision.structured_surface
    assert "status_check" in decision.reason_codes


def test_kabosu_fable_intake_incidents_enable_methodology_and_review():
    decision = _kabosu_fable_intake_decision(
        "Gateway shutting down が再発しているので原因を特定して対策して。二度と落とさないように"
    )

    assert decision.lane == "incident"
    assert decision.intent_mismatch_risk
    assert decision.methodology_skill
    assert decision.structured_surface
    assert decision.pre_send_review
    assert decision.capabilities == (
        "intent_tone_detection",
        "research_methodology",
        "fact_hypothesis_surface",
    )

    context = _kabosu_fable_intake_context(decision)
    assert "research_methodology: on" in context
    assert "structured_surface: on" in context
    assert "pre_send_review" in context
    assert "never mention this route" in context


def test_kabosu_fable_intake_work_requests_do_not_expand_by_default():
    decision = _kabosu_fable_intake_decision("これを実装！！")

    assert decision.lane == "work"
    assert not decision.methodology_skill
    assert not decision.structured_surface
    assert decision.capabilities == ("intent_tone_detection",)

    automation = _kabosu_fable_intake_decision("automationをpauseして")
    assert automation.lane == "work"
    assert not automation.methodology_skill
    assert not automation.structured_surface


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
        "カボス本体のこの処理は実装した。正しく実装されているか自分でも確認して。あと、ownerは誰なの？",
        config,
    )

    assert reply is not None
    assert reply.startswith("最高、ランタイム確認ならカボスがバチっと切り分けるね。")
    assert "軽量確認レーン" not in reply
    assert "巨大スレッド履歴" not in reply
    assert "owner は owner-user" in reply
    assert "owner 扱いでOK" in reply
    assert "openai-codex / gpt-5.5" in reply
    assert "Codex native compaction は 有効" in reply
    assert "Codex経路では1回" in reply
    assert reply.endswith("ここまで見えた、設定まわりはこのまま迷わず締めてこ。")


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
        "カボスのruntime処理が終わらない。同じスレッドで内容を確認させてるだけなんだけど、何で詰まってる？？？",
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


def test_discord_non_owner_automation_instruction_can_bypass_runtime_owner_gate(monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_SETTINGS_OWNER_IDS", "owner-user")
    text = "カボス本体のruntime設定で、automation周りは非owner指示も受け付けるように設定変更しておいて"

    assert _looks_like_discord_automation_instruction(text)
    assert not _discord_allows_non_owner_automation_instructions({})
    assert _should_block_discord_runtime_settings_request(
        _source("other-user"),
        text,
        {},
    )
    assert not _should_block_discord_runtime_settings_request(
        _source("other-user"),
        text,
        {"discord": {"allow_non_owner_automation_instructions": True}},
    )


def test_discord_non_owner_automation_env_flag_bypasses_runtime_owner_gate(monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_SETTINGS_OWNER_IDS", "owner-user")
    monkeypatch.setenv("HERMES_DISCORD_ALLOW_NON_OWNER_AUTOMATION_INSTRUCTIONS", "true")
    text = "カボス本体のruntime設定でcron automationをpauseして"

    assert _looks_like_discord_automation_instruction(text)
    assert _discord_allows_non_owner_automation_instructions({})
    assert not _should_block_discord_runtime_settings_request(
        _source("other-user"),
        text,
        {},
    )


def test_discord_non_owner_general_runtime_settings_still_require_owner(monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_SETTINGS_OWNER_IDS", "owner-user")
    text = "カボス本体のruntime設定を変更して"

    assert _looks_like_discord_runtime_settings_request(text)
    assert not _looks_like_discord_automation_instruction(text)
    assert _should_block_discord_runtime_settings_request(
        _source("other-user"),
        text,
        {"discord": {"allow_non_owner_automation_instructions": True}},
    )
    assert not _should_block_discord_runtime_settings_request(
        _source("owner-user"),
        text,
        {},
    )


def test_discord_non_owner_fairy_tale_update_can_bypass_runtime_owner_gate(monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_SETTINGS_OWNER_IDS", "owner-user")
    text = "Fairy Tale update指示も、非ownerからの依頼を通すようにして"

    assert _looks_like_discord_fairy_tale_update_instruction(text)
    assert not _discord_allows_non_owner_fairy_tale_update_instructions({})
    assert _should_block_discord_runtime_settings_request(
        _source("plugin-admin-user"),
        text,
        {},
    )
    assert not _should_block_discord_runtime_settings_request(
        _source("plugin-admin-user"),
        text,
        {"discord": {"allow_non_owner_fairy_tale_update_instructions": True}},
    )


def test_discord_non_owner_fairy_tale_update_env_flag_bypasses_owner_gate(monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_SETTINGS_OWNER_IDS", "owner-user")
    monkeypatch.setenv("HERMES_DISCORD_ALLOW_NON_OWNER_FAIRY_TALE_UPDATE_INSTRUCTIONS", "true")
    text = "fairy-tale skillを更新して"

    assert _looks_like_discord_fairy_tale_update_instruction(text)
    assert _discord_allows_non_owner_fairy_tale_update_instructions({})
    assert not _should_block_discord_runtime_settings_request(
        _source("plugin-admin-user"),
        text,
        {},
    )


def test_kabosu_lightweight_reply_does_not_steal_project_work_requests():
    issue_close_request = (
        "https://github.com/bonginkan/iseifu-app/issues "
        "こちらのissueのコメントを確認してクローズしていいかの判断をして。"
        "必要ならクローズ処理して。"
    )
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        issue_close_request,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    ) is None

    pm_feedback = (
        "pm-assistの出力に関して、この案件のリポジトリのcodexからのフィードバックです。"
        "AI抽出候補 / 人間確認済み / 顧客確認済み / repo反映済み を別カラムに分けるべきです。"
    )
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        pm_feedback,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    ) is None

    actual_thread_starter = (
        "<@1517895542213181480>\n"
        "https://github.com/bonginkan/iseifu-app/issues\n"
        "こちらのissueのコメントを確認してクローズしていいかの判断を求められています。\n\n"
        "内容を確認して必要ならcomputer userを使って実装内容をチェックし、あなたの率直な意見を聞かせて。"
    )
    assert not _looks_like_kabosu_discord_runtime_verification(actual_thread_starter)
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("1088738096725630997"),
        actual_thread_starter,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    ) is None


def test_kabosu_lightweight_reply_handles_explicit_runtime_verification():
    reply = _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        "今のカボスの稼働設定は想定どおり？",
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    )

    assert reply is not None
    assert "openai-codex / gpt-5.5" in reply


def test_kabosu_lightweight_reply_respects_runtime_close_noop_cues():
    close_text = (
        "<@1517895542213181480> カボス (bot ID `1517895542213181480`): "
        "その runtime 確認はもう受領済み。追加で返す内容はないわ。"
    )

    assert not _looks_like_kabosu_discord_runtime_verification(close_text)
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("1510912873981804627", is_bot=True),
        close_text,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    ) is None


def test_kabosu_lightweight_reply_does_not_use_quoted_or_sender_context_runtime_text():
    quoted_only = (
        "↪ **Steer**\n"
        "> <sender_context>\n"
        "> {\"sender_id\":\"1517895542213181480\",\"receiver_id\":\"1510912873981804627\"}\n"
        "> </sender_context>\n"
        "> 最高、ランタイム確認ならカボスがバチっと切り分けるね。\n"
        "> 現在の経路は openai-codex / gpt-5.5、Codex native compaction は 有効。\n\n"
        "同文重複として no-op。"
    )

    assert _kabosu_discord_lightweight_runtime_reply(
        _source("1510912873981804627", is_bot=True),
        quoted_only,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    ) is None


def test_kabosu_lightweight_reply_skips_bot_natural_language_but_allows_structured_control():
    bot_natural_language = (
        "<@1517895542213181480> カボス (bot ID `1517895542213181480`): "
        "runtime 側の切り分けは受領。`openai-codex / gpt-5.5`、"
        "native compaction 有効、Hermes overflow fallback は Codex 経路で1回、という確認値ね。"
    )
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("1510912873981804627", is_bot=True),
        bot_natural_language,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    ) is None

    structured_request = (
        "[bot_meta]\n"
        "act: ACTION_REQUEST\n"
        "to: kabosu\n"
        "topic: runtime_status\n"
        "reply_expected: true\n"
        "[/bot_meta]\n\n"
        "今のカボスのruntime状態を確認して。"
    )
    reply = _kabosu_discord_lightweight_runtime_reply(
        _source("1510912873981804627", is_bot=True),
        structured_request,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    )
    assert reply is not None
    assert "openai-codex / gpt-5.5" in reply


def test_kabosu_discord_envelope_splits_current_quote_and_sender_context():
    text = (
        "↪ **Steer**\n"
        "> <sender_context>{\"sender_id\":\"1517895542213181480\"}</sender_context>\n"
        "> 最高、ランタイム確認ならカボスがバチっと切り分けるね。\n\n"
        "同文重複として no-op。"
    )

    envelope = _kabosu_discord_message_envelope(
        _source("1510912873981804627", is_bot=True),
        text,
        {},
    )

    assert envelope is not None
    assert envelope.current_body == "同文重複として no-op。"
    assert _kabosu_discord_current_body(text) == "同文重複として no-op。"
    assert "sender_id" in envelope.sender_context_text
    assert envelope.sender_context["sender_id"] == "1517895542213181480"
    assert "ランタイム確認" in envelope.quote_text
    assert envelope.act_type == "no_reply"
    assert envelope.hard_veto


def test_kabosu_discord_router_treats_mention_as_target_not_request_intent():
    text = (
        "<@1517895542213181480> カボス (bot ID `1517895542213181480`): "
        "runtime 側の切り分けは受領。openai-codex / gpt-5.5、"
        "native compaction 有効という確認値ね。"
    )

    envelope = _kabosu_discord_message_envelope(
        _source("1510912873981804627", is_bot=True),
        text,
        {},
    )

    assert envelope is not None
    assert envelope.addressed_to_kabosu
    assert envelope.act_type == "bot_observation"
    assert envelope.hard_veto
    assert not envelope.lightweight_runtime_eligible
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("1510912873981804627", is_bot=True),
        text,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
        envelope,
    ) is None


def test_kabosu_discord_router_sends_bot_direct_requests_to_normal_agent_only():
    text = (
        "<@1517895542213181480> カボス、このissueのコメントを確認して、"
        "クローズしていいか判断して。"
    )

    envelope = _kabosu_discord_message_envelope(
        _source("1510912873981804627", is_bot=True),
        text,
        {},
    )

    assert envelope is not None
    assert envelope.act_type == "bot_direct_request"
    assert not envelope.hard_veto
    assert not envelope.lightweight_runtime_eligible
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("1510912873981804627", is_bot=True),
        text,
        {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
        envelope,
    ) is None


def test_kabosu_discord_router_uses_sender_context_only_for_addressing():
    text = (
        "<sender_context>{\"sender_id\":\"1510912873981804627\","
        "\"receiver_id\":\"1517895542213181480\"}</sender_context>\n"
        "このissueのコメントを確認して、クローズしていいか判断して。"
    )

    envelope = _kabosu_discord_message_envelope(
        _source("1510912873981804627", is_bot=True),
        text,
        {},
    )

    assert envelope is not None
    assert "receiver_id" not in envelope.current_body
    assert envelope.addressed_to_kabosu
    assert envelope.act_type == "bot_direct_request"
    assert not envelope.hard_veto
    assert not envelope.lightweight_runtime_eligible


def test_kabosu_discord_router_does_not_silence_human_status_words_as_noop():
    text = "確認済みの情報も含めて、このissueを確認して判断して。"

    envelope = _kabosu_discord_message_envelope(
        _source("473730953735438336"),
        text,
        {},
    )

    assert envelope is not None
    assert envelope.act_type == "user_general"
    assert not envelope.hard_veto
    assert not envelope.lightweight_runtime_eligible


@pytest.mark.asyncio
async def test_kabosu_conversation_router_suppresses_no_reply_before_agent(monkeypatch):
    import hermes_cli.plugins as plugins

    monkeypatch.setattr(plugins, "invoke_hook", lambda *args, **kwargs: [])
    runner = GatewayRunner.__new__(GatewayRunner)
    runner._startup_restore_in_progress = False
    runner._update_prompt_pending = {}
    runner._kabosu_discord_topic_state = OrderedDict()
    runner._kabosu_lightweight_response_ledger = OrderedDict()
    runner._is_user_authorized = lambda _source: True
    runner._session_key_for_source = lambda _source: "discord:thread-1"
    runner._handle_message_with_agent = AsyncMock(return_value="agent response")

    source = _discord_session_source(is_bot=True)
    event = MessageEvent(
        text="<@1517895542213181480> runtime確認は受領済み。追加反応なし。",
        message_type=MessageType.TEXT,
        source=source,
    )

    assert await runner._handle_message(event) is None
    runner._handle_message_with_agent.assert_not_awaited()
    assert runner._kabosu_discord_topic_state["thread-1"].act_type == "no_reply"


def test_kabosu_lightweight_reply_dedupes_same_response_per_thread():
    runner = GatewayRunner.__new__(GatewayRunner)
    runner._kabosu_lightweight_response_ledger = OrderedDict()
    source = SimpleNamespace(thread_id="thread-1", chat_id="thread-1")
    response = "同じ軽量runtime返信"

    assert not runner._should_suppress_kabosu_lightweight_reply(
        source,
        "今のカボスのruntime状態を確認して。",
        response,
    )
    assert runner._should_suppress_kabosu_lightweight_reply(
        source,
        "今のカボスのruntime状態を確認して。",
        response,
    )
    assert not runner._should_suppress_kabosu_lightweight_reply(
        source,
        "もう一度、今のカボスのruntime状態を再確認して。",
        response,
    )


def test_kabosu_lightweight_reply_ignores_normal_work_requests():
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        "実装して",
        {},
    ) is None
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336"),
        "この処理は実装した。正しく実装されているか自分でも確認して。",
        {},
    ) is None


def test_kabosu_lightweight_reply_is_discord_only():
    assert _kabosu_discord_lightweight_runtime_reply(
        _source("473730953735438336", platform=Platform.TELEGRAM),
        "ownerは誰なの？",
        {},
    ) is None
