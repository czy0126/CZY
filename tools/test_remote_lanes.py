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
import json
from pathlib import Path

import remote_lanes as runner

import pytest

from remote_lanes import MAX_ATTEMPTS, artifact_paths, body_hash, check_lane, prepare_lanes, completed_artifacts


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

    write_completed_artifacts(deck)
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


def write_completed_artifacts(deck: Path, *, value: bytes = b"42") -> None:
    raw, log = artifact_paths(str(deck))
    Path(raw).write_bytes(
        b"Title: test\nDate: now\nPlotname: Transient Analysis\n"
        b"Flags: real\nNo. Variables: 2\nNo. Points: 1\n"
        b"Variables:\n0 time time\n1 V(out) voltage\nValues:\n"
        b"0\t0\n" + value + b"\n"
    )
    Path(log).write_text(
        "LTspice 26.0.2 for Windows\nTotal elapsed time: 0.125 seconds.\n",
        encoding="utf-8",
    )


def test_completed_artifacts_requires_real_ascii_points_and_finished_log(tmp_path: Path):
    deck = tmp_path / "deck.cir"
    deck.write_text("* test")
    raw, log = artifact_paths(str(deck))
    assert completed_artifacts(str(deck))[0] is False
    Path(raw).write_bytes(b"")
    Path(log).write_text("Start Time: now")
    assert completed_artifacts(str(deck))[0] is False
    write_completed_artifacts(deck)
    assert completed_artifacts(str(deck))[0]
    Path(log).write_text("Start Time: now\n")
    assert "completion" in completed_artifacts(str(deck))[1]
    write_completed_artifacts(deck)
    Path(raw).write_bytes(b"Title: ok\nDate: now\n")
    assert "ASCII raw" in completed_artifacts(str(deck))[1]
    write_completed_artifacts(deck)
    Path(raw).write_bytes(Path(raw).read_bytes().replace(b"No. Points: 1", b"No. Points: 0"))
    assert not completed_artifacts(str(deck))[0]
    write_completed_artifacts(deck)
    Path(log).write_text("Total elapsed time: 1 seconds.\nFatal Error: solver failed\n")
    assert not completed_artifacts(str(deck))[0]


def test_process_nonzero_returncode_is_never_success_even_with_complete_artifacts(tmp_path: Path):
    deck = tmp_path / "deck.cir"
    deck.write_text("* test")
    write_completed_artifacts(deck)
    proc = FakeProcess()
    proc.alive = False
    proc.poll = lambda: 2
    state = new_state(proc)
    assert check_lane(state, str(deck), now=20, t0=0) == "wait"
    assert not state["done"]
    assert "exited 2" in state["last_failure"]


def test_empty_raw_does_not_exempt_stalled_solver_from_watchdog(tmp_path: Path):
    deck = tmp_path / "deck.cir"
    deck.write_text("* test")
    raw, log = artifact_paths(str(deck))
    Path(raw).write_bytes(b"")
    Path(log).write_text("Start Time: now")
    proc = FakeProcess()
    state = new_state(proc, now=0, cpu=0)
    frozen = lambda _pid: 0.0
    assert check_lane(state, str(deck), now=100, t0=0, cpu_of=frozen) == "wait"
    assert proc.killed
    assert state["kills"] == 1
    assert "stalled" in state["last_failure"]


def test_recent_raw_growth_prevents_watchdog_killing_busy_writer(tmp_path: Path):
    deck = tmp_path / "deck.cir"
    deck.write_text("* test")
    raw, _ = artifact_paths(str(deck))
    Path(raw).write_bytes(b"x" * 1024)
    proc = FakeProcess()
    state = new_state(proc, now=0, cpu=0)
    assert check_lane(state, str(deck), now=100, t0=0,
                      cpu_of=lambda _: 0.0) == "run"
    assert not proc.killed
    assert state["raw_size"] == 1024
    assert state["cpu_at"] == 100
    assert check_lane(state, str(deck), now=200, t0=0,
                      cpu_of=lambda _: 0.0) == "wait"
    assert proc.killed


def test_prepare_lanes_never_reuses_an_old_run_directory(tmp_path: Path):
    source = tmp_path / "sim" / "v3"
    source.mkdir(parents=True)
    (source / "deck.cir").write_text("first")
    first = prepare_lanes(str(tmp_path), "sim/v3/deck.cir", 2)
    (Path(first[0]).parent / "deck.raw").write_bytes(b"OLD_DATA_PRESERVE")
    second = prepare_lanes(str(tmp_path), "sim/v3/deck.cir", 2)
    assert not set(first).intersection(second)
    assert (Path(first[0]).parent / "deck.raw").read_bytes() == b"OLD_DATA_PRESERVE"


def test_prepare_lanes_rejects_traversal_nonexistent_and_invalid_counts(tmp_path: Path):
    source = tmp_path / "sim" / "v3"
    source.mkdir(parents=True)
    (source / "deck.cir").write_text("*test")
    for deck in ("../sim/v3/deck.cir", "sim/v3/../deck.cir",
                 r"sim\v3\..\deck.cir", r"sim\..\v3\deck.cir",
                 "/tmp/sim/v3/deck.cir", "sim/v3/missing.cir", "sim/v3/deck.raw"):
        with pytest.raises(ValueError):
            prepare_lanes(str(tmp_path), deck, 1)
    for count in (0, -1, 999):
        with pytest.raises(ValueError):
            prepare_lanes(str(tmp_path), "sim/v3/deck.cir", count)


def test_run_rejects_hash_mismatch_even_if_all_processes_complete(tmp_path: Path, monkeypatch):
    source = tmp_path / "sim" / "v3"
    source.mkdir(parents=True)
    source_deck = source / "deck.cir"
    source_deck.write_text("*test")
    reference = tmp_path / "ref.raw"
    write_completed_artifacts(tmp_path / "ref.cir", value=b"DIFFERENT")
    outputs = []
    def prepare(root, deck, n):
        for index in range(n):
            lane = tmp_path / f"mock_{index}"
            lane.mkdir()
            d = lane / "deck.cir"
            d.write_text("*test")
            write_completed_artifacts(d, value=b"ACTUAL")
            outputs.append(str(d))
        return outputs
    monkeypatch.setattr(runner, "prepare_lanes", prepare)
    proc = FakeProcess()
    proc.alive = False
    monkeypatch.setattr(runner, "_launch", lambda _: proc)
    monkeypatch.setattr(runner, "cpu_seconds", lambda _: 0.0)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    report = tmp_path / "out.json"
    exitcode = runner.run(str(tmp_path), "sim/v3/deck.cir", 2, 0,
                          "ref.raw", str(report))
    result = json.loads(report.read_text(encoding="utf-8"))
    assert exitcode == 1
    assert result["ok"] == 2
    assert result["all_same"] is False
    assert set(result["reference_mismatch_lanes"]) == {"0", "1"} or set(result["reference_mismatch_lanes"]) == {0, 1}
