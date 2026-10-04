"""Voice Design: edits must reach the engine (Discord report).

1. Once a designed voice was saved or selected, every take sent its
   ``profile_id``. The backend then cloned the profile's saved sample, so new
   attributes, gender and seed barely mattered ("always a female voice"). A
   request whose instruct or seed differs from the design profile's now
   designs from the request; an unchanged one still re-renders the saved
   voice from its sample.
"""
import importlib
import os
import uuid

import pytest
import torch

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")


def _gen():
    return importlib.import_module("api.routers.generation")


def _tts():
    return importlib.import_module("services.tts_backend")


def _design_row(**overrides):
    row = {
        "kind": "design", "instruct": "male, low pitch", "vd_states": None,
        "seed": 42, "ref_audio_path": "design-sample.wav", "ref_text": "Sample.",
        "is_locked": 0, "locked_audio_path": "", "language": "Auto",
    }
    row.update(overrides)
    return row


# ── 1. an edited design must not clone the saved sample ─────────────────────


def test_unchanged_design_rerenders_from_its_saved_sample():
    cond = _gen()._resolve_profile_conditioning(
        _design_row(), instruct="low pitch, male", seed=42,
    )
    assert cond["ref_audio_path"] and cond["ref_audio_path"].endswith("design-sample.wav")
    assert not cond["diverged"]


def test_omitted_instruct_and_seed_mean_the_profiles():
    cond = _gen()._resolve_profile_conditioning(_design_row())
    assert cond["ref_audio_path"]
    assert cond["instruct"] == "male, low pitch"
    assert cond["seed"] == 42


def test_a_changed_instruct_designs_from_the_request():
    cond = _gen()._resolve_profile_conditioning(
        _design_row(), instruct="female, high pitch", seed=42,
    )
    assert cond["ref_audio_path"] is None
    assert cond["instruct"] == "female, high pitch"
    assert cond["diverged"]


def test_a_changed_seed_designs_from_the_request_with_the_profiles_instruct():
    cond = _gen()._resolve_profile_conditioning(_design_row(), seed=7)
    assert cond["ref_audio_path"] is None
    assert cond["instruct"] == "male, low pitch"
    assert cond["seed"] == 7


def test_a_locked_design_take_is_not_cloned_once_edited():
    row = _design_row(is_locked=1, locked_audio_path="locked.wav")
    assert _gen()._resolve_profile_conditioning(row)["ref_audio_path"].endswith("locked.wav")
    assert _gen()._resolve_profile_conditioning(row, instruct="female")["ref_audio_path"] is None


def test_a_clone_profile_keeps_its_reference_with_a_style_instruct():
    row = _design_row(kind="clone", instruct="", ref_audio_path="clip.wav")
    cond = _gen()._resolve_profile_conditioning(row, instruct="whisper", seed=9)
    assert cond["ref_audio_path"].endswith("clip.wav")


def _engine(design, engine_id):
    class _Fake(_tts().TTSBackend):
        id = engine_id
        display_name = "Reference-only engine (test)"
        supports_voice_design = design
        applies_own_mastering = False
        gpu_compat = ("cpu",)
        calls: list = []

        @property
        def sample_rate(self) -> int:
            return 24000

        @property
        def supported_languages(self) -> list[str]:
            return ["multi"]

        @classmethod
        def is_available(cls):
            return True, "ready"

        def generate(self, text, **kw) -> torch.Tensor:
            type(self).calls.append(kw)
            return torch.zeros(1, 2400)

    _Fake.calls = []
    return _Fake


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture()
def profiles():
    from core.db import db_conn, init_db

    init_db()
    created = []

    def make(kind, *, sample=False, instruct="male, low pitch", seed=42):
        import soundfile as sf
        from core.config import VOICES_DIR

        pid = f"vd-{uuid.uuid4().hex[:8]}"
        rel = None
        if sample:
            rel = f"{pid}.wav"
            os.makedirs(VOICES_DIR, exist_ok=True)
            sf.write(os.path.join(VOICES_DIR, rel), [0.0] * 24000, 24000)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO voice_profiles (id, name, kind, instruct, seed, "
                "ref_audio_path, ref_text, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (pid, "Narrator", kind, instruct, seed, rel, "Hello there.", 0.0),
            )
        created.append((pid, rel))
        return pid

    yield make
    from core.config import VOICES_DIR

    with db_conn() as conn:
        for pid, rel in created:
            conn.execute("DELETE FROM generation_history WHERE profile_id=?", (pid,))
            conn.execute("DELETE FROM voice_profiles WHERE id=?", (pid,))
            if rel:
                try:
                    os.remove(os.path.join(VOICES_DIR, rel))
                except OSError:
                    pass


def test_an_edited_design_reaches_the_engine_and_is_not_filed_under_the_profile(
    client, monkeypatch, profiles
):
    from core.db import db_conn

    fake = _engine(True, "fake-designer")
    monkeypatch.setitem(_tts()._REGISTRY, fake.id, fake)
    pid = profiles("design", sample=True)

    same = client.post("/generate", data={
        "text": "Hello", "engine": fake.id, "profile_id": pid,
        "instruct": "male, low pitch", "seed": "42",
    })
    assert same.status_code == 200, same.text
    assert fake.calls[-1].get("ref_audio")

    edited = client.post("/generate", data={
        "text": "Hello", "engine": fake.id, "profile_id": pid,
        "instruct": "female", "seed": "42",
    })
    assert edited.status_code == 200, edited.text
    assert not fake.calls[-1].get("ref_audio")
    assert fake.calls[-1].get("instruct") == "female"
    with db_conn() as conn:
        takes = conn.execute(
            "SELECT instruct FROM generation_history WHERE profile_id=?", (pid,)
        ).fetchall()
    assert [t["instruct"] for t in takes] == ["male, low pitch"]
