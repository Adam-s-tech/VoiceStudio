"""Re-locking a voice to another take re-keys its longform caches (#2535)."""
import asyncio
import os

import pytest
import torch

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")

from api.routers.audiobook import _render_chapter_cached  # noqa: E402
from services.audiobook import Chapter, Span  # noqa: E402


def _render(cache_dir, calls, tag, resolve):
    def synth(text, voice_id, speed=None):
        calls.append(tag)
        return torch.full((2400,), 0.1)

    chapter = Chapter(title="C", spans=[Span(voice_id=None, text="Hello.", pause_ms_after=0)])
    return _render_chapter_cached(chapter, synth, 24000, "eng", resolve, str(cache_dir))


@pytest.fixture
def locked_profile(tmp_path, monkeypatch):
    from api.routers import profiles
    from core import config, db

    voices = tmp_path / "voices"
    outputs = tmp_path / "outputs"
    voices.mkdir()
    outputs.mkdir()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setattr(profiles, "VOICES_DIR", str(voices))
    monkeypatch.setattr(profiles, "OUTPUTS_DIR", str(outputs))
    monkeypatch.setattr(config, "VOICES_DIR", str(voices))
    db.init_db()
    with db.db_conn() as conn:
        conn.execute("INSERT INTO voice_profiles(id,name) VALUES('voice','V')")
        for name, body in (("take1.wav", b"first-take"), ("take2.wav", b"second-take")):
            (outputs / name).write_bytes(body)
            conn.execute(
                "INSERT INTO generation_history(id, text, audio_path) VALUES(?, 'same text', ?)",
                (name[:5], name),
            )
    return voices


def test_relock_with_same_text_and_seed_re_keys_the_longform_cache(locked_profile, tmp_path):
    from api.routers import audiobook, profiles

    cache = tmp_path / "cache"
    cache.mkdir()
    calls: list = []

    def render(tag):
        return _render(cache, calls, tag, lambda _v: audiobook._resolve_voice("voice"))

    asyncio.run(profiles.lock_profile("voice", history_id="take1", seed=7))
    first_path, _, cached, _ = render("one")
    assert not cached

    asyncio.run(profiles.lock_profile("voice", history_id="take2", seed=7))
    second_path, _, cached, _ = render("two")
    assert not cached and calls == ["one", "two"]
    assert second_path != first_path

    # Inner segment layer: drop only the chapter WAV, the old take must not replay.
    os.remove(second_path)
    render("three")
    assert calls == ["one", "two"], "segment cached for the NEW take only"

    # The superseded take is swept once retired; only the current one remains.
    profiles.sweep_retired_voice_files(grace_s=0)
    assert len([p for p in os.listdir(locked_profile) if "locked" in p]) == 1


def test_relock_and_unlock_keep_the_take_a_running_render_still_reads(locked_profile):
    """A long-form render resolves the voice once and re-reads the reference
    for every segment; re-locking or unlocking mid-render must not delete it."""
    from api.routers import audiobook, profiles

    asyncio.run(profiles.lock_profile("voice", history_id="take1", seed=7))
    in_flight = audiobook._resolve_voice("voice")["ref_audio"]

    asyncio.run(profiles.lock_profile("voice", history_id="take2", seed=7))
    assert open(in_flight, "rb").read() == b"first-take"
    second = audiobook._resolve_voice("voice")["ref_audio"]

    asyncio.run(profiles.unlock_profile("voice"))
    assert open(second, "rb").read() == b"second-take"

    # Inside the grace period nothing goes; after it, both unreferenced takes do.
    assert profiles.sweep_retired_voice_files() == 0
    assert os.path.exists(in_flight) and os.path.exists(second)
    assert profiles.sweep_retired_voice_files(grace_s=0) == 2
    assert not os.path.exists(in_flight) and not os.path.exists(second)
    assert os.listdir(locked_profile / ".retired") == []


def test_sweep_keeps_a_retired_file_a_profile_references_again(locked_profile):
    from api.routers import profiles
    from core import db

    (locked_profile / "voice_locked.wav").write_bytes(b"legacy")  # pre-#2535 name
    with db.db_conn() as conn:
        conn.execute(
            "UPDATE voice_profiles SET locked_audio_path='voice_locked.wav', is_locked=1"
        )
    profiles._retire_voice_file("voice_locked.wav")
    assert profiles.sweep_retired_voice_files(grace_s=0) == 0
    assert (locked_profile / "voice_locked.wav").read_bytes() == b"legacy"
    assert os.listdir(locked_profile / ".retired") == []
