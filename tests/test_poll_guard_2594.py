"""#2594 / #2601 / #2247: status polls must not be able to starve the worker pool.

The renderer polls ``/model/status``, ``/model/loaded`` and ``/workers/target``
about once a second per widget while anything runs. They were sync routes
behind a sync ``require_admin`` dependency, so every poll (and every other
admin-router request) took a thread from the shared 40-thread pool. When the
pool filled with blocked sync routes the whole API stopped answering although
the process was alive.

Fail-before: the routes and the admin dependency are plain functions, so with
the pool saturated a poll never gets a thread. Pass-after: they run on the
event loop / a private executor and answer regardless.
"""

import asyncio
import inspect
import os
import sys
import threading
import time

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
)

from core.poll_guard import PollGuard  # noqa: E402


def test_status_poll_routes_and_admin_gate_never_use_the_worker_pool():
    from api import dependencies
    from api.routers import system, workers

    for fn in (
        dependencies.require_admin,
        system.model_status,
        system.loaded_models,
        workers.get_target,
    ):
        assert inspect.iscoroutinefunction(fn), (
            f"{fn.__name__} is sync: it would queue behind every blocked sync route"
        )


def test_wedged_snapshot_costs_one_private_thread_and_answers_503():
    release = threading.Event()
    calls = []

    def _wedged():
        calls.append(threading.current_thread().name)
        release.wait(30)
        return {"ok": True}

    async def scenario():
        guard = PollGuard("unit", _wedged, deadline_s=0.2)
        started = time.monotonic()
        results = await asyncio.gather(*(guard.get() for _ in range(60)), return_exceptions=True)
        elapsed = time.monotonic() - started
        return results, elapsed

    try:
        results, elapsed = asyncio.run(scenario())
    finally:
        release.set()
    assert elapsed < 2.0, "callers waited on the wedged snapshot"
    assert all(getattr(r, "status_code", None) == 503 for r in results)
    assert len(calls) == 1, "concurrent polls must share one in-flight computation"
    assert calls[0].startswith("poll-unit")


def test_overrun_serves_the_last_good_snapshot():
    state = {"block": False}
    release = threading.Event()

    def _snapshot(key):
        if state["block"]:
            release.wait(30)
        return {"key": key, "n": 1}

    async def scenario():
        guard = PollGuard("unit", _snapshot, deadline_s=0.2)
        first = await guard.get("tts")
        state["block"] = True
        stale = await guard.get("tts")
        other = None
        try:
            await guard.get("clone")  # never answered: no stale value for it
        except Exception as exc:  # noqa: BLE001
            other = exc
        return first, stale, other

    try:
        first, stale, other = asyncio.run(scenario())
    finally:
        release.set()
    assert first == stale == {"key": "tts", "n": 1}
    assert getattr(other, "status_code", None) == 503


def test_sequential_polls_are_not_cached():
    counter = iter(range(100))
    guard = PollGuard("unit", lambda: next(counter))

    async def scenario():
        return [await guard.get(), await guard.get()]

    assert asyncio.run(scenario()) == [0, 1]


def test_polls_answer_while_the_shared_pool_is_saturated(monkeypatch, tmp_path):
    """The real routes, behind the real admin gate, with all 40 pool threads held."""
    httpx = pytest.importorskip("httpx")
    from fastapi import FastAPI
    from api.routers import system, workers

    app = FastAPI()
    app.include_router(system.router)
    app.include_router(workers.router)
    release = threading.Event()

    @app.get("/_block")
    def block():  # a sync route: runs in the shared pool
        release.wait(30)
        return {}

    from services import model_lifecycle

    monkeypatch.setattr(model_lifecycle, "list_loaded", lambda: {"models": [], "count": 0})

    async def scenario():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            blockers = [asyncio.ensure_future(client.get("/_block")) for _ in range(60)]
            await asyncio.sleep(0.5)  # pool is now full, 20 more queued behind it
            try:
                started = time.monotonic()
                status = await asyncio.wait_for(client.get("/model/status"), 5)
                loaded = await asyncio.wait_for(client.get("/model/loaded"), 5)
                target = await asyncio.wait_for(client.get("/workers/target?op=tts"), 5)
                return status, loaded, target, time.monotonic() - started
            finally:
                release.set()
                await asyncio.gather(*blockers, return_exceptions=True)

    status, loaded, target, elapsed = asyncio.run(scenario())
    assert status.status_code == 200, status.text
    assert loaded.status_code == 200, loaded.text
    assert target.status_code == 200, target.text
    assert elapsed < 4.0
