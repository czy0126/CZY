"""Execute the PROT-03 matched 50 V/120 A A/B cases (PR 29, document 16).

``tools/run_d1_50v_matched_cases.ps1`` is the authoritative procedure.  This
module is its line-for-line port because of two environment facts: a PowerShell
execution policy can forbid running ``.ps1`` files on the analysis machine at
all, and the offline pytest suite cannot exercise PowerShell.  The four decks,
the deck gates, the staging directory (``sim/v3``, so ``../../models`` still
resolves), the archive layout, the manifest and every refusal are the same.

The runner checks *duration only*.  A raw that reaches 320 us does not show
pre-fault pairing, gate waveforms or hardware safety -- the three manifest
flags stay false by construction.

``--variant`` ports the PR 30 solver sweep: the same four roles taken from
``sim/v3/d1_prot03_{shunt_2f,shunt_5f,shunt_10f}_<role>.cir``, which differ
from the published decks only in ``.options cshunt``.  Control and candidate
must come from the same variant; the gate refuses a deck whose cshunt is not
the variant's, so a 1 fF candidate can never be paired with a 5 fF control.
The manifest records the variant -- a deliberate addition to the port, because
an archived sweep run must never be mistaken for published 1 fF evidence.

Usage:
    python tools/run_d1_50v_matched_cases.py                     # dry run
    python tools/run_d1_50v_matched_cases.py --variant shunt_2f  # sweep dry run
    python tools/run_d1_50v_matched_cases.py --execute --run-id d1_50v_001 \\
        --ltspice D:/ADI/LTspice/LTspice.exe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ascii_raw_window import last_time

ROOT = Path(__file__).resolve().parent.parent
SIM = ROOT / "sim/v3"
DEFAULT_ARCHIVE = ROOT / "out/d1_50v"

DECKS = {
    "A_CONTROL": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v_thrmute_control.cir",
    "A_CANDIDATE": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.cir",
    "B_CONTROL": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_thrmute_control.cir",
    "B_CANDIDATE": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir",
}

# The value is the cshunt the variant's decks must carry.  "published" is the
# frozen 1 fF set; the others are PR 30's generated numerical diagnostics.
VARIANTS = {
    "published": "1e-15",
    "shunt_2f": "2e-15",
    "shunt_5f": "5e-15",
    "shunt_10f": "1e-14",
}
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,35}$")


def decks_for(variant: str) -> dict[str, str]:
    """Deck names for one variant; a sweep role keeps the published role name."""
    if variant not in VARIANTS:
        raise KeyError(f"unknown variant {variant!r}")
    if variant == "published":
        return dict(DECKS)
    return {case: f"d1_prot03_{variant}_{case}.cir" for case in DECKS}


def gates(required_cshunt: str) -> tuple[tuple[re.Pattern[str], str], ...]:
    """Each gate names why it exists in the error, not just that it failed."""
    return (
        (re.compile(r"\.options\s+plotwinsize=0\s+method=gear\s+cshunt=" + re.escape(required_cshunt)),
         "solver options changed"),
        (re.compile(r"\.tran\s+0\s+2320u\s+2000u\s+5n\s+uic"), "320 us save window changed"),
        (re.compile(r"\.include\s+\.\./\.\./models/"), "model includes changed"),
    )


def sha256(path: Path) -> str:
    """Hash a file in blocks: the raws are gigabytes and must not be loaded."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def deck_text(case: str, variant: str = "published") -> str:
    decks = decks_for(variant)
    if case not in decks:
        raise KeyError(f"unknown case {case}")
    return (SIM / decks[case]).read_text(encoding="utf-8")


def validate_deck(case: str, text: str, variant: str = "published") -> None:
    for pattern, reason in gates(VARIANTS[variant]):
        if not pattern.search(text):
            raise ValueError(f"{case}: {reason}")


def check_run_id(run_id: str) -> str:
    if not RUN_ID.match(run_id):
        raise SystemExit(f"run id {run_id!r} needs 3..36 permitted characters")
    return run_id


def find_ltspice(explicit: str | None) -> Path:
    candidates = [Path(explicit)] if explicit else []
    for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [Path(base) / "ADI/LTspice/LTspice.exe",
                           Path(base) / "Programs/ADI/LTspice/LTspice.exe"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("need an installed LTspice.exe; pass --ltspice")


def manifest(run_id: str, results: list[dict], variant: str = "published") -> dict:
    """The three false flags are the point: duration is not a safety result."""
    return {"kind": "LTSIM_ONLY", "run_id": run_id, "variant": variant,
            "required_cshunt_farads": VARIANTS[variant],
            "pre_fault_1mV_paired_verified": False,
            "ten_physical_gate_shutdown_verified": False,
            "fabrication_approved": False,
            "cases": results}


def solver_reported_completion(log_bytes: bytes) -> bool:
    """LTspice prints "Total elapsed time" even when the solver gives up, so the
    marker alone would call a failed run finished."""
    return b"Total elapsed time" in log_bytes and b"Simulation Failed" not in log_bytes


def classify(raw: Path, log: Path) -> dict[str, object]:
    """How far a run got, read from the files it left -- including a failed one."""
    tail_us = round(last_time(raw) * 1e6, 6)
    return {"solver_finished": solver_reported_completion(log.read_bytes()),
            "tail_us": tail_us, "reached_320us": tail_us >= 319.999}


def run_case(case: str, stage: Path, ltspice: Path, case_dir: Path, timeout_s: float,
             decks: dict[str, str] | None = None) -> dict:
    """Stage, run, classify and archive one case; never raise on solver failure."""
    decks = DECKS if decks is None else decks
    raw, log = stage.with_suffix(".raw"), stage.with_suffix(".log")
    source = SIM / decks[case]
    record = {"case": case, "source": decks[case], "source_sha256": sha256(source),
              "state": "NOT_RUN", "solver_finished": False, "tail_us": None,
              "reached_320us": False, "raw_sha256": None, "log_sha256": None, "reason": ""}
    try:
        if any(path.exists() for path in (stage, raw, log)):
            raise FileExistsError(f"refuse overwrite {stage}")
        shutil.copyfile(source, stage)
        completed = subprocess.run([str(ltspice), "-b", "-ascii", str(stage)],
                                   capture_output=True, timeout=timeout_s)
        have_files = raw.is_file() and log.is_file()
        # Classify before looking at the return code: a hard convergence failure
        # still leaves a readable prefix, and where it stopped is the evidence.
        if have_files:
            record.update(classify(raw, log))
        if completed.returncode != 0:
            raise RuntimeError(f"LTspice exit {completed.returncode}"
                               + ("" if have_files else "; no raw/log"))
        if not have_files:
            raise RuntimeError("no raw/log")
        record["state"] = ("DURATION_ONLY_PASS" if record["solver_finished"] and record["reached_320us"]
                           else "INCOMPLETE_PREFIX")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        record["state"] = "FAILED_KEEP_EVIDENCE"
        record["reason"] = str(error)
    finally:
        for path in (stage, raw, log):
            if path.is_file():
                if path.suffix == ".raw":
                    record["raw_sha256"] = sha256(path)
                if path.suffix == ".log":
                    record["log_sha256"] = sha256(path)
                # shutil.move, not Path.replace: an archive root can sit on
                # another volume and os.replace refuses to cross one.
                shutil.move(str(path), str(case_dir / path.name))
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--ltspice", default="")
    parser.add_argument("--cases", nargs="+", default=list(DECKS))
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="published")
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--timeout-s", type=float, default=1800.0)
    args = parser.parse_args(argv)
    decks = decks_for(args.variant)
    for case in args.cases:
        if case not in decks:
            raise SystemExit(f"unknown case {case}")
        validate_deck(case, deck_text(case, args.variant), args.variant)
    if not args.execute:
        for case in args.cases:
            print(f"DRY_RUN {case} {decks[case]}")
        print("NO NEW RAW. Invoke --execute --run-id unique_tag --ltspice exe_path.")
        return 0
    archive = args.archive_root / check_run_id(args.run_id)
    ltspice = find_ltspice(args.ltspice)
    if archive.exists():
        raise SystemExit(f"refuse overwrite archive {archive}")
    archive.mkdir(parents=True)
    results = []
    for case in args.cases:
        stage = SIM / f"d1_{args.run_id}_{case}.cir"
        (archive / case).mkdir()
        results.append(run_case(case, stage, ltspice, archive / case, args.timeout_s, decks))
        print(f"{case} {results[-1]['state']} t_last={results[-1]['tail_us']}us")
    report = archive / "run_manifest.json"
    report.write_text(json.dumps(manifest(args.run_id, results, args.variant), ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    incomplete = [record["case"] for record in results if record["state"] != "DURATION_ONLY_PASS"]
    if incomplete:
        raise SystemExit(f"incomplete runs retained at {report}: {', '.join(incomplete)}")
    print("Only 320us completeness checked; paired pre-fault, Vgs/Id and hardware safety NOT VERIFIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
