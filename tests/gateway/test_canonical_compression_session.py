from datetime import datetime

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionSource, SessionStore
from hermes_state import SessionDB


def _discord_source() -> SessionSource:
    return SessionSource(
        platform=Platform.DISCORD,
        chat_id="1516075912532066547",
        chat_type="group",
        thread_id="1519632807037767720",
        user_id="user-1",
        user_name="tester",
    )


def _runner(store: SessionStore, db: SessionDB):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.session_store = store
    runner._session_db = db
    return runner


def test_gateway_resolves_discord_compressed_parent_before_context(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("compressed-parent", "discord")
    db.end_session("compressed-parent", "compression")
    db.create_session(
        "compressed-tip",
        "discord",
        parent_session_id="compressed-parent",
    )
    db._conn.execute(
        "UPDATE sessions SET started_at=? WHERE id=?",
        (datetime.now().timestamp() + 1, "compressed-tip"),
    )
    db._conn.commit()

    config = GatewayConfig(
        platforms={Platform.DISCORD: PlatformConfig(enabled=True, token="***")}
    )
    store = SessionStore(sessions_dir=tmp_path / "sessions", config=config)
    store._db = db
    entry = store.get_or_create_session(_discord_source())
    entry.session_id = "compressed-parent"
    entry.last_prompt_tokens = 345000
    store._save()

    resolved, block = _runner(store, db)._resolve_canonical_gateway_session(
        _discord_source(),
        entry,
    )

    assert block is None
    assert resolved.session_id == "compressed-tip"
    assert resolved.last_prompt_tokens == 0
    assert store.get_or_create_session(_discord_source()).session_id == "compressed-tip"


def test_gateway_blocks_compressed_parent_without_tip(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("compressed-parent", "discord")
    db.end_session("compressed-parent", "compression")

    config = GatewayConfig(
        platforms={Platform.DISCORD: PlatformConfig(enabled=True, token="***")}
    )
    store = SessionStore(sessions_dir=tmp_path / "sessions", config=config)
    store._db = db
    entry = store.get_or_create_session(_discord_source())
    entry.session_id = "compressed-parent"
    store._save()

    resolved, block = _runner(store, db)._resolve_canonical_gateway_session(
        _discord_source(),
        entry,
    )

    assert resolved.session_id == "compressed-parent"
    assert block is not None
    assert "compressed archived history" in block
