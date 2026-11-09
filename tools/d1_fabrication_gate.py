"""Fail-closed, regenerable D1 electrical fabrication readiness report.

Checks evidence actually present in the repository. Do NOT equate a passing
subset-of-pads netlist diff, offline pytest, a machine-generated placement PCB,
or simulated current with a fabrication release.

Usage:
  python tools/d1_fabrication_gate.py --write
  python tools/d1_fabrication_gate.py --require-release
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
OUT = HW / "d1_fabrication_gate.json"
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
NETLIST = HW / "netlist_compare.json"
CONTRACT = HW / "magnetics_symbol_contract.json"
REVIEW = HW / "pin_footprint_review.csv"
BOM = ROOT / "design/v3/bom/bom_draft.csv"

import d1_bom_coverage as bomcov
import d1_functional_net_audit as functional_audit
import check_main_board_netlist as native_check
import main_board_schematic as mbs
import magnetics_cad_contract as magnetics_contract
import native_inventory_bom_gate as native_bom

# No such files have been delivered in the current main branch. Do not turn
# these checks green until the native EDA evidence has been independently
# exported and checked, including real pad numbers and layer stack-up.
NATIVE_ERC = HW / "native_erc_approved.json"
PCB_NET_DIFF = HW / "pcb_to_schematic_verified.json"
FAB_APPROVAL = HW / "fabrication_approval.json"
# This P0 design review is separate from ERC/PCB/DFM and from hardware rating.
PROTECTION_APPROVAL = HW / "protection_design_approved.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _manual_gate(path: Path, required: tuple[str, ...]) -> dict:
    try:
        display = path.relative_to(ROOT).as_posix()
    except ValueError:
        display = path.as_posix()
    if not path.is_file():
        return {"passed": False, "reason": "evidence file absent", "path": display}
    try:
        doc = _read(path)
    except (ValueError, OSError) as exc:
        return {"passed": False, "reason": f"invalid evidence: {type(exc).__name__}",
                "path": display}
    # Sign-off metadata alone is not enough: evidence must be present in this
    # checkout with a matching sha256. Reject absolute/out-of-repo paths so an
    # approval cannot silently depend on a private author's desktop.
    ok = doc.get("approved") is True and all(
        isinstance(doc.get(k), str) and doc[k].strip() for k in required
    )
    reason = "approval and source evidence fields incomplete"
    if ok:
        paths = [k for k in required if k.endswith("_path")]
        if not paths:
            ok = False
            reason = "no original evidence file fields"
        for key in paths:
            if not ok:
                break
            original = Path(doc[key])
            if original.is_absolute() or ".." in original.parts:
                ok = False
                reason = "evidence path must be relative and inside repository"
                break
            original = ROOT / original
            digest = doc.get(key[:-5] + "_sha256")
            if (not original.is_file() or not isinstance(digest, str)
                    or len(digest) != 64
                    or hashlib.sha256(original.read_bytes()).hexdigest() != digest.lower()):
                ok = False
                reason = "missing original report or matching sha256: " + key
                break
    return {"passed": bool(ok), "path": display,
            "reason": "source hashes verified; still needs human signature review" if ok else reason}



def _protection_design_gate() -> dict:
    """Fail closed until real hardware fault-inhibit design is independently reviewed.

    An ideal LTspice behavioural latch or 0.05-ohm clamp cannot serve as this
    approval. Source hashes bind the review to a saved native CAD revision;
    these metadata checks do not constitute hardware SOA certification.
    """
    fields = (
        "native_project_path", "fault_analysis_path", "driver_shutdown_path",
        "power_sequence_path", "vendor_soa_path", "reviewer", "revision",
    )
    result = _manual_gate(PROTECTION_APPROVAL, fields)
    if not result["passed"]:
        return result
    doc = _read(PROTECTION_APPROVAL)
    if doc.get("review_scope") != "PRE_FAB_PROTECTION_DESIGN_ONLY":
        return {**result, "passed": False,
                "reason": "protection review must be a pre-fabrication design check"}
    if doc.get("native_project_path") != "hardware/dcx_main/dcx_main_board.eprj2":
        return {**result, "passed": False,
                "reason": "fault shutdown review not bound to the native main-board CAD"}
    guarantees = (
        "independent_primary_and_all_eight_sr_inhibit_reviewed",
        "gate_disable_on_any_bias_loss_reviewed",
        "fault_latch_and_controlled_restart_reviewed",
        "startup_masking_and_fault_during_mask_reviewed",
        "physical_gate_driver_and_clamp_conflict_reviewed",
        "vendor_pulse_soa_and_winding_stress_reviewed",
    )
    missing = [key for key in guarantees if doc.get(key) is not True]
    if missing:
        return {**result, "passed": False,
                "reason": "missing protection design approvals: " + ", ".join(missing)}
    load = doc.get("simulated_fault_load_a")
    if (doc.get("simulated_fault_vin_v") != [48, 50] or
        isinstance(load, bool) or not isinstance(load, (int, float))
        or not (120 <= load < 10000)):
        return {**result, "passed": False,
                "reason": "protection evidence must cover 48/50 V and at least 120 A"}
    return {**result, "reason":
            "original source hashes matched; design-only signoff, NOT a hardware rating"}


def _primary_en_default_low_precheck(refs: dict, r8_real_dnp: bool = False) -> dict:
    """Static structural veto on always-on RUN; *not* protection approval.

    A real fault latch must independently be reviewed, but paperwork cannot
    override a 1k pullup hardwired between VCC12 and the UCC27282 EN pin.
    Search all resistor refs (not just R8), in either pin order, so renaming
    the unsafe resistor cannot evade the check. A captured R8 DNP is excluded
    ONLY if both actual BOM and PCB flags are false and the capture's
    independently generated audit matches its committed readback; connected
    but physically unpopulated R8 remains visible in the schematic netlist.
    """
    u2 = refs.get("U2") or {}
    r7 = refs.get("R7") or {}
    run_net = u2.get("6")
    problems = []
    if run_net != "RUN":
        problems.append("U2 pin6 EN is not on the reviewed RUN net")
    if set(r7) != {"1", "2"} or set(r7.values()) != {"RUN", "PGND"}:
        problems.append("R7 passive default-low path RUN->PGND missing")
    if run_net:
        powered = sorted(
            ref for ref, pins in refs.items()
            if ref.startswith("R") and isinstance(pins, dict)
            and not (ref == "R8" and r8_real_dnp is True)
            and len(pins) == 2 and set(pins.values()) == {"VCC12", run_net}
        )
        if powered:
            problems.append("unconditional resistor pullup to VCC12: " +
                            ", ".join(powered))
    return {"passed": not problems, "problems": problems,
            "limited_scope": "static RUN routing only; no proof of fault latch, "
                             "power loss, real driver inhibit or measured gate VGS"}


def _native_mpn_and_r8_precheck() -> dict:
    """Manufacturing veto against actual captured OEM IDs, not display Value.

    The 61-ref value ECO can make a schematic look correct without replacing
    physical Samsung 100nF / Uniroyal 10k library devices. Compare the
    independently regenerated original-inventory audit with its committed
    readback: stale or absent evidence cannot authorize fabrication.
    This is a necessary SOURCE check, never a substitute for native GUI
    export, exact package pin map, or signed purchasing/DFM approval.
    """
    try:
        actual = native_bom.audit()
        cached = _read(native_bom.OUTPUT)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"passed": False, "snapshot_matches_live_capture": False,
                "manufacturer_target_conflicts": None,
                "r8_in_bom": None, "r8_in_pcb": None,
                "reason": f"native inventory audit unavailable: {type(exc).__name__}"}
    match = cached == actual
    conflicts = actual.get("manufacturer_target_conflicts")
    in_bom = actual.get("original_r8_in_bom")
    in_pcb = actual.get("original_r8_in_pcb")
    # A zero-conflict report with zero audited rows is not a clean BOM.
    # Maintain at least the historically evidenced 51 manufacturer/target
    # identities (of 61 placeholder refs and 83 captured native instances).
    # When replacing parts, the auditor and its verified OEM part registry must
    # be extended, not bypassed by dropping old part codes from KNOWN.
    known_rows = actual.get("known_mpn_and_target_rows")
    register_rows = actual.get("register_placeholder_rows")
    component_rows = actual.get("native_components")
    coverage_retained = (
        type(known_rows) is int and known_rows >= 51
        and type(register_rows) is int and register_rows >= 61
        and type(component_rows) is int and component_rows >= 83
    )
    passed = (match and coverage_retained
              and type(conflicts) is int and conflicts == 0
              and in_bom is False and in_pcb is False)
    return {
        "passed": passed,
        "snapshot_matches_live_capture": match,
        "manufacturer_target_conflicts": conflicts,
        "r8_in_bom": in_bom,
        "r8_in_pcb": in_pcb,
        "known_mpn_and_target_rows": actual.get("known_mpn_and_target_rows"),
        "native_component_rows": actual.get("native_components"),
        "reason": ("captured MPN/target pairs agree and R8 is DNP in BOM and PCB"
                   if passed else
                   "OEM manufacturer MPN/value conflicts, unsafe R8 inclusion "
                   "or stale native readback; correct in actual EDA and re-export"),
        "scope": "Known catalog part numbers in captured EDA only; NOT a fresh GUI ERC or final BOM approval",
    }


def build() -> dict:
    golden = _csv(GOLDEN)
    net = _read(NETLIST)
    # Never accept edited physical-pad/DOT approval booleans from the cached
    # JSON. The current contract generator still has NO vendor drawings and
    # therefore must remain unverified. Any future physical-pad approval
    # requires a reviewed generator change plus real native-CAD evidence.
    magnets = _read(CONTRACT)["symbols"]
    live_magnets = magnetics_contract.build()["symbols"]
    if magnets != live_magnets:
        raise ValueError("magnetics CAD contract differs from live SPICE/native source")
    placement = _read(HW / "placement_plan.json")
    review = _csv(REVIEW)
    bom = _csv(BOM)
    # Recompute from current BOM and SPICE golden: a stale checked-in
    # bom_coverage.json must never make this release gate go green.
    bom_coverage = bomcov.build()
    native_export = _read(HW / "gen/netlist_export_raw.json")
    if not native_export.get("ok") or not isinstance(native_export.get("value", {}).get("refs"), dict):
        raise ValueError("missing or invalid native EDA export")
    native_refs = set(native_export["value"]["refs"])
    # The cached subset report is not authoritative. Recompute directly
    # from this checkout's CAD export and the golden pad contract each run.
    # A changed export must not retain last week's green netlist_compare.json.
    live_net = native_check.compare(
        mbs.load_golden(), native_export["value"]["refs"], mbs.load_library())
    subset_snapshot_fresh = live_net == net
    functional_check = functional_audit.compare(native_export["value"]["refs"])
    native_mpn_precheck = _native_mpn_and_r8_precheck()
    # With the actual native capture and regeneration matching, both BOM+PCB
    # excluded R8 is an unpopulated schematic footprint, not an electrical
    # pull-up. The 39/38 other OEM discrepancies still independently block
    # fabrication via native_mpn_precheck; design-only protection signoff
    # requires entirely separate physical fault-inhibit evidence.
    real_r8_dnp = (
        native_mpn_precheck["snapshot_matches_live_capture"] is True
        and native_mpn_precheck["r8_in_bom"] is False
        and native_mpn_precheck["r8_in_pcb"] is False
    )
    primary_en_precheck = _primary_en_default_low_precheck(
        native_export["value"]["refs"], r8_real_dnp=real_r8_dnp)


    gold_refs = {x["ref"] for x in golden}
    present = set(placement["refs"])
    missing_refs = sorted(gold_refs - present)
    incomplete_magnets = sorted(
        m["ref"] for m in magnets
        if not m.get("native_symbol_present") or not m.get("physical_pad_map_verified")
        or any(not p.get("physical_pad") for p in m.get("pins", []))
    )
    placeholders = sorted({x["ref"] for x in review if "PLACEHOLDER" in x.get("note", "")})
    undecided_bom = [
        {"ref": x["ref"], "mpn": x["mpn"], "status": x["status"]}
        for x in bom if x["mpn"] in {"TO SELECT", "TO BUILD", "TO ASSIGN"}
                     or x["status"] in {"TO SELECT", "TO BUILD"}
    ]
    native_erc = _manual_gate(NATIVE_ERC, ("report_path", "reviewer", "revision"))
    pcb_diff = _manual_gate(PCB_NET_DIFF, ("report_path", "reviewer", "revision"))
    fab_signoff = _manual_gate(FAB_APPROVAL, ("gerber_path", "bom_path", "pcb_drc_path",
                                               "stackup_path", "reviewer", "revision"))
    protection_design = _protection_design_gate()

    logical_ok = (
        bool(live_net.get("subset_ok"))
        and not live_net.get("missing_or_wrong")
        and not live_net.get("unexpected_nets")
        and not live_net.get("unexpected_refs")
        and subset_snapshot_fresh
    )
    # "ok" in a subset report is explicitly NOT a release decision.
    all_placed = not missing_refs and not live_net.get("not_placed") and not incomplete_magnets
    all_values_frozen = not placeholders and not undecided_bom
    required_missing = bom_coverage["required_bom_refs_missing_from_golden"]
    # Unlike the SPICE-derived golden, the *actual native* CAD must include
    # every soldered BOM designator. The external PS1 can remain an interface.
    # R7-R10/C13/C101-C112 can never appear in a SPICE netlist, so keying this
    # check to the golden list made it unpassable by definition.
    all_bom_refs = {
        ref for row in bom for ref in bomcov.refs(row["ref"])
    } - bomcov.EXTERNAL_INTERFACES
    native_bom_missing = sorted(all_bom_refs - native_refs)
    # Independent cross-check restricted to the same domain: coverage only
    # enumerates BOM refs absent from the golden list, while native_bom_missing
    # also covers golden refs that are simply not placed yet. If the two
    # disagree on the shared domain, neither the gate nor the report can be
    # trusted, so fail loudly instead of picking one.
    native_bom_missing_reported = sorted(
        x["ref"] for x in bom_coverage["required_bom_refs_missing_from_native_design"])
    native_bom_missing_not_in_golden = sorted((all_bom_refs - gold_refs) - native_refs)
    if native_bom_missing_not_in_golden != native_bom_missing_reported:
        raise ValueError(
            "BOM coverage and the native export disagree on missing refs: "
            f"coverage={native_bom_missing_reported} native={native_bom_missing_not_in_golden}")
    checks = {
        "native_editable_project_present": (HW / "dcx_main_board.eprj2").is_file(),
        "golden_subnet_matches": logical_ok,
        "cached_netlist_report_matches_live_native_export": subset_snapshot_fresh,
        "controller_rt_dt_roles_match_native_netlist": functional_check["passed"],
        "all_golden_refs_and_magnetic_physical_pads_verified": all_placed,
        "no_electrical_placeholders_or_unselected_bom": all_values_frozen,
        "native_manufacturer_ids_and_r8_dnp_verified": native_mpn_precheck["passed"],
        "all_required_real_hardware_bom_refs_in_native_design": not native_bom_missing_reported,
        "native_erc_evidence": native_erc["passed"],
        "routed_pcb_to_schematic_evidence": pcb_diff["passed"],
        "manufacturing_package_evidence": fab_signoff["passed"],
        "independent_fault_shutdown_design_evidence": (
            protection_design["passed"] and primary_en_precheck["passed"]),
    }
    blockers = [key for key, passed in checks.items() if not passed]
    return {
        "gate": "D1_ELECTRICAL_FABRICATION",
        "release_approved": not blockers,
        "status": "APPROVED_WITH_DOCUMENTED_EVIDENCE" if not blockers else "NOT_FOR_FAB",
        "checks": checks,
        "counts": {
            "golden_references": len(gold_refs),
            "golden_logical_pins": len(golden),
            "placed_references": len(present),
            "golden_pads_checked_by_subnet": live_net.get("pads_checked"),
            "live_native_netlist_missing_or_wrong": live_net.get("missing_or_wrong"),
            "functional_control_net_mismatches": functional_check["problems"],
            "unplaced_references": missing_refs,
            "magnetics_missing_physical_pads": incomplete_magnets,
            "refs_with_placeholders": placeholders,
            "native_mpn_target_conflicts": native_mpn_precheck["manufacturer_target_conflicts"],
            "native_r8_still_in_bom": native_mpn_precheck["r8_in_bom"],
            "native_r8_still_in_pcb": native_mpn_precheck["r8_in_pcb"],
            "bom_rows_not_selected": undecided_bom,
            "real_hardware_bom_refs_not_in_golden": sorted(x["ref"] for x in required_missing),
            "all_required_bom_refs_missing_from_native_export": native_bom_missing,
            "real_hardware_bom_refs_not_in_native_design": native_bom_missing_reported,
            "real_hardware_bom_refs_covered_by_native_design": bom_coverage["covered_by_native_design"],
            "external_bias_interface_to_document": [x["ref"] for x in bom_coverage["external_interfaces_not_in_golden"]],
        },
        "manual_evidence": {
            "native_erc": native_erc,
            "pcb_to_schematic": pcb_diff,
            "fab_approval": fab_signoff,
            "protection_design": protection_design,
            "native_manufacturer_bom": native_mpn_precheck,
        },
        "blockers": blockers,
        "limitations": [
            "Netlist subset is recomputed from the exported native CAD nets; cache must match but native export still needs editor provenance",
            "Subset netlist check is NOT a complete schematic pin or footprint check",
            "Controller RT/DT functional-value crosscheck detects BOM-to-net mislabelling but does NOT substitute native ERC",
            "The golden netlist was derived from a SPICE deck, not all physical components",
            "BOM-driven control/decoupling parts must be present in native EDA and the final CAD-derived netlist",
            "Visible schematic Value is not an OEM MPN: vendor MPN conflict and native R8 BOM/PCB DNP now veto fabrication",
            "Evidence records require original repository files and matching SHA256, but hashes do not replace expert approval",
            "Independent primary and eight SR fault shutdown must be independently design-reviewed in the same native CAD revision",
            "An ideal behavioural gate clamp cannot replace vendor SOA or real hardware protection signoff",
            "Power and efficiency from LTspice do not constitute hardware continuous rating",
            "Thermal and cold plate design intentionally deferred; continuous rating stays unapproved",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--require-release", action="store_true")
    args = parser.parse_args()
    result = build()
    serial = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.write:
        OUT.write_text(serial, encoding="utf-8", newline="\n")
    elif OUT.is_file() and OUT.read_text(encoding="utf-8") != serial:
        raise SystemExit("D1 report is stale: run --write and commit the difference")
    print(f"D1 {result['status']}: {len(result['blockers'])} blocker categories")
    for row in result["blockers"]:
        print(f"  BLOCKED {row}")
    return 1 if args.require_release and not result["release_approved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
