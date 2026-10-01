"""A full disk mid-install must fail fast with an actionable message (not retry
five times, not blame the network)."""
import errno

import pytest

from core.failure import is_disk_full_error


@pytest.mark.parametrize(
    "reason",
    [
        OSError(errno.ENOSPC, "No space left on device"),
        OSError("[Errno 28] No space left on device: '/x/blobs/a.incomplete'"),
        "[WinError 112] There is not enough space on the disk",
        "OSError: [Errno 122] Disk quota exceeded",
    ],
)
def test_disk_full_is_recognised(reason):
    assert is_disk_full_error(reason)


def test_disk_full_is_found_through_a_wrapped_cause():
    try:
        try:
            raise OSError(errno.ENOSPC, "No space left on device")
        except OSError as inner:
            raise RuntimeError("download failed") from inner
    except RuntimeError as wrapped:
        assert is_disk_full_error(wrapped)


def test_other_failures_are_not_disk_full():
    assert not is_disk_full_error(ConnectionResetError("peer closed connection"))
    assert not is_disk_full_error("Not enough disk space to install: needs 3 GB")
    assert not is_disk_full_error(None)


def test_model_install_does_not_retry_a_full_disk():
    from api.routers.setup.download import _is_retryable_download_error

    assert not _is_retryable_download_error(OSError(errno.ENOSPC, "No space left on device"))
    assert _is_retryable_download_error(ConnectionResetError(errno.ECONNRESET, "reset"))


def test_disk_full_message_names_free_space_and_cache(tmp_path):
    from api.routers.setup.models import disk_full_message

    text = disk_full_message(cache_dir=str(tmp_path))
    assert str(tmp_path) in text and "Free up space" in text


def test_sidecar_install_reports_full_disk_from_uv_log():
    from collections import deque

    from services import sidecar_install as si

    job = {"log": deque(["Downloading torch", "error: failed to write: No space left on device (os error 28)"])}
    assert si._log_shows_disk_full(job)
    assert not si._log_shows_disk_full({"log": deque(["connection reset by peer"])})
