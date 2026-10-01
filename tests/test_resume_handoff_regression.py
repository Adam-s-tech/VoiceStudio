import asyncio
from pathlib import Path

import pytest


@pytest.fixture
def checkpoint(tmp_path, monkeypatch):
    from core import config, db
    from services import longform_resume, ffmpeg_utils
    monkeypatch.setattr(config, "OUTPUTS_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "jobs.db"))
    db.init_db()
    monkeypatch.setattr(ffmpeg_utils, "find_ffmpeg", lambda: None)
    manifest = longform_resume.build_manifest(job_id="old", job_type="story", title="Book",
        plan_chapters=[{"title": "Chapter", "spans": [{"voice_id": "v", "text": "Saved prose", "pause_ms_after": 0, "speed": None}]}],
        params={"default_voice": "v", "voice_map": {"v": "voice"}})
    path = longform_resume.write_manifest(manifest)
    return Path(path), manifest


def test_unconsumed_or_closed_response_preserves_checkpoint(checkpoint):
    from api.routers import audiobook
    from services import longform_resume
    path, manifest = checkpoint
    async def run():
        response = await audiobook.resume_longform("old")
        assert longform_resume.load_manifest_file(str(path)) == manifest
        await response.body_iterator.aclose()
        assert longform_resume.load_manifest_file(str(path)) == manifest
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["replace", "raise"])
def test_failed_replacement_keeps_original(checkpoint, monkeypatch, failure):
    from api.routers import audiobook
    from services import longform_resume
    path, manifest = checkpoint
    if failure == "replace":
        monkeypatch.setattr(longform_resume.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    else:
        monkeypatch.setattr(longform_resume, "write_manifest", lambda *_: (_ for _ in ()).throw(RuntimeError("write failed")))
    async def run():
        response = await audiobook.resume_longform("old")
        assert "ffmpeg" in await anext(response.body_iterator)
        await response.body_iterator.aclose()
    asyncio.run(run())
    assert longform_resume.load_manifest_file(str(path)) == manifest


def test_original_retired_only_after_atomic_checkpoint_then_close(checkpoint, monkeypatch):
    from api.routers import audiobook
    from services import longform_resume
    path, manifest = checkpoint
    real_discard = longform_resume.discard_manifest_file
    observed = []
    def discard(old_path):
        replacements = [e for e in longform_resume.scan_resumable() if e["job_id"] != "old"]
        assert len(replacements) == 1
        replacement = longform_resume.load_manifest_file(replacements[0]["manifest_path"])
        assert replacement["plan"] == manifest["plan"]
        assert replacement["params"]["voice_map"] == manifest["params"]["voice_map"]
        observed.append(replacements[0]["manifest_path"])
        real_discard(old_path)
    monkeypatch.setattr(longform_resume, "discard_manifest_file", discard)
    async def run():
        response = await audiobook.resume_longform("old")
        assert path.exists()
        assert "ffmpeg" in await anext(response.body_iterator)
        await response.body_iterator.aclose()
    asyncio.run(run())
    assert not path.exists() and len(observed) == 1
    assert longform_resume.load_manifest_file(observed[0])["plan"] == manifest["plan"]


def test_cancel_during_checkpoint_write_keeps_original(checkpoint, monkeypatch):
    from api.routers import audiobook
    from services import longform_resume
    path, manifest = checkpoint
    def cancel(_fd):
        raise asyncio.CancelledError()
    monkeypatch.setattr(longform_resume, "flush_fd", cancel)
    async def run():
        response = await audiobook.resume_longform("old")
        with pytest.raises(asyncio.CancelledError):
            await anext(response.body_iterator)
        await response.body_iterator.aclose()
    asyncio.run(run())
    assert longform_resume.load_manifest_file(str(path)) == manifest
