"""The remote lane runner must not mistake a silent LTspice exit for a finished run.

On the remote host a launched LTspice can exit 0 having written nothing (the sshd
Job Object drops anything past its third live child, and startup sometimes just
handed off), and it can also stay alive at ~0 CPU. Artifact presence cannot be the
liveness signal: the ASCII raw stays 0 bytes until the run ends, and the .log is
written once at startup. These tests pin the state machine that decides between
"still running", "relaunch" and "done", plus the hash that ignores the volatile
Title/Date header lines.

The process and CPU probes are injected, so nothing here needs LTspice or Windows.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from remote_lanes import MAX_ATTEMPTS, artifact_paths, body_hash, check_lane, prepare_lanes


class FakeProcess:
    """Just enough of subprocess.Popen for the state machine."""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.alive = True
        self.killed = False

    def poll(self) -> int | None:
        return None if self.alive else 0

    def kill(self) -> None:
        self.alive = False
        self.killed = True

    def wait(self) -> int:
        self.alive = False
        return 0


def new_state(proc, now: float = 0.0, cpu: float = 0.0) -> dict:
    return {"proc": proc, "attempts": 1, "started": now, "cpu": cpu, "cpu_at": now,
            "when": None, "done": False, "failed": False, "kills": 0, "finish": None}


def test_body_hash_ignores_the_two_volatile_header_lines(tmp_path: Path) -> None:
    raw = tmp_path / "deck.raw"
    raw.write_bytes(b"Title: run A\nDate: now\n1\t2\t3\n4\t5\t6\n")
    assert body_hash(raw) == hashlib.sha256(b"1\t2\t3\n4\t5\t6\n").hexdigest()


def test_artifacts_sit_next_to_the_deck(tmp_path: Path) -> None:
    assert artifact_paths(str(tmp_path / "deck.cir")) == (
        str(tmp_path / "deck.raw"), str(tmp_path / "deck.log"))


def test_a_silent_exit_relaunches_and_then_finishes(tmp_path: Path) -> None:
    deck = tmp_path / "deck.cir"
    deck.write_text("* deck\n")
    stale = FakeProcess()
    stale.alive = False  # exited without writing anything
    state = new_state(stale)
    assert check_lane(state, str(deck), now=10.0, t0=0.0) == "wait"
    assert state["when"] == pytest.approx(13.0)

    launched = FakeProcess(pid=99)
    assert check_lane(state, str(deck), now=14.0, t0=0.0,
                      launcher=lambda _: launched) == "run"
    assert state["attempts"] == 2

    Path(artifact_paths(str(deck))[0]).write_bytes(b"raw\n")
    Path(artifact_paths(str(deck))[1]).write_bytes(b"log\n")
    launched.alive = False
    assert check_lane(state, str(deck), now=250.0, t0=0.0) == "done"
    assert state["finish"] == pytest.approx(250.0)


def test_a_process_that_stops_burning_cpu_is_killed_and_relaunched(tmp_path: Path) -> None:
    deck = tmp_path / "deck.cir"
    deck.write_text("* deck\n")
    proc = FakeProcess()
    state = new_state(proc, now=0.0, cpu=5.0)
    frozen = lambda _pid: 5.0
    assert check_lane(state, str(deck), now=50.0, t0=0.0, cpu_of=frozen) == "run"
    assert check_lane(state, str(deck), now=100.0, t0=0.0, cpu_of=frozen) == "wait"
    assert proc.killed
    assert state["kills"] == 1


def test_a_process_that_keeps_burning_cpu_is_left_alone(tmp_path: Path) -> None:
    deck = tmp_path / "deck.cir"
    deck.write_text("* deck\n")
    proc = FakeProcess()
    state = new_state(proc, now=0.0, cpu=0.0)
    burning = lambda _pid: 500.0
    assert check_lane(state, str(deck), now=120.0, t0=0.0, cpu_of=burning) == "run"
    assert not proc.killed
    assert state["kills"] == 0


def test_giving_up_after_max_attempts(tmp_path: Path) -> None:
    deck = tmp_path / "deck.cir"
    deck.write_text("* deck\n")
    state = new_state(FakeProcess(pid=7))
    state["proc"] = None
    state["when"] = 0.0
    state["attempts"] = MAX_ATTEMPTS
    assert check_lane(state, str(deck), now=1.0, t0=0.0) == "failed"


def test_lanes_are_siblings_one_level_under_sim(tmp_path: Path) -> None:
    source = tmp_path / "sim" / "v3"
    source.mkdir(parents=True)
    (source / "deck.cir").write_text("* deck\n")
    lanes = prepare_lanes(str(tmp_path), str(Path("sim") / "v3" / "deck.cir"), 3)
    assert len(lanes) == 3
    for lane in lanes:
        path = Path(lane)  # the copied deck file; its folder is the lane
        assert path.parent.parent == tmp_path / "sim"
        assert path.read_text() == "* deck\n"
