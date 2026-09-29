"""Round 13, S5-01: `make install` on the server writes the unit file whole or not at all.

The unit was read for the rollback, and then written in place with `write_text`, outside the
`try` the rest of the install is in: a disk that filled or failed part way left half a unit file
in /etc/systemd/system, the install ended in a traceback, and nothing was put back. The rollback's
own `write_bytes` was the same in-place write. Production's installer has the same write and no
rollback at all.

Now the unit goes to a file beside it, is flushed to the disk and renamed over the old one, and the
folder is flushed; a write that fails leaves the unit that was there byte for byte and the install
exits 1, and the rollback puts a unit back the same way. systemctl, /proc and /health are stood in
for exactly as in tests/test_r11_install_gate.py.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

from tests.test_r11_install_gate import NEW_UNIT, OLD_UNIT, UNIT, Host


def _fail_part_way(monkeypatch, content: bytes) -> None:
    """The disk fills while `content` is being written: half of it goes down, then ENOSPC. Caught
    at every way a file's bytes are written here (os.write, Path.write_text, Path.write_bytes), so
    whichever the installer uses meets it; every other write is untouched."""
    real_write, real_text, real_bytes = os.write, Path.write_text, Path.write_bytes

    def write(fd, data):
        if bytes(data) == content:
            real_write(fd, bytes(data[: len(content) // 2]))
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(fd, data)

    def write_text(self, text, *args, **kwargs):
        if str(text).encode("utf-8") == content:
            real_text(self, str(text)[: len(text) // 2], *args, **kwargs)
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_text(self, text, *args, **kwargs)

    def write_bytes(self, data):
        if bytes(data) == content:
            real_bytes(self, bytes(data[: len(data) // 2]))
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_bytes(self, data)

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(Path, "write_bytes", write_bytes)


def test_a_unit_write_that_fails_part_way_leaves_the_unit_that_was_there(tmp_path, monkeypatch, capsys):
    host = Host(tmp_path, monkeypatch, previous=OLD_UNIT)
    _fail_part_way(monkeypatch, NEW_UNIT.encode("utf-8"))
    assert host.installer.install(8000) == 1
    monkeypatch.undo()
    assert host.unit.read_bytes() == OLD_UNIT, "byte for byte the unit that was there"
    assert sorted(p.name for p in host.unit.parent.iterdir()) == [UNIT], "nothing half-written left beside it"
    assert ("restart", UNIT) not in host.calls, "the service was not touched: nothing it runs on changed"
    out = capsys.readouterr().out
    assert "FAIL" in out and "Done." not in out


def test_a_first_install_whose_unit_write_fails_leaves_no_unit(tmp_path, monkeypatch, capsys):
    host = Host(tmp_path, monkeypatch, previous=None, enabled=False, active=False)
    _fail_part_way(monkeypatch, NEW_UNIT.encode("utf-8"))
    assert host.installer.install(8000) == 1
    monkeypatch.undo()
    assert list(host.unit.parent.iterdir()) == []
    assert "Done." not in capsys.readouterr().out


def test_the_rollback_puts_the_unit_back_whole_or_leaves_the_new_one_whole(tmp_path, monkeypatch, capsys):
    host = Host(tmp_path, monkeypatch, previous=OLD_UNIT, health=None)     # a gate fails: roll back
    _fail_part_way(monkeypatch, OLD_UNIT)                                   # and the disk fills as it does
    assert host.installer.install(8000) == 1
    monkeypatch.undo()
    assert host.unit.read_bytes() in (OLD_UNIT, NEW_UNIT.encode("utf-8")), host.unit.read_bytes()
    assert sorted(p.name for p in host.unit.parent.iterdir()) == [UNIT]
    out = capsys.readouterr().out
    assert "FAIL   unit put back as it was" in out and "NOT fully rolled back" in out


def test_the_unit_is_on_the_disk_before_systemd_is_told_to_read_it(tmp_path, monkeypatch):
    host = Host(tmp_path, monkeypatch, previous=OLD_UNIT)
    log: list[tuple] = []
    real_fsync = os.fsync

    def fsync(fd):
        info = os.fstat(fd)
        log.append(("fsync", info.st_ino))
        return real_fsync(fd)

    told = host.systemctl

    def systemctl(*args):
        log.append(("systemctl", *args))
        return told(*args)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(host.installer, "systemctl", systemctl)
    assert host.installer.install(8000) == 0
    monkeypatch.undo()
    reload_at = log.index(("systemctl", "daemon-reload"))
    assert ("fsync", os.stat(host.unit).st_ino) in log[:reload_at], "the unit's bytes, before systemd reads them"
    assert ("fsync", os.stat(host.unit.parent).st_ino) in log[:reload_at], "and its name in the folder"
    assert host.unit.read_text() == NEW_UNIT and oct(host.unit.stat().st_mode & 0o777) == "0o644"
