import json
from types import SimpleNamespace

from gateway.change_audit import record_discord_audit_event, should_audit_discord_user


def test_should_audit_default_user_id(monkeypatch):
    monkeypatch.delenv("HERMES_DISCORD_AUDIT_USER_IDS", raising=False)

    assert should_audit_discord_user("473730953735438336")
    assert not should_audit_discord_user("123")


def test_record_discord_audit_event_writes_target_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_AUDIT_DIR", str(tmp_path / "audit"))
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "SOUL.md").write_text("persona", encoding="utf-8")
    (hermes_home / "config.yaml").write_text("model: test\n", encoding="utf-8")
    (hermes_home / ".env").write_text("SECRET=redacted\n", encoding="utf-8")

    source = SimpleNamespace(
        platform=SimpleNamespace(value="discord"),
        user_id="473730953735438336",
        user_name="_thepioneer",
        chat_id="channel-1",
        chat_name="test",
        chat_type="group",
        thread_id=None,
        guild_id="guild-1",
        message_id="message-1",
    )
    event = SimpleNamespace(
        source=source,
        text="Hermesの設定を変えて",
        message_id="message-1",
        reply_to_message_id="reply-1",
    )

    record_discord_audit_event(
        hermes_home=hermes_home,
        event=event,
        message_preview="Hermesの設定を変えて",
        reply_to_text="previous",
    )

    audit_path = tmp_path / "audit" / "discord-user-473730953735438336.jsonl"
    record = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert record["kind"] == "discord_inbound"
    assert record["source"]["user_id"] == "473730953735438336"
    assert record["message"]["text"] == "Hermesの設定を変えて"
    assert record["state"]["soul"]["sha256"]
    assert record["state"]["config"]["sha256"]


def test_record_discord_audit_event_ignores_other_users(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DISCORD_AUDIT_DIR", str(tmp_path / "audit"))
    source = SimpleNamespace(
        platform=SimpleNamespace(value="discord"),
        user_id="not-target",
    )
    event = SimpleNamespace(source=source, text="ignore")

    record_discord_audit_event(
        hermes_home=tmp_path,
        event=event,
        message_preview="ignore",
        reply_to_text="",
    )

    assert not (tmp_path / "audit").exists()
