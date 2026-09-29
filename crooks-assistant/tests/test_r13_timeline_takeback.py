"""Round 13, RC-7 (O1-01, R9-A3b-F-A3B-SHORT-WRITE): a timeline write that fails part way takes
back only its own part-line, and a take-back that fails is counted, never written over.

`_take_back` cut the file to its size at the time, less the bytes of the part-line. A second
writer's whole line appended in between moved the end of the file, so the cut removed the end of
that line (counted written by its writer) and left this writer's part-line in place. And when the
cut failed and the newline that ends a part-line failed too, the next batch was glued onto the
part-line and counted written.

Now each append holds the timeline file alone while it writes (an exclusive lock on the file),
records where it began, and cuts back to there plus the whole lines it wrote. A part-line that can
be neither cut nor ended leaves the file broken for this process: what would follow it is counted
dropped, and the session's stop says its count is not final.
"""

from __future__ import annotations

import errno
import os
import threading

from app.observability import timeline as timeline_module
from app.observability.session import TestSessions
from app.observability.timeline import Timeline, read_events

NOW = 1_790_000_000.0


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _lines(path) -> list[bytes]:
    return path.read_bytes().split(b"\n")


def test_a_second_writer_s_line_is_never_cut_by_this_writer_s_take_back(tmp_path, monkeypatch):
    """Batch one goes down short and then fails. Between the failure and the take-back, a second
    writer (another backend on the same session folder) appends a whole line of its own."""
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    ours = Timeline(store, clock=clock)
    theirs = Timeline(TestSessions(tmp_path, clock=clock), clock=clock)
    session = ours.start("two writers")
    assert ours.flush()
    path = store.timeline_path(session)
    other_line = timeline_module.json.dumps({"kind": "from_the_other_writer", "ts": NOW, "text": "y" * 40})

    real_write = os.write
    state = {"calls": 0, "armed": False}
    other_done = threading.Event()

    def other_writer():
        written, dropped = theirs._append(path, [other_line])
        state["other"] = (written, dropped)
        other_done.set()

    def failing(fd, data):
        if not state["armed"]:
            return real_write(fd, data)
        state["calls"] += 1
        if state["calls"] == 1:
            return real_write(fd, bytes(data[: len(data) // 2 + 7]))  # two lines and part of a third, then …
        # … the disk fails, and in that moment the other writer appends.
        state["armed"] = False
        runner = threading.Thread(target=other_writer)
        runner.start()
        other_done.wait(0.5)                  # held off by our lock now; free to land before
        state["runner"] = runner
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(timeline_module.os, "write", failing)
    state["armed"] = True
    written, dropped = ours._append(path, [timeline_module.json.dumps({"kind": "ours", "n": n, "text": "x" * 60})
                                           for n in range(4)])
    state["runner"].join(5)
    monkeypatch.undo()
    assert state["other"] == (1, 0), "the other writer counted its line written"
    raw = _lines(path)
    assert raw[-1] == b"", "the file ends at the end of a line"
    assert all(line.startswith(b"{") and line.endswith(b"}") for line in raw[:-1]), raw
    kinds = [e["kind"] for e in read_events(path)]
    assert kinds.count("from_the_other_writer") == 1, "its line is on the disk whole"
    assert kinds.count("ours") == written and written + dropped == 4


def test_a_part_line_that_can_be_neither_cut_nor_ended_stops_the_file_and_the_stop_says_so(tmp_path, monkeypatch):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    session = timeline.start("disk failing")
    assert timeline.flush()
    path = store.timeline_path(session)
    before = path.read_bytes()

    real_write = os.write
    state = {"calls": 0}

    def failing(fd, data):
        state["calls"] += 1
        if state["calls"] == 1:
            return real_write(fd, bytes(data[:10]))                    # a part of the first line
        raise OSError(errno.EIO, "Input/output error")                 # then nothing, not even "\n"

    def no_truncate(fd, length):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(timeline_module.os, "write", failing)
    monkeypatch.setattr(timeline_module.os, "ftruncate", no_truncate)
    written, dropped = timeline._append(path, [timeline_module.json.dumps({"kind": "turn_started", "n": 1})])
    monkeypatch.undo()
    assert (written, dropped) == (0, 1)
    assert path.read_bytes().startswith(before) and not path.read_bytes().endswith(b"\n"), "the part-line is there"

    # With the disk answering again, nothing is glued onto that part-line and counted.
    assert timeline._append(path, [timeline_module.json.dumps({"kind": "turn_finished"})]) == (0, 1)
    assert not path.read_bytes().endswith(b"}\n")
    timeline.emit("turn_started", n=2)
    assert timeline.flush(timeout_s=5)
    assert timeline.counts["dropped"] >= 1
    timeline.stop()
    assert timeline.stop_settled is False, "a file that ends in a part-line is not a final count"


def test_a_part_line_that_cannot_be_cut_is_ended_and_the_file_goes_on(tmp_path, monkeypatch):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    session = timeline.start("no truncate")
    assert timeline.flush()
    path = store.timeline_path(session)
    real_write = os.write
    state = {"calls": 0}

    def failing(fd, data):
        state["calls"] += 1
        if state["calls"] == 1:
            return real_write(fd, bytes(data[:10]))
        if state["calls"] == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(fd, data)                                    # the newline goes down

    def no_truncate(fd, length):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(timeline_module.os, "write", failing)
    monkeypatch.setattr(timeline_module.os, "ftruncate", no_truncate)
    assert timeline._append(path, [timeline_module.json.dumps({"kind": "turn_started"})]) == (0, 1)
    monkeypatch.undo()
    assert path.read_bytes().endswith(b"\n")
    assert timeline._append(path, [timeline_module.json.dumps({"kind": "turn_finished"})]) == (1, 0)
    assert path.read_bytes().endswith(b'{"kind": "turn_finished"}\n'), "a whole line of its own"
    timeline.stop()
    assert timeline.stop_settled is True
