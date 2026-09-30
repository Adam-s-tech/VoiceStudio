"""#2394: two cold TTS loads must never overlap, whichever route started them.

A reporter's backend died 16 s after startup with
``exit code -1073741819`` — ``0xC0000005`` STATUS_ACCESS_VIOLATION — right
after two ``generate:start (audio)`` clicks, with ``Preloading TTS model in
background…`` still live in the captured log.

There were two cold-load routes into the same native
``VoiceStudio.from_pretrained``:

  * the startup preload (and any server-loop ``get_model()``) held
    ``_model_lock`` and ran the load *in the GPU pool*;
  * a generate reaching ``OmniVoiceBackend._ensure_loaded()`` on a pool worker
    could not await ``_model_lock`` (bound to the server loop, #1417), so it
    took ``_model_load_thread_lock`` instead and loaded INLINE.

Those two locks are disjoint, and ``_pick_gpu_workers()`` gives CUDA hosts up
to four pool workers (#567) — so a generate landing on worker #2 while the
preload still held only ``_model_lock`` found the thread lock free, saw
``model is None``, and entered the native load CONCURRENTLY with the preload.
Two overlapping torch loads in one process is what Windows answers with an
access violation; #1669 is the same class on the ASR side.

Fail-before: two concurrent ``_load_model_sync`` calls, and the second caller
wastes a full load. Pass-after: exactly one load, and the waiter adopts it.

The test drives the real shape — a preload on the server loop holding
``_model_lock``, plus a generate on a pool-named thread — and asserts on
overlap rather than on lock identity, so it still fails if the exclusion is
re-implemented wrongly rather than only if it is removed.
"""

from __future__ import annotations

import asyncio
import importlib
import threading

import pytest


@pytest.fixture
def mm():
    """Resolve per test — a collection-time binding can go stale when another
    suite rebinds ``services.model_manager`` in ``sys.modules``."""
    return importlib.import_module("services.model_manager")


class _ConcurrentLoadProbe:
    """Stands in for ``_load_model_sync`` and records whether two ever overlap.

    ``max_in_flight`` is the assertion that matters: a real native load that
    overlaps another is unrecoverable, so the fix has to make the *count* one,
    not merely make both callers eventually succeed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.max_in_flight = 0
        self.model = object()

    def __call__(self):
        with self._lock:
            self.calls += 1
            self.max_in_flight = max(self.max_in_flight, self.calls)
        # Hold the "native load" open long enough that a second route which is
        # wrongly allowed in lands inside this window.
        threading.Event().wait(0.2)
        return self.model


def _drive_both_cold_routes(mm):
    """Run the preload and generate cold routes concurrently.

    The generate side runs on a thread named like a pool worker, which is what
    ``running_on_gpu_pool()`` keys on (#1417) — the real thing is reached from
    ``OmniVoiceBackend._ensure_loaded()``, which is already on that pool.
    """
    results: dict[str, object] = {}
    started = threading.Barrier(2, timeout=10)

    def _call(key: str) -> None:
        try:
            started.wait()
            results[key] = asyncio.run(mm.get_model())
        except BaseException as exc:  # noqa: BLE001 — the failure IS the subject
            results[key] = exc

    preload = threading.Thread(target=_call, args=("preload",), name="server-loop")
    generate = threading.Thread(
        target=_call, args=("generate",), name=f"{mm._GPU_POOL_THREAD_PREFIX}1"
    )
    preload.start()
    generate.start()
    preload.join(timeout=30)
    generate.join(timeout=30)
    return results.get("preload"), results.get("generate"), preload, generate


def _isolate(mm, monkeypatch, probe):
    """Fresh locks + a probe loader, so no other test's state can mask a race."""
    monkeypatch.setattr(mm, "model", None, raising=False)
    monkeypatch.setattr(mm, "_model_lock", asyncio.Lock(), raising=False)
    monkeypatch.setattr(mm, "_model_load_thread_lock", threading.RLock(), raising=False)
    monkeypatch.setattr(mm, "_load_model_sync", probe, raising=False)
    # Reclaim touches real memory/disk probes; keep the leaf's other work out.
    monkeypatch.setattr(mm, "_make_room_before_tts_load", lambda: None, raising=False)


def test_a_generate_cannot_enter_the_native_load_during_a_background_preload(
    mm, monkeypatch
):
    """THE CRASH. Fail-before: two overlapping ``from_pretrained`` calls."""
    probe = _ConcurrentLoadProbe()
    _isolate(mm, monkeypatch, probe)

    preload_result, generate_result, preload, generate = _drive_both_cold_routes(mm)

    # A timed-out thread is still inside `get_model()`; touching module state
    # under it would leak a live thread into later tests.
    assert not preload.is_alive() and not generate.is_alive(), (
        "a cold load never returned — the routes are deadlocking instead of "
        "excluding each other"
    )
    monkeypatch.setattr(mm, "model", None, raising=False)

    assert not isinstance(preload_result, BaseException), preload_result
    assert not isinstance(generate_result, BaseException), generate_result

    assert probe.max_in_flight == 1, (
        f"{probe.max_in_flight} native loads ran at once — overlapping torch "
        "loads in one process is the Windows access violation (#2394)"
    )
    assert probe.calls == 1, (
        f"the native load ran {probe.calls} times; the waiter must adopt the "
        "model the first load published, not start its own"
    )
    # Both callers get the one published model — the fix is exclusion, not a
    # second load that happens not to crash.
    assert preload_result is probe.model
    assert generate_result is probe.model


def test_a_lone_cold_load_still_loads_and_publishes(mm, monkeypatch):
    """The exclusion must not turn into "never load"."""
    probe = _ConcurrentLoadProbe()
    monkeypatch.setattr(mm, "model", None, raising=False)
    monkeypatch.setattr(mm, "_model_lock", asyncio.Lock(), raising=False)
    monkeypatch.setattr(mm, "_model_load_thread_lock", threading.RLock(), raising=False)
    monkeypatch.setattr(mm, "_load_model_sync", probe, raising=False)
    reclaimed = []
    monkeypatch.setattr(
        mm, "_make_room_before_tts_load", lambda: reclaimed.append(1), raising=False
    )

    loaded = asyncio.run(mm.get_model())

    assert loaded is probe.model
    assert mm.model is probe.model
    assert probe.calls == 1
    # Reclaim moved into the shared leaf, so the inline pool-worker route gets
    # it too — it used to keep a private second copy that could drift.
    assert reclaimed == [1], (
        "the pre-load reclaim must run once, immediately before the load"
    )


def test_a_warm_model_never_takes_the_load_lock(mm, monkeypatch):
    """The guard must not serialise the hot path behind a load lock."""
    probe = _ConcurrentLoadProbe()
    resident = object()
    monkeypatch.setattr(mm, "model", resident, raising=False)
    monkeypatch.setattr(mm, "_load_model_sync", probe, raising=False)

    async def _no_heal():
        return None

    monkeypatch.setattr(mm, "_heal_tts_placement", _no_heal, raising=False)
    monkeypatch.setattr(mm, "make_room_before_generate", lambda: None, raising=False)

    assert asyncio.run(mm.get_model()) is resident
    assert probe.calls == 0, "a resident model must not re-enter the cold load"

