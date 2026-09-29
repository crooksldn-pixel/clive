"""Round 13, S6-01 / T4-02 / T6-01: an objective's three-step write is durable in order.

A change to an objective goes down as three steps (`ObjectiveStore._write`): the new design as a
pending file, the record, then the pending design becomes the design. The order is what makes a
write cut short read as the whole old objective or the whole new one. It held only for a write
cut short by an exception: nothing was flushed to the disk, so after a power cut the record of
step 2 could be there while the pending design of step 1 was empty or missing. The old design
still agrees with that record by its history, so it was read instead, and the change was lost
while the record's history said it had been made.

Here: each step's file and its folder reach the disk before the next step begins, and a pending
design found damaged beside a record that has moved past the design being read is said to the
owner as an open question on the objective, never silently replaced by the old one.
"""

from __future__ import annotations

import os

import pytest

from app.objectives import store as store_module
from app.objectives.store import ObjectiveStore


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def tasks_objective(s):
    return s.create(title="Rosa and Kit's tasks", request="Give Rosa and Kit these to do later", kind="tasks",
                    tasks=[{"who": "Rosa", "text": "Steam the AW samples"}, {"who": "Kit", "text": "Update the size chart"}])


class Disk:
    """What reached the disk, in order: each fsync by the file or folder it was of (its inode, so
    a file keeps its identity through the renames), and each rename."""

    def __init__(self, monkeypatch) -> None:
        self.log: list[tuple] = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd):
            info = os.fstat(fd)
            self.log.append(("fsync", (info.st_dev, info.st_ino)))
            return real_fsync(fd)

        def replace(src, dst, *args, **kwargs):
            self.log.append(("replace", str(src), str(dst)))
            return real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(store_module.os, "fsync", fsync)
        monkeypatch.setattr(store_module.os, "replace", replace)

    @staticmethod
    def ident(path) -> tuple[int, int]:
        info = os.stat(path)
        return (info.st_dev, info.st_ino)

    def at(self, entry: tuple) -> int:
        assert entry in self.log, f"{entry} never happened: {self.log}"
        return self.log.index(entry)

    def last_fsync_before(self, ident: tuple[int, int], index: int) -> int:
        found = [i for i, e in enumerate(self.log[:index]) if e == ("fsync", ident)]
        assert found, f"nothing fsynced {ident} before step {index}: {self.log}"
        return found[-1]


def test_each_step_of_a_change_is_on_the_disk_before_the_next_begins(s, monkeypatch):
    obj = tasks_objective(s)
    disk = Disk(monkeypatch)
    s.task(obj.id, who="Kit", text="Pack the returns")

    root, folder = s.root, s.root / "design"
    record, pending, design = root / f"{obj.id}.json", folder / f"{obj.id}.next.json", folder / f"{obj.id}.json"
    step1 = next(i for i, e in enumerate(disk.log) if e[0] == "replace" and e[2] == str(pending))
    step2 = next(i for i, e in enumerate(disk.log) if e[0] == "replace" and e[2] == str(record))
    step3 = disk.at(("replace", str(pending), str(design)))
    assert step1 < step2 < step3
    # 1: the pending design's content before it is named, and its folder before the record.
    assert disk.last_fsync_before(disk.ident(design), step1) < step1
    assert step1 < disk.last_fsync_before(disk.ident(folder), step2)
    # 2: the record's content before it is named, and its folder before the design is replaced.
    assert disk.last_fsync_before(disk.ident(record), step2) < step2
    assert step2 < disk.last_fsync_before(disk.ident(root), step3)
    # 3: the design's folder once more, after it.
    assert ("fsync", disk.ident(folder)) in disk.log[step3 + 1:], "the last rename is not durable until its folder is"


def test_a_new_objective_is_on_the_disk_before_create_returns(s, monkeypatch):
    disk = Disk(monkeypatch)
    obj = tasks_objective(s)
    record = s.root / f"{obj.id}.json"
    written = disk.at(next(e for e in disk.log if e[0] == "replace" and e[2] == str(record)))
    assert disk.last_fsync_before(disk.ident(record), written) < written
    assert ("fsync", disk.ident(s.root)) in disk.log[written + 1:]
    # The folders themselves, made by this first write, are named in theirs.
    assert ("fsync", disk.ident(s.root.parent)) in disk.log
    assert ("fsync", disk.ident(s.root)) in disk.log[:written], "design/ is named in the root before it is used"


def _cut_after_the_record(s, monkeypatch, objective_id, change):
    """The machine stops after step 2: the record is the new one, the pending design never
    became the design."""
    real = os.replace
    pending = str(s.root / "design" / f"{objective_id}.next.json")
    design = str(s.root / "design" / f"{objective_id}.json")

    def replace(src, dst, *args, **kwargs):
        if str(src) == pending and str(dst) == design:
            raise OSError("the machine stopped here")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(store_module.os, "replace", replace)
    with pytest.raises(OSError):
        change()
    monkeypatch.undo()
    return s.root / "design" / f"{objective_id}.next.json"


def test_a_pending_design_lost_after_its_record_is_said_not_silently_replaced(s, monkeypatch):
    """T6-01's case: the data of the pending design did not survive (truncated to nothing), the
    record did. The old design still agrees with that record by its history. It is read, because
    it is all there is, but the owner is told on the objective itself what did not come back."""
    obj = tasks_objective(s)
    pending = _cut_after_the_record(s, monkeypatch, obj.id,
                                    lambda: s.task(obj.id, who="Kit", text="Pack the returns"))
    pending.write_bytes(b"")                     # what a power cut before a flush leaves

    got = ObjectiveStore(s.root).get(obj.id)
    assert [t["text"] for t in got.tasks] == ["Steam the AW samples", "Update the size chart"]
    question = got.open_("attention")
    assert len(question) == 1 and "Pack the returns" in question[0]["text"], got.attention
    assert "could not be read back" in question[0]["text"]
    assert got.attention_()[0] == "needs_you"
    assert got.summary()["needs_you"] == [question[0]["text"]]
    # Said once, and kept: it is on the record, so a second read (or a restart) still says it.
    again = ObjectiveStore(s.root).get(obj.id)
    assert [a["text"] for a in again.open_("attention")] == [question[0]["text"]]
    assert list((s.root / "design").glob(f"{obj.id}.*.unreadable.damaged")), "the damaged file is kept aside"


def test_a_pending_design_that_was_never_recorded_is_not_a_loss(s, monkeypatch):
    """Cut before the record: the pending design carried a change that was never made. Damaged or
    not, nothing is lost and nothing is asked."""
    obj = tasks_objective(s)
    real = os.replace
    record = str(s.root / f"{obj.id}.json")

    def replace(src, dst, *args, **kwargs):
        if str(dst) == record:
            raise OSError("the machine stopped here")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(store_module.os, "replace", replace)
    with pytest.raises(OSError):
        s.task(obj.id, who="Kit", text="Pack the returns")
    monkeypatch.undo()
    (s.root / "design" / f"{obj.id}.next.json").write_bytes(b"")
    got = ObjectiveStore(s.root).get(obj.id)
    assert got.open_("attention") == [] and len(got.tasks) == 2


def test_a_record_the_old_store_moved_on_is_not_a_loss(s):
    """After a rollback the store production rolls back to adds events and never touches the
    design: a design behind its record is normal then, and asks nothing."""
    import json

    obj = tasks_objective(s)
    record = s.root / f"{obj.id}.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["events"].append({"at": "2026-10-01T09:00:00Z", "kind": "progress", "text": "Samples ship Friday", "by": "clive"})
    record.write_text(json.dumps(data), encoding="utf-8")
    got = ObjectiveStore(s.root).get(obj.id)
    assert got.open_("attention") == [] and len(got.tasks) == 2
