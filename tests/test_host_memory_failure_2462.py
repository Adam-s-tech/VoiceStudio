"""#2462 — a generation that fails because the HOST ran out of memory must say so.

The report is a bare floor message on a machine with no GPU:

    Generation failed. Check the selected engine and try again.
    Backend error class: RuntimeError
    StreamingPreviewError: Generation failed. Check the selected engine and try again.
    … Compute device: cpu … RAM: 7.9 GB

The cause is structural, not incidental. `_GPU_OOM_SIGNATURES` names only DEVICE
allocators — CUDA, MPS, HIP, "out of memory on device" — so on a CPU-only host
the taxonomy has no entry for the one memory failure that can happen there.
torch raises it as a bare ``RuntimeError`` from its CPU allocator, classify()
returns "" and the streaming frame can only say "check the selected engine",
which sends the reporter to an engine that is fine. #2177 closed exactly this
gap for the unsupported-GPU class; this is the other half — the machine, not
the card.

Two things must not move: a real device OOM keeps GPU_OOM and its VRAM remedy,
and a genuinely unknown failure keeps the byte-identical floor message (#1943's
"confidently wrong remedy" is worse than no remedy).
"""
import pytest

from core import error_journal
from core.failure import (
    _CONTEXT_FREE_HINT_CLASSES,
    _HINTS,
    _HOST_OOM_SIGNATURES,
    classify,
    is_host_oom,
)
from core.public_errors import public_exception_response, stream_generation_failure

# The report's own failure: torch's CPU allocator on a 7.9 GB, GPU-less machine.
TORCH_CPU_ALLOCATOR = (
    "DefaultCPUAllocator: not enough memory: you tried to allocate 2147483648 bytes."
)
WINDOWS_WINERROR_8 = "[WinError 8] Not enough memory to continue the execution of the program"
BAD_ALLOC = "std::bad_alloc"
C_ALLOC_FAIL = "[enforce fail at alloc_cpu.cpp:75] . Can't allocate memory: you tried to allocate..."

# Signatures that must NOT be claimed. Each is a real phrasing a dependency or
# the OS produces for something that has nothing to do with RAM — the #1943
# shape. A hint that names the wrong cause is the failure mode of this module.
NOT_HOST_OOM = [
    "No space left on device",                       # a disk, not RAM
    "[WinError 1455] The paging file is too small for this operation to complete",
    "The read operation timed out",
    "Connection reset by peer",
    "CUDA out of memory. Tried to allocate 2.00 GiB",  # the device class
]


# ── the reported failure ────────────────────────────────────────────────────


def test_a_cpu_host_that_runs_out_of_memory_is_named_instead_of_the_floor_message():
    payload = stream_generation_failure(RuntimeError(TORCH_CPU_ALLOCATOR))

    assert payload["docs_topic"] == "HOST_MEMORY_EXHAUSTED"
    assert payload["hint"]
    assert payload["docs_url"].endswith("#generation-failure-diagnosis")
    # The floor message is still the lead; the hint is appended to it, exactly
    # as the other context-free classes render.
    assert payload["detail"].startswith(stream_generation_failure(RuntimeError("boom"))["detail"])
    assert payload["detail"] != stream_generation_failure(RuntimeError("boom"))["detail"]


def test_the_remedy_is_about_system_memory_not_vram():
    """A CPU-only reporter must not be told to free VRAM or to choose CPU —
    that is what GPU_OOM's hint says, and both halves of it are wrong here."""
    hint = stream_generation_failure(RuntimeError(TORCH_CPU_ALLOCATOR))["hint"]

    assert "memory" in hint.lower()
    assert "GPU-heavy" not in hint
    assert "choose CPU" not in hint
    # Something the user can actually do on a laptop with no discrete GPU.
    assert "Flush models" in hint


def test_it_stays_retryable_rather_than_terminal():
    """Unlike #2177's build mismatch, host RAM frees up: closing a browser tab
    genuinely repairs it, so the floor message's "try again" is still true."""
    payload = stream_generation_failure(RuntimeError(TORCH_CPU_ALLOCATOR))

    assert payload.get("terminal", False) is False
    assert payload["retryable"] is True


def test_the_exception_class_still_rides_along():
    # #1800's guarantee must survive the new branch.
    payload = stream_generation_failure(RuntimeError(TORCH_CPU_ALLOCATOR))
    assert payload["error_class"] == "RuntimeError"


@pytest.mark.parametrize("message", [
    TORCH_CPU_ALLOCATOR,
    WINDOWS_WINERROR_8,
    BAD_ALLOC,
    C_ALLOC_FAIL,
    "[Errno 12] Cannot allocate memory",
])
def test_every_host_oom_spelling_reaches_the_user(message):
    payload = stream_generation_failure(RuntimeError(message))
    assert payload["docs_topic"] == "HOST_MEMORY_EXHAUSTED"
    assert payload["hint"]


# ── the other memory classes must be untouched ──────────────────────────────


def test_a_device_oom_keeps_its_own_class_and_vram_remedy():
    payload = stream_generation_failure(
        RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
    )

    assert payload["docs_topic"] == "GPU_OOM"
    assert payload["retryable"] is True
    assert "GPU-heavy" in payload["hint"]


# ── no private data escapes ─────────────────────────────────────────────────


def test_no_exception_text_is_ever_copied():
    """Constitution I — this surface reports topics, not messages. The reporter's
    paths and sizes must not ride along in the hint."""
    secret = "C:/Users/someone/private-voice-sample.wav"
    payload = stream_generation_failure(
        RuntimeError(f"{TORCH_CPU_ALLOCATOR} (while reading {secret})")
    )

    assert payload["docs_topic"] == "HOST_MEMORY_EXHAUSTED"
    for value in payload.values():
        assert secret not in str(value)
        assert "someone" not in str(value)
    # Not even the allocation size the reporter's machine printed.
    assert "2147483648" not in str(payload)


# ── taxonomy invariants ─────────────────────────────────────────────────────


@pytest.mark.parametrize("message", [
    TORCH_CPU_ALLOCATOR,
    WINDOWS_WINERROR_8,
    BAD_ALLOC,
    C_ALLOC_FAIL,
])
def test_the_class_classifies_on_its_own(message):
    assert classify(message) == "HOST_MEMORY_EXHAUSTED"


def test_every_context_free_class_has_a_hint_to_give():
    missing = {t for t in _CONTEXT_FREE_HINT_CLASSES if not _HINTS.get(t)}
    assert not missing, f"allowlisted with no hint text: {sorted(missing)}"


def test_the_helper_walks_wrappers_the_way_its_device_twin_does():
    """Same contract as is_gpu_oom: a failure re-raised behind a wrapper is the
    same failure, and the reason string alone would miss it."""
    try:
        try:
            raise RuntimeError(TORCH_CPU_ALLOCATOR)
        except RuntimeError as inner:
            raise RuntimeError("voice-clone prompt precompute failed") from inner
    except RuntimeError as wrapped:
        assert is_host_oom(wrapped)

    outer = RuntimeError("generation failed")
    outer.__context__ = RuntimeError(BAD_ALLOC)
    assert is_host_oom(outer)

    assert is_host_oom(MemoryError())  # the type name is unambiguous
    assert not is_host_oom(RuntimeError("model load failed"))
    assert not is_host_oom("CUDA out of memory")


def test_the_journal_names_the_class_instead_of_unknown():
    """A streaming failure reaches the journal, not the 500 handler. The reporter's
    report could only say `RuntimeError` because the journal filed it UNKNOWN."""
    assert error_journal.classify_exception(RuntimeError(TORCH_CPU_ALLOCATOR)) == (
        "HOST_MEMORY_EXHAUSTED"
    )
    # And the device class is not stolen by it.
    assert error_journal.classify_exception(
        RuntimeError("CUDA out of memory. Tried to allocate 2.5 GiB")
    ) == "GPU_OOM"


def test_the_two_signature_lists_cannot_drift():
    """The journal keeps literals so importing it never drags in the taxonomy;
    this is the guard that keeps those literals equal to the real ones."""
    journal_rules = dict(error_journal._CLASS_RULES)

    assert set(journal_rules["HOST_MEMORY_EXHAUSTED"]) == set(_HOST_OOM_SIGNATURES)


def test_the_windows_paging_file_class_keeps_its_own_specific_remedy():
    """WinError 1455 and WinError 8 are both "not enough memory" to a user and
    both are Windows, but only the first is fixed by growing the page file."""
    payload = public_exception_response(
        OSError("[WinError 1455] The paging file is too small for this operation to complete"),
        fallback="Internal error.",
    )

    assert payload.get("docs_topic") == "WINDOWS_PAGING_FILE_TOO_SMALL"


@pytest.mark.parametrize("message", NOT_HOST_OOM)
def test_nothing_else_is_misread_as_ram_exhaustion(message):
    """#1943's lesson, applied to the new class: a hint that confidently names
    the wrong cause sends the user somewhere useless. Disk-full, the paging
    file, timeouts and the device class all share vocabulary with RAM."""
    assert classify(message) != "HOST_MEMORY_EXHAUSTED"
