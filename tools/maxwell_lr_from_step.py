"""Prepare or solve one vetted Lr CAD case in Maxwell 3D via PyAEDT.

The repository does NOT contain an executable STEP model or nonlinear 100 C
N97 B-H curve. Engineers can build a *catalogue-based concept STEP* while
waiting for OEM geometry, but must label the provenance. Until a reviewed
STEP and traceable BH table are supplied, --check returns blockers,
and --build/--solve fail closed. This is intentionally not a fictitious FEM run.

    python tools/maxwell_lr_from_step.py --check --case ELP38_Lr_2turn_0920uH
    python tools/maxwell_lr_from_step.py --build --case ELP38_Lr_2turn_0920uH
    python tools/maxwell_lr_from_step.py --solve --case ELP38_Lr_2turn_0920uH

Requires ansys-aedt-core / Ansys Electronics Desktop only for build/solve.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "design/v3/maxwell/elp38_lr_maxwell_contract.json"


def load_case(config: dict, case_id: str) -> dict:
    selected = [c for c in config["cases"] if c["id"] == case_id]
    if len(selected) != 1:
        raise ValueError(f"unknown or duplicated case: {case_id}")
    return selected[0]


def under_repo(path_text: str | None) -> Path | None:
    if not path_text:
        return None
    path = (ROOT / path_text).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"path outside repository: {path_text}")
    return path


def check_bh_csv(path: Path) -> list[str]:
    errors = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) < 6:
            errors.append("BH curve needs >=6 measured/digitized samples")
        previous_h, previous_b = None, None
        for index, r in enumerate(rows):
            h, b = float(r["H_A_per_m"]), float(r["B_T"])
            if not math.isfinite(h) or not math.isfinite(b) or h < 0 or b < 0:
                errors.append("BH CSV requires finite non-negative H and B")
                break
            if index == 0 and (h != 0 or b != 0):
                errors.append("normal BH curve must begin at (H=0,B=0)")
                break
            if previous_h is not None:
                dh, db = h - previous_h, b - previous_b
                if dh <= 0 or db <= 0:
                    errors.append("BH requires strictly increasing H and B")
                    break
                # Maxwell normal BH requires slope not below vacuum mu0.
                if db / dh < 4 * math.pi * 1e-7:
                    errors.append("normal BH slope must not drop below mu0")
                    break
            previous_h, previous_b = h, b
        if previous_b is not None and previous_b < 0.32:
            errors.append("BH data must reach >=0.32T for the 2-turn RFQ case")
    except (ValueError, KeyError, OSError) as exc:
        errors.append("BH CSV invalid: " + str(exc))
    return errors


def blockers(config: dict, case: dict) -> list[str]:
    problems = []
    for k in ("geometry_source_reviewed_for_concept",
              "bh_curve_source_reviewed_for_concept",
              "winding_direction_confirmed", "cad_gap_matches_case"):
        if config["approval"].get(k) is not True:
            problems.append("approval." + k + " still false")
    geometry = under_repo(case.get("step_file"))
    if geometry is None or not geometry.is_file():
        problems.append("case.step_file missing reviewed CAD STEP (self-built concept allowed)")
    elif geometry.suffix.lower() not in {".step", ".stp"}:
        problems.append("case.step_file must be STEP")
    bh = under_repo(config.get("n97_bh_100c_csv"))
    if bh is None or not bh.is_file():
        problems.append("n97_bh_100c_csv missing sourced nonlinear BH table")
    else:
        problems.extend(check_bh_csv(bh))
    if not config.get("aedt_material_name"):
        problems.append("aedt_material_name required; runner creates material from supplied BH CSV")
    if config.get("hardware_fabrication_approved") is not False:
        problems.append("fabrication flag cannot be set by Maxwell recipe")
    if config.get("maxwell_solution") != "Magnetostatic":
        problems.append("this runner only supports Magnetostatic L(I) screening")
    names = list(config.get("cad_body_names", {}).values())
    if len(names) != 4 or len(set(names)) != 4 or not all(names):
        problems.append("four CAD body names must be distinct")
    return problems


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matrix_export_path(output: Path, current_a: float) -> Path:
    """PyAEDT export_matrix requires .txt; don't call it with .csv."""
    return output / ("matrix_" + str(current_a).replace(".", "p") + "A.txt")


def source_sha256_evidence(config_path: Path, cad: Path, bh: Path) -> dict:
    """Record exactly which config, geometry and B-H were used per run."""
    return {
        "config_sha256": sha256(config_path),
        "step_sha256": sha256(cad),
        "bh_sha256": sha256(bh),
    }


def bh_pairs_for_pyaedt(rows: list[dict]) -> list[list[float]]:
    """Use labeled input rows in the [H(A/m), B(T)] order of PyAEDT docs.

    Separation from Ansys lets CI check unit ordering independently.
    """
    return [[float(row["H_A_per_m"]), float(row["B_T"])] for row in rows]


def build(config: dict, case: dict, *, solve: bool, output: Path,
          version: str | None) -> None:
    try:
        from ansys.aedt.core import Maxwell3d
        from ansys.aedt.core.modules.boundary.maxwell_boundary import (
            MatrixMagnetostatic, SourceMagnetostatic,
        )
    except ImportError as exc:
        raise SystemExit("Install compatible PyAEDT (ansys-aedt-core) on a "
                         "licensed Maxwell host: " + str(exc)) from exc

    step = under_repo(case["step_file"])
    bh = under_repo(config["n97_bh_100c_csv"])
    names = config["cad_body_names"]
    output.mkdir(parents=True, exist_ok=True)
    input_evidence = {
        "case": case["id"], "source": CONFIG.relative_to(ROOT).as_posix(),
        "manufacturer_geometry_verified": config["approval"].get("manufacturer_geometry_verified", False),
        **source_sha256_evidence(CONFIG, step, bh),
        "solver": "Ansys Maxwell 3D Magnetostatic",
        "meaning": "CAD/source provenance only, NOT an L(I) answer",
        "concept_model": True,
        "fab_release": False,
    }
    (output / "inputs.json").write_text(
        json.dumps(input_evidence, indent=2) + "\n", encoding="utf-8")

    app = Maxwell3d(
        project=str(output / (case["id"] + ".aedt")),
        design="Lr_bias_magnetostatic",
        solution_type="Magnetostatic",
        version=version,
        new_desktop=True, non_graphical=False,
    )
    try:
        ok = app.import_3d_cad(str(step), import_free_surfaces=True)
        if not ok:
            raise RuntimeError("STEP import failed")
        available = set(app.modeler.object_names)
        missing = set(names.values()) - available
        if missing:
            raise RuntimeError("STEP must name independent core, plate, copper, "
                               "terminal sheet bodies: " + str(sorted(missing)))
        material = config["aedt_material_name"]
        # Build the non-linear concept material from the supplied sourced
        # CSV instead of requiring a manually preloaded AEDT library item.
        # PyAEDT expects magnetization entries ordered [H (A/m), B (T)].
        with bh.open(encoding="utf-8-sig", newline="") as stream:
            points = bh_pairs_for_pyaedt(list(csv.DictReader(stream)))
        mat = app.materials.add_material(material)
        if not mat:
            raise RuntimeError("cannot register N97 BH material")
        mat.permeability.value = points
        if not mat.update():
            raise RuntimeError("nonlinear BH assignment did not update")
        if not app.assign_material(
            [names["core"], names["plate"]], material
        ):
            raise RuntimeError("core material assignment failed")
        if not app.assign_material(names["winding_copper"], "copper"):
            raise RuntimeError("winding copper assignment failed")
        app.modeler.create_region(pad_value=60)
        # Terminal sheet direction and Ampere-turns MUST be independently
        # checked in the GUI. Stranded conductor ignores foil eddy losses.
        coil = app.assign_coil(
            assignment=[names["winding_terminal_sheet"]],
            conductors_number=int(case["turns"]),
            polarity="Positive", name="Lr_Terminal",
        )
        if not coil:
            raise RuntimeError("coil terminal assignment failed")
        winding = app.assign_winding(
            winding_type="Current", is_solid=False,
            current=0.5, name="Lr_Winding",
        )
        if not winding:
            raise RuntimeError("winding assignment failed")
        if not app.add_winding_coils(
            assignment=winding.name, coils=[coil.name]
        ):
            raise RuntimeError("winding->terminal mapping failed")
        matrix = app.assign_matrix(MatrixMagnetostatic(
            signal_sources=[SourceMagnetostatic(name=winding.name)],
            group_sources=[], matrix_name="Lr_Matrix",
        ))
        if not matrix:
            raise RuntimeError("inductance matrix creation failed")
        setup = app.create_setup(
            name="Lr_BH_Sweep", setup_type="Magnetostatic",
            MaximumPasses=12, PercentError=1.0,
        )
        if not setup:
            raise RuntimeError("analysis setup creation failed")
        if not app.save_project():
            raise RuntimeError("Maxwell project save failed")
        if solve:
            statuses = []
            for amp in config["solved_currents_a"]:
                winding.props["Current"] = str(amp) + "A"
                if not winding.update():
                    raise RuntimeError("winding current update failed")
                if not app.analyze_setup(name=setup.name):
                    raise RuntimeError("Maxwell solver failed at " + str(amp))
                # Store real solver artifacts, without reporting unparsed
                # matrices as verified inductance or material certification.
                matrix_path = matrix_export_path(output, amp)
                if not app.export_matrix(
                    matrix_name="Lr_Matrix", output_file=str(matrix_path),
                    setup=setup.name,
                ) or not matrix_path.is_file() or matrix_path.stat().st_size == 0:
                    raise RuntimeError("matrix export missing for current " + str(amp))
                statuses.append({
                    "current_a": amp, "solver_returned": True,
                    "matrix_file": matrix_path.name,
                    "matrix_sha256": sha256(matrix_path),
                    "L_diff_uH": None, "B_local_peak_T": None,
                    "validity": "RAW_MATRIX_ONLY_NEEDS_BH_AND_MESH_CONVERGENCE",
                })
            (output / "run_manifest.json").write_text(
                json.dumps({
                    "status": "SOLVER_CALLS_RETURNED_NOT_ENGINEERING_SIGNOFF",
                    "cases": statuses, "input_evidence": input_evidence,
                    "fab_release": False,
                }, indent=2) + "\n", encoding="utf-8")
            app.save_project()
    finally:
        app.desktop_class.close_desktop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--build", action="store_true")
    group.add_argument("--solve", action="store_true")
    parser.add_argument("--aedt-version", default=None)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "design/v3/maxwell/local_runs")
    args = parser.parse_args()
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    case = load_case(data, args.case)
    problems = blockers(data, case)
    if problems:
        print(json.dumps({"case": case["id"], "status": "BLOCKED",
                          "blockers": problems, "maxwell_executed": False,
                          "fab_release": False}, indent=2))
        if not args.check:
            raise SystemExit(2)
        return
    if args.check:
        print("PRECHECK_OK: inputs present; Maxwell geometry, BH and coils still require GUI review")
        return
    build(data, case, solve=args.solve, output=args.output / case["id"],
          version=args.aedt_version)


if __name__ == "__main__":
    main()
