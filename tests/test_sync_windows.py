from __future__ import annotations

from datetime import date

from pipeline.config import Settings
from pipeline.store import Store
from pipeline.sync import (
    ANCHOR_KEY,
    CHECKPOINT_CHUNK_DAYS_KEY,
    CHECKPOINT_KEY,
    checkpoint_chunk_days,
    pending_chunks,
    sync,
)


def test_bounded_window_sync_is_resumable(monkeypatch, tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_dirs()
    store = Store(settings.db_path)

    fetched: list[tuple[date, date]] = []

    def fake_fetch(_settings, start, end, **_kwargs):
        fetched.append((start, end))
        return f"dummy history {start} {end}"

    parsed = []
    monkeypatch.setattr("pipeline.sync.amfi.fetch_history", fake_fetch)
    monkeypatch.setattr("pipeline.sync.amfi.parse_history", lambda text: parsed)

    result = sync(
        settings,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        chunk_days=10,
        skip_navall=True,
        save_raw=False,
        finalise=False,
        log_fn=lambda _msg: None,
    )

    assert result["chunks"] == 4
    assert result["chunks_completed"] == 4
    assert len(fetched) == 4
    assert CHECKPOINT_KEY in store.get_meta()

    fetched.clear()
    result = sync(
        settings,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        chunk_days=10,
        skip_navall=True,
        save_raw=False,
        finalise=False,
        log_fn=lambda _msg: None,
    )

    assert result["chunks_completed"] == 0
    assert fetched == []


def test_pending_chunks_use_stable_anchor(tmp_path):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_dirs()
    store = Store(settings.db_path)
    store.init_schema()

    store.set_meta(
        {
            ANCHOR_KEY: "2026-01-01",
            CHECKPOINT_CHUNK_DAYS_KEY: "10",
            CHECKPOINT_KEY: '[["2026-01-01", "2026-01-10"]]',
        }
    )

    pending = pending_chunks(settings, bootstrap_days=999, chunk_days=30)
    assert pending[0] == (date(2026, 1, 11), date(2026, 1, 20))
    assert pending[1] == (date(2026, 1, 21), date(2026, 1, 30))
    assert checkpoint_chunk_days(settings) == 10
