"""Concurrent migration snapshots must each retain a usable recovery file."""
import concurrent.futures
import sqlite3
import threading

from core import db_backup


def test_concurrent_snapshots_cannot_share_a_recovery_slot(tmp_path, monkeypatch):
    path = tmp_path / 'voices.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE voices(name TEXT)')
        connection.execute("INSERT INTO voices VALUES ('keep my voice')")
    counter = db_backup._next_counter
    boundary = threading.Barrier(2)

    def simultaneous_counter(*args):
        value = counter(*args)
        boundary.wait(timeout=5)
        return value

    monkeypatch.setattr(db_backup, '_next_counter', simultaneous_counter)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(db_backup.snapshot_before_migration, str(path), '1.0') for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert len(set(results)) == 2
    assert set(db_backup.list_backups(str(path))) == set(results)
    for backup in results:
        with sqlite3.connect(backup) as connection:
            assert connection.execute('SELECT name FROM voices').fetchall() == [('keep my voice',)]
    assert not list(tmp_path.glob('*.reserve'))


def test_abandoned_reservation_is_not_reused_or_listed(tmp_path):
    path = tmp_path / 'voices.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE voices(name TEXT)')
    abandoned = tmp_path / 'voices.db.backup-1.0-1.reserve'
    abandoned.touch()
    backup = db_backup.snapshot_before_migration(str(path), '1.0')
    assert backup.endswith('.backup-1.0-2')
    assert db_backup.list_backups(str(path)) == [backup]
    assert abandoned.exists()


def test_failed_copy_releases_its_reservation(tmp_path, monkeypatch):
    import pytest

    path = tmp_path / 'voices.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE voices(name TEXT)')
    connect = sqlite3.connect

    def fail_destination(filename, *args, **kwargs):
        if '.part-' in str(filename):
            raise sqlite3.OperationalError('destination unavailable')
        return connect(filename, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', fail_destination)
    with pytest.raises(sqlite3.OperationalError, match='destination unavailable'):
        db_backup.snapshot_before_migration(str(path), '1.0')
    assert not list(tmp_path.glob('*.reserve'))
    assert db_backup.list_backups(str(path)) == []


def test_abandoned_reservations_are_pruned_but_live_ones_kept(tmp_path):
    import os
    import time

    path = tmp_path / 'voices.db'
    path.write_bytes(b'')
    base = f'{path}.backup-1.0-'
    done = tmp_path / 'voices.db.backup-1.0-1'
    done.write_bytes(b'x')
    (tmp_path / 'voices.db.backup-1.0-1.reserve').write_bytes(b'')       # snapshot landed
    old = tmp_path / 'voices.db.backup-1.0-2.reserve'                    # dead writer
    old.write_bytes(b'')
    past = time.time() - 48 * 3600
    os.utime(old, (past, past))
    live = tmp_path / 'voices.db.backup-1.0-3.reserve'                   # in flight
    live.write_bytes(b'')
    db_backup.prune_backups(str(path))
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.endswith('.reserve')) == [live.name]
    assert done.exists() and base
