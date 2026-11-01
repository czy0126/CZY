"""Publish a CURRENT-CANDIDATE manifest (review 2026-10-31 round 3, P2).

The old design/baseline/baseline_manifest.json has 304 entries and five known
hash mismatches.  It is history, not a reproduction recipe: re-running every old
bench to make it "unique" again would be busy-work.  This tool emits the small
manifest that actually reproduces the current delivery:

    decks        the round-4 generated decks + the accepted 1 ms deck
    models       the three .lib files those decks include
    scripts      the measurement / summary / test tools
    results      the JSON and markdown that quote numbers
    raws         size + mtime + saved time range (full hash only when small)

Raw time ranges come from design/v2/round4_summary.json when it exists; the raw
saved axis is rebased by Tstart, so both the raw range and the display offset
are written down (the third review asked for that explicitly).

Usage:
    python tools/current_manifest.py
    python tools/current_manifest.py --json design/v2/manifest_current_candidate.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

V3_SOURCES = {
    "deck": [
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct47.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.cir",
        # physical-configuration variants (tools/make_physical_decks.py).  They
        # are what the baseline's Lr turn decision and ripple rows quote.
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_lrmin.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.cir",
        # issue #6: the same instrumented deck saved over the first phase-
        # aligned window (133 gate periods = 662.9 us), and the same window at
        # half the max timestep so the step check covers the quoted number.
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned2n.cir",
        # issue #6 asks for 5 / 2 / 1 ns; the third leg is a .tran step change.
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned1n.cir",
        # High-output candidates (tools/make_high_output_decks.py): the 110 A
        # one was run, the other three are targets that have never run.  All
        # four say UNRUN in their header; see the 48V110A record for the
        # measured point.  The _cin deck carries the 100 A ledger's probes.
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.cir",
        "sim/v3/sr_tank_dual_v33_cold_phys.cir",
        "sim/v3/sr_tank_dual_v33_cold_oc_phys.cir",
        "sim/v3/sr_tank_dual_v33_cold_oc_lrmin.cir",
    ],
    "model": [
        "models/ucc25600_legacy_behaviour.lib",
        "models/sr_timing_v3_3.lib",
        "models/sr_device_v3.lib",
    ],
    "script": [
        "tools/ascii_raw_window.py",
        "tools/magnetics_design.py",
        "tools/draw_magnetics.py",
        "tools/make_magnetics_manifest.py",
        "tools/extract_op_point.py",
        "tools/thermal_precheck.py",
        "tools/passive_requirements.py",
        "tools/lr_design.py",
        "tools/cout_bank.py",
        "tools/cr_stress.py",
        "tools/ct_design.py",
        "tools/oc_network_check.py",
        "tools/connector_budget.py",
        "tools/board_netlist.py",
        "tools/winding_polarity.py",
        "tools/powerup_checklist.py",
        "tools/energy_ledger_100a.py",
        "tools/make_physical_decks.py",
        "tools/make_high_output_decks.py",
        "tools/ci_check.py",
        "tools/current_manifest.py",
        "tools/test_ascii_raw_window.py",
        "tools/test_magnetics_design.py",
        "tools/test_draw_magnetics.py",
        "tools/test_extract_op_point.py",
        "tools/test_thermal_precheck.py",
        "tools/test_passive_requirements.py",
        "tools/test_lr_design.py",
        "tools/test_cout_bank.py",
        "tools/test_cr_stress.py",
        "tools/test_ct_design.py",
        "tools/test_oc_network_check.py",
        "tools/test_gate_drive_calibration.py",
        "tools/test_connector_budget.py",
        "tools/test_board_netlist.py",
        "tools/test_powerup_checklist.py",
        "tools/test_energy_ledger_100a.py",
        "tools/test_make_physical_decks.py",
        "tools/test_make_high_output_decks.py",
        "tools/test_operating_point_110a.py",
        "tools/test_energy_ledger_48v_110a.py",
        "tools/test_control_validation_doc.py",
        "tools/test_ci_check.py",
        "tools/test_baseline_doc.py",
        "tools/test_bom_draft.py",
        "tools/test_current_manifest.py",
    ],
    "result": [
        "design/v3/magnetics/magnetics_design.json",
        "design/v3/magnetics/operating_point_100a.json",
        "design/v3/magnetics/operating_point_100a_cout7m.json",
        "design/v3/magnetics/operating_point_100a_phys.json",
        "design/v3/magnetics/manifest.json",
        "design/v3/magnetics/height_stackup.csv",
        "design/v3/magnetics/inspection_spec.csv",
        "design/v3/magnetics/winding_polarity.json",
        "design/v3/magnetics/winding_polarity.csv",
        "design/v3/magnetics/first_article_polarity_record.csv",
        "design/v3/stage_f/thermal_precheck.json",
        "design/v3/bom/passive_requirements.json",
        "design/v3/bom/lr_design.json",
        "design/v3/bom/cout_bank.json",
        "design/v3/bom/cr_stress.json",
        "design/v3/bom/ct_design.json",
        "design/v3/bom/oc_network_ct10.json",
        "design/v3/bom/oc_network_ct47.json",
        "design/v3/bom/connector_budget.json",
        "design/v3/bom/bom_draft.csv",
        "design/v3/pcb/board_netlist.csv",
        "design/v3/pcb/board_netlist.json",
        "design/v3/stage_f/powerup_checklist.json",
        "design/v3/stage_f/上电检查表.md",
        "design/v3/stage_f/energy_ledger_100a.json",
        "design/v3/stage_f/energy_ledger_100a_phase_aligned.json",
        # High-output candidate: the run record, its writeup, and the ledger
        # taken from the probe deck (input power, hence efficiency).
        "design/v3/power_priority/operating_point_48v_110a.json",
        "design/v3/power_priority/scenarios.json",
        "design/v3/power_priority/energy_ledger_48v_110a.json",
    ],
    "doc": [
        "design/v3/magnetics/磁件设计包_2026-10-31.md",
        "design/v3/magnetics/绕组工艺卡_2026-11-01.md",
        "design/v3/magnetics/winding_cross_section.svg",
        "design/v3/magnetics/winding_connections.svg",
        "design/v3/magnetics/height_stackup.svg",
        "design/v3/当前候选基线_2026-11-01.md",
        "design/v3/stage_f/首样验证与额定值判定_2026-10-31.md",
        "design/v3/bom/功率级元件需求与BOM草案_2026-11-01.md",
        "design/v3/pcb/主功率板连接网表_2026-11-01.md",
        "design/v3/power_priority/48V110A_实测_2026-11-01.md",
        "pcb/control_validation/控制验证板_设计与测试说明_2026-10-31.md",
    ],
    "config": [
        "requirements.txt",
        ".github/workflows/ci.yml",
    ],
    "raw": [
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned2n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned1n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.raw",
        # The three cold-start / cold-OC raws are 11-12 GB each and stay out of
        # the hash list; their .log files are the committed measurements.
    ],
}

V2_SOURCES = {
    "deck": [
        "sim/v2/sr_tank_dual_v33_ss_1ms.cir",
        "sim/v2/sr_tank_dual_v33_ss_1ms_full.cir",
        "sim/v2/sr_tank_dual_v33_cold.cir",
        "sim/v2/sr_tank_dual_v33_cold_oc.cir",
        "sim/v2/sr_tank_dual_v33_conv_5n.cir",
        "sim/v2/sr_tank_dual_v33_conv_2n.cir",
        "sim/v2/sr_tank_dual_v33_conv_1n.cir",
        "sim/v2/sr_tank_dual_v33_cpin_50p.cir",
        "sim/v2/sr_tank_dual_v33_cpin_200p.cir",
        "sim/v2/sr_tank_dual_v33_conv1ms_2n.cir",
        "sim/v2/sr_tank_dual_v33_conv1ms_1n.cir",
        "sim/v2/sr_tank_dual_v33_cpin1ms_50p.cir",
        "sim/v2/sr_tank_dual_v33_cpin1ms_200p.cir",
    ],
    "model": [
        "models/ucc25600_legacy_behaviour.lib",
        "models/sr_timing_v3_3.lib",
        "models/sr_device_v3.lib",
    ],
    "script": [
        "tools/tank_metrics.py",
        "tools/sr_energy_ledger.py",
        "tools/steady_state_check.py",
        "tools/round3_summary.py",
        "tools/task_package1_summary.py",
        "tools/fault_metrics.py",
        "tools/ascii_raw_window.py",
        "tools/period_variance.py",
        "tools/make_round4_decks.py",
        "tools/current_manifest.py",
        "tools/test_tank_metrics.py",
        "tools/test_sr_energy_ledger.py",
        "tools/test_steady_state_check.py",
        "tools/test_round3_summary.py",
        "tools/test_task_package1_summary.py",
        "tools/test_make_round4_decks.py",
        "tools/test_fault_metrics.py",
        "tools/test_ascii_raw_window.py",
    ],
    "result": [
        "design/v2/round4_summary.json",
        "design/v2/round3_summary.json",
        "design/v2/round3_energy_ledger_ss.json",
        "design/v2/round3_energy_ledger_284k.json",
        "design/v2/period_variance_cpin1ms.json",
        "design/v2/fault_metrics_sr_tank_dual_v33_cold_oc.json",
        "design/v2/第四轮_证据修正与数值疑点关闭_2026-10-31.md",
    ],
    "raw": [
        "sim/v2/sr_tank_dual_v33_ss_1ms.raw",
        "sim/v2/sr_tank_dual_v33_ss_1ms_full.raw",
        "sim/v2/sr_tank_dual_v33_cold.raw",
        "sim/v2/sr_tank_dual_v33_cold_oc.raw",
        "sim/v2/sr_tank_dual_v33_conv_5n.raw",
        "sim/v2/sr_tank_dual_v33_conv_2n.raw",
        "sim/v2/sr_tank_dual_v33_conv_1n.raw",
        "sim/v2/sr_tank_dual_v33_cpin_50p.raw",
        "sim/v2/sr_tank_dual_v33_cpin_200p.raw",
        "sim/v2/sr_tank_dual_v33_conv1ms_2n.raw",
        "sim/v2/sr_tank_dual_v33_conv1ms_1n.raw",
        "sim/v2/sr_tank_dual_v33_cpin1ms_50p.raw",
        "sim/v2/sr_tank_dual_v33_cpin1ms_200p.raw",
    ],
}

SCOPES = {"v2": V2_SOURCES, "v3": V3_SOURCES}

# Full hashes above this size are skipped: a raw is identified by size, mtime and
# its saved time range, and re-verifying it means re-running the deck anyway.
HASH_LIMIT_BYTES = 256 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def entry(path: str, kind: str) -> dict[str, object]:
    full = ROOT / path
    if not full.exists():
        return {"path": path, "kind": kind, "status": "missing"}
    size = full.stat().st_size
    row: dict[str, object] = {
        "path": path,
        "kind": kind,
        "bytes": size,
        "mtime": full.stat().st_mtime,
        "sha256": sha256(full) if size <= HASH_LIMIT_BYTES else "skipped-large-raw",
    }
    return row


_SPICE_SUFFIX = (("meg", 1e6), ("t", 1e12), ("g", 1e9), ("k", 1e3),
                 ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12), ("f", 1e-15))


def spice_seconds(token: str) -> float:
    """LTspice time literal ('880u', '5n', '8m', '0') -> seconds."""
    text = token.strip().lower()
    if text in ("", "0"):
        return 0.0
    for suffix, scale in _SPICE_SUFFIX:
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * scale
    return float(text)


def deck_timing(rel_path: str, root: Path = ROOT) -> dict[str, object]:
    """Saved-axis range and display offset, read from the deck's own .tran line.

    `Tstart` rebases the axis: `.tran 0 1000u 880u 5n uic` writes 0..120 us into
    the raw, which displays as 880..1000 us.  Both numbers are recorded because
    neither alone says which window a downstream measurement used.

    `cold_start` follows the same rule as tools/task_package1_summary.py: `uic`
    alone is a true zero initial state, but any `.ic` directive means the run
    starts from a specified state no matter what `uic` says.
    """
    deck = root / rel_path
    row: dict[str, object] = {"deck": rel_path}
    if not deck.exists():
        return {**row, "status": "missing"}
    lines = deck.read_text(encoding="utf-8", errors="replace").splitlines()
    tran = next((ln for ln in lines if ln.strip().lower().startswith(".tran")), None)
    if tran is None:
        return {**row, "status": "no .tran"}
    tokens = tran.split()[1:]
    has_uic = any(tok.lower() == "uic" for tok in tokens)
    numeric = [tok for tok in tokens if tok.lower() not in ("uic", "startup")]
    stop = spice_seconds(numeric[1]) if len(numeric) > 1 else 0.0
    start = spice_seconds(numeric[2]) if len(numeric) > 2 else 0.0
    max_step = spice_seconds(numeric[3]) if len(numeric) > 3 else 0.0
    has_ic = any(ln.strip().lower().startswith(".ic") for ln in lines)
    return {
        **row,
        "tran": tran.strip(),
        "raw_time_start_s": 0.0,
        "raw_time_end_s": stop - start,
        "display_offset_us": round(start * 1e6, 9),  # 880u -> 880.0, not 879.9999999999999
        "max_step_s": max_step,
        "has_ic": has_ic,
        "uic": has_uic,
        "cold_start": has_uic and not has_ic,
    }


def log_saved_end_s(log: Path) -> float | None:
    """The end of the saved window as LTspice itself reported it ('FROM 0 TO x')."""
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"FROM 0 TO ([0-9.eE+-]+)", text)
    return float(match.group(1)) if match else None


def run_metadata(summary_path: Path) -> dict[str, object]:
    """Saved-axis range and display offset per result section."""
    if not summary_path.exists():
        return {}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for section in ("operating_point", "full_machine", "cold_start"):
        row = payload.get(section)
        if isinstance(row, dict):
            out[section] = {
                key: row.get(key) for key in ("raw", "raw_time_start_s", "raw_time_end_s",
                                              "display_offset_us", "window_us")
                if key in row
            }
    for section in ("convergence", "convergence_1ms", "cpin_sensitivity"):
        cases = payload.get(section)
        if isinstance(cases, dict):
            out[section] = {
                label: {key: case.get(key) for key in ("raw_time_start_s", "raw_time_end_s",
                                                       "display_offset_us")}
                for label, case in cases.items()
            }
    return out


REPRODUCE = {
    "v2": [
            "python tools/make_round4_decks.py",
            "python tools/task_package1_summary.py --op sim/v2/sr_tank_dual_v33_ss_1ms.raw "
            "--full sim/v2/sr_tank_dual_v33_ss_1ms_full.raw --cold sim/v2/sr_tank_dual_v33_cold.raw "
            "--conv1ms 2n=sim/v2/sr_tank_dual_v33_conv1ms_2n.raw "
            "1n=sim/v2/sr_tank_dual_v33_conv1ms_1n.raw "
            "--cpin1ms 50p=sim/v2/sr_tank_dual_v33_cpin1ms_50p.raw "
            "200p=sim/v2/sr_tank_dual_v33_cpin1ms_200p.raw "
            "--json design/v2/round4_summary.json",
            "python tools/fault_metrics.py --fault-start-ms 5.5 --fault-end-ms 5.6 "
            "--gate \"V(ga1)\" --ascii-window-from-ms 5.4 sr_tank_dual_v33_cold_oc",
            "python tools/period_variance.py 5n=sim/v2/sr_tank_dual_v33_ss_1ms.raw "
            "2n=sim/v2/sr_tank_dual_v33_conv1ms_2n.raw "
            "1n=sim/v2/sr_tank_dual_v33_conv1ms_1n.raw "
            "cpin50p=sim/v2/sr_tank_dual_v33_cpin1ms_50p.raw "
            "cpin200p=sim/v2/sr_tank_dual_v33_cpin1ms_200p.raw "
            "--json design/v2/period_variance_cpin1ms.json",
            "python -m pytest tools -q",
    ],
    "v3": [
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw "
        "--rl 0.0189 --periods 22 --json design/v3/magnetics/operating_point_100a.json",
        "python tools/magnetics_design.py --json design/v3/magnetics/magnetics_design.json",
        "python tools/draw_magnetics.py --out design/v3/magnetics",
        "python tools/make_magnetics_manifest.py",
        "python tools/thermal_precheck.py --json design/v3/stage_f/thermal_precheck.json",
        "python tools/passive_requirements.py --json design/v3/bom/passive_requirements.json",
        "python tools/passive_requirements.py "
        "--cin-raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.raw "
        "--json design/v3/bom/passive_requirements.json",
        "python tools/lr_design.py --json design/v3/bom/lr_design.json",
        "python tools/cout_bank.py --json design/v3/bom/cout_bank.json",
        "python tools/cr_stress.py --json design/v3/bom/cr_stress.json",
        "python tools/ct_design.py --json design/v3/bom/ct_design.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct47.cir",
        "python tools/oc_network_check.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.raw "
        "--burden 10 --rd1 10k --json design/v3/bom/oc_network_ct10.json",
        "python tools/oc_network_check.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct47.raw "
        "--burden 47 --rd1 110k --json design/v3/bom/oc_network_ct47.json",
        "python tools/connector_budget.py --json design/v3/bom/connector_budget.json",
        "python tools/board_netlist.py --json design/v3/pcb/board_netlist.json "
        "--csv design/v3/pcb/board_netlist.csv",
        "python tools/powerup_checklist.py --md design/v3/stage_f/上电检查表.md "
        "--json design/v3/stage_f/powerup_checklist.json",
        "python tools/make_physical_decks.py",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.cir",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.raw --periods 133 "
        "--no-step-check "
        "--json design/v3/stage_f/energy_ledger_100a_phase_aligned.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.raw "
        "--rl 0.0189 --periods 22 --json design/v3/magnetics/operating_point_100a_cout7m.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.raw "
        "--rl 0.0189 --periods 22 --json design/v3/magnetics/operating_point_100a_phys.json",
        "# 11-12 GB cold runs (~37 min each); the .log carries the .meas results used by lr_design.py",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_phys.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_oc_phys.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_oc_lrmin.cir",
        # High-output candidate: generate, run, extract, then the ledger on the
        # probe deck (that deck differs from the candidate only in .save).
        "python tools/make_high_output_decks.py --write",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.raw "
        "--rl 0.0169 --periods 22 --pairs 1 4 "
        "--json design/v3/power_priority/operating_point_48v_110a.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.cir",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.raw --periods 22 "
        "--vin 48 --rl 0.0169 --no-step-check "
        "--json design/v3/power_priority/energy_ledger_48v_110a.json",
        "python -m pytest tools -q",
        "python tools/ci_check.py",
    ],
}

SCOPE_DESCRIPTION = {
    "v2": "current candidate only: round-4 decks/models/scripts/results + run metadata",
    "v3": "100 A design delivery: two v3 decks/raws, magnetics package, "
          "stage-F protocol, BOM package + deck-derived run metadata",
}

SCOPE_SUPERSEDES = {
    "v2": {
        "path": "design/baseline/baseline_manifest.json",
        "entries": 304,
        "status": "historical; five known hash mismatches, do not reproduce from it",
    },
    "v3": {
        "path": "design/v2/manifest_current_candidate.json",
        "status": "historical; the v2 round-4 package, superseded by this v3 delivery",
    },
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=sorted(SCOPES), default="v2")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=ROOT / "design/v2/round4_summary.json")
    args = ap.parse_args()

    sources = SCOPES[args.scope]
    out_path = args.json or ROOT / f"design/{args.scope}/manifest_current_candidate.json"
    entries = [entry(path, kind) for kind, paths in sources.items() for path in paths]
    decks = [deck_timing(path) for path in sources["deck"]]
    payload = {
        "generated": date.today().isoformat(),
        "scope": SCOPE_DESCRIPTION[args.scope],
        "supersedes": SCOPE_SUPERSEDES[args.scope],
        "entries": entries,
        "missing": [row["path"] for row in entries if row.get("status") == "missing"],
        "deck_timing": decks,
        "raw_run_metadata": run_metadata(args.summary) if args.scope == "v2" else {},
        "reproduce": REPRODUCE[args.scope],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path}  ({len(entries)} entries, {len(payload['missing'])} missing)")


if __name__ == "__main__":
    main()
