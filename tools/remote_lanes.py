"""Run several LTspice decks concurrently — this script executes ON the remote host.

The project runs all simulations on the `winsrv` remote (see CLAUDE.md, "远端仿真主机").
Two facts shape this runner:

* sshd's Job Object allows only 3 live LTspice children and silently drops the rest,
  so the runner itself must be started through `schtasks` (outside that Job Object).
* A launched LTspice can exit 0 having written nothing, or stay alive at ~0 CPU. The
  ASCII raw stays 0 bytes until the run ends and the .log is written once at startup,
  so artifact presence says nothing about liveness — the watchdog watches process CPU.

Every lane is a sibling of the source deck directory, because decks `.include
../../models/...` and only resolve one level under `sim`.

Usage (on the remote host):
    python -I tools/remote_lanes.py --root C:\\work\\stage --deck sim\\v3\\deck.cir --jobs 6
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import tempfile
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from typing import Callable

LTSPICE = r"D:\ADI\LTspice-26.0.2\LTspice.exe"
CPU_STALL_S = 90.0
CPU_MIN_GROWTH_S = 1.0
MAX_ATTEMPTS = 5
POLL_S = 2.0
QUERY_LIMITED_INFORMATION = 0x1000
FILETIME_TICKS_PER_S = 10000000


def body_hash(path: str) -> str:
    """SHA-256 of an ASCII raw with the two volatile header lines dropped."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for index, line in enumerate(handle):
            if index >= 2:
                digest.update(line)
    return digest.hexdigest()


def artifact_paths(deck: str) -> tuple[str, str]:
    """The .raw and .log LTspice writes next to a deck."""
    base = deck[:-4] if deck.lower().endswith(".cir") else deck
    return base + ".raw", base + ".log"


def completed_artifacts(deck: str) -> tuple[bool, str]:
    """Require a finished *ASCII* transient raw and LTspice completion marker.

    A 0-byte raw + startup log existed on the remote before solver success.
    File existence and process returncode 0 are NOT enough. This is a cheap
    header/completion preflight, not an exhaustive parse of every raw sample.
    """
    raw, log = artifact_paths(deck)
    if not os.path.isfile(raw) or not os.path.isfile(log):
        return False, "missing raw/log"
    if os.path.getsize(raw) == 0 or os.path.getsize(log) == 0:
        return False, "empty raw/log"
    try:
        with open(raw, "rb") as stream:
            prefix = stream.read(512 * 1024)
        header = re.search(rb"(?m)^No\. Points:\s*([0-9]+)\s*$", prefix)
        variables = re.search(rb"(?m)^No\. Variables:\s*([0-9]+)\s*$", prefix)
        values = re.search(rb"(?m)^Values:\s*\r?\n", prefix)
        if (not header or int(header.group(1)) < 1 or
                not variables or int(variables.group(1)) < 1 or
                not values):
            return False, "ASCII raw lacks nonzero points/variables or Values header"
        if not prefix[values.end():].strip():
            return False, "ASCII raw has no waveform data after Values"
        with open(log, "r", encoding="utf-8", errors="replace") as stream:
            logfile = stream.read()
        if re.search(r"(?im)^\s*(?:fatal error|error(?: in line)?|internal error)\s*:", logfile):
            return False, "LTspice log contains an error"
        if not re.search(r"(?im)^Total elapsed time:\s*[0-9.]+\s+seconds?\.", logfile):
            return False, "LTspice log lacks completion-time marker"
    except OSError as error:
        return False, f"cannot inspect artifacts: {error}"
    return True, "validated completed raw header and LTspice log"


def cpu_seconds(pid: int) -> float | None:
    """Total CPU time of a process in seconds, or None when it is gone."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    times = [wintypes.FILETIME() for _ in range(4)]
    ok = kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times])
    kernel32.CloseHandle(handle)
    if not ok:
        return None

    def ticks(field: wintypes.FILETIME) -> int:
        return field.dwHighDateTime << 32 | field.dwLowDateTime

    return (ticks(times[2]) + ticks(times[3])) / FILETIME_TICKS_PER_S


def clear_artifacts(deck: str) -> None:
    for path in artifact_paths(deck):
        if os.path.exists(path):
            os.remove(path)


def _launch(deck: str) -> subprocess.Popen:
    return subprocess.Popen([LTSPICE, "-b", "-ascii", os.path.basename(deck)],
                            cwd=os.path.dirname(deck),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check_lane(state: dict, deck: str, now: float, t0: float,
               cpu_of: Callable[[int], float | None] = cpu_seconds,
               launcher: Callable[[str], subprocess.Popen] = _launch) -> str:
    """Advance one lane; returns 'run', 'wait', 'done' or 'failed'."""
    if state["done"] or state["failed"]:
        return "done" if state["done"] else "failed"
    proc = state["proc"]
    raw_path, log_path = artifact_paths(deck)
    if proc is not None:
        exitcode = proc.poll()
        if exitcode is not None:
            complete, reason = completed_artifacts(deck)
            if exitcode == 0 and complete:
                state["done"] = True
                state["finish"] = now - t0
                return "done"
            state["last_failure"] = (f"LTspice exited {exitcode}; " + reason)
            state["proc"] = None
            state["when"] = now + 3
            return "wait"
        cpu = cpu_of(proc.pid)
        if cpu is None:
            return "run"
        size = os.path.getsize(raw_path) if os.path.isfile(raw_path) else 0
        if size > state.get("raw_size", 0):
            # A writer may be busy flushing gigabytes of RAW while CPU is idle.
            # Treat byte growth as work, but an empty/unchanged file is NOT liveness.
            state["raw_size"], state["cpu_at"] = size, now
        if cpu - state["cpu"] >= CPU_MIN_GROWTH_S:
            state["cpu"], state["cpu_at"] = cpu, now
        elif now - state["cpu_at"] > CPU_STALL_S:
            proc.kill()
            proc.wait()
            state["kills"] += 1
            state["last_failure"] = "CPU and RAW output remained stalled"
            state["proc"] = None
            state["when"] = now + 3
            return "wait"
        return "run"
    if state["when"] is None or now < state["when"]:
        return "wait"
    if state["attempts"] >= MAX_ATTEMPTS:
        state["failed"] = True
        return "failed"
    clear_artifacts(deck)
    proc = launcher(deck)
    state.update({"proc": proc, "attempts": state["attempts"] + 1, "started": now,
                  "cpu": cpu_of(proc.pid) or 0.0, "cpu_at": now, "raw_size": 0,
                  "when": None})
    return "run"


def prepare_lanes(root: str, deck: str, count: int) -> list[str]:
    """Copy the deck into `count` lane directories that are siblings of its own folder.

    Decks `.include ../../models/...`, which only resolves two levels below the
    staging root — so a lane must sit at <root>/sim/lane* when the deck lives at
    <root>/sim/v3/deck.cir.
    """
    if count < 1 or count > 32:
        raise ValueError("concurrent lane count must be between 1 and 32")
    if os.path.isabs(deck) or ".." in deck.replace(chr(92), "/").split("/"):
        raise ValueError("deck must be relative to --root without parent traversal")
    source = os.path.abspath(os.path.join(root, deck))
    root_abs = os.path.abspath(root)
    if os.path.commonpath([source, root_abs]) != root_abs:
        raise ValueError("deck path escapes the staging root")
    if not source.lower().endswith(".cir") or not os.path.isfile(source):
        raise ValueError("deck must be an existing .cir file")
    lane_parent = os.path.dirname(os.path.dirname(source))
    if os.path.basename(lane_parent).lower() != "sim":
        raise ValueError("deck must be directly under <root>/sim/<case>/")
    lanes = []
    for index in range(count):
        # Never reuse a lane: old .raw/.log files are precious experimental
        # evidence and clear_artifacts() must not destroy a prior run.
        lane = tempfile.mkdtemp(prefix=f"lane_{index}_", dir=lane_parent)
        target = os.path.join(lane, os.path.basename(deck))
        shutil.copy2(source, target)
        lanes.append(target)
    return lanes


def run(root: str, deck: str, count: int, stagger: float, reference: str | None,
        report_path: str) -> int:
    if not (0 <= stagger <= 60):
        raise ValueError("stagger must be between 0 and 60 seconds")
    lanes = prepare_lanes(root, deck, count)
    anchor = time.time()
    states = {}
    for index, lane in enumerate(lanes):
        proc = _launch(lane)
        stale = time.time()
        states[index] = {"proc": proc, "attempts": 1, "started": stale,
                         "cpu": cpu_seconds(proc.pid) or 0.0, "cpu_at": stale,
                         "when": None, "done": False, "failed": False,
                         "kills": 0, "finish": None, "raw_size": 0,
                         "last_failure": None}
        time.sleep(stagger)
    last_write = 0.0
    while True:
        now = time.time()
        status = {i: check_lane(s, lanes[i], now, anchor) for i, s in states.items()}
        if all(value in ("done", "failed") for value in status.values()):
            break
        if now - last_write > 15:
            last_write = now
            with open(report_path, "w") as handle:
                json.dump({"elapsed_s": round(now - anchor, 1), "status": status}, handle)
        time.sleep(POLL_S)
    wall = time.time() - anchor
    done = {i: body_hash(artifact_paths(lanes[i])[0]) for i, s in states.items() if s["done"]}
    expected = body_hash(os.path.join(root, reference)) if reference else None
    all_complete = len(done) == count
    all_match_reference = (expected is not None and all_complete
                           and all(value == expected for value in done.values()))
    result = {
        "n": count,
        "wall_s": round(wall, 1),
        "ok": sum(1 for s in states.values() if s["done"]),
        "throughput_per_h": round(len(done) / wall * 3600, 1),
        "launches": sum(s["attempts"] for s in states.values()),
        "watchdog_kills": sum(s["kills"] for s in states.values()),
        "finish_s": {i: round(s["finish"], 1) for i, s in states.items() if s["finish"]},
        "hashes": done,
        "all_same": all_match_reference,
        "reference_mismatch_lanes": (
            [i for i, value in done.items() if value != expected]
            if expected is not None else []),
        "failed_lanes": [i for i, state in states.items() if state["failed"]],
        "last_failures": {i: state.get("last_failure") for i, state in states.items()
                          if state.get("last_failure")},
        "reference": reference,
    }
    with open(report_path, "w") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "hashes"}))
    return 0 if all_complete and (expected is None or all_match_reference) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="staging root that contains sim/ and models/")
    parser.add_argument("--deck", required=True, help="deck path relative to --root")
    parser.add_argument("--jobs", type=int, default=6, help="number of concurrent lanes")
    parser.add_argument("--stagger", type=float, default=3.0, help="seconds between launches")
    parser.add_argument("--reference", help="raw path relative to --root to compare hashes against")
    parser.add_argument("--report", help="status/report JSON path (default <root>/lanes_<tag>.json)")
    args = parser.parse_args(argv)
    report = args.report or os.path.join(args.root, "lanes_%s.json" % time.strftime("%H%M%S"))
    return run(args.root, args.deck, args.jobs, args.stagger, args.reference, report)


if __name__ == "__main__":
    sys.exit(main())
