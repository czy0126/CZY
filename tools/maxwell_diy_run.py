"""Run genuine Maxwell3D Lr concept solves on an explicitly licensed AEDT host.

The generated ELP38 concept STEP is not OEM geometry. The 100C BH table here
is *synthetic interpolation*, not a measured nonlinear B(H). This workflow is
ONLY for choosing next geometry/gap study; no real L(I), losses or fab approval.

No Maxwell installation or license is available in source-only CI.
  python tools/maxwell_diy_run.py --prepare --case ELP38_Lr_3turn_0920uH
  python tools/maxwell_diy_run.py --build --case ... --accept-synthetic-bh
  python tools/maxwell_diy_run.py --solve --case ... --accept-synthetic-bh

For the validated manufacturer material B-H, use original
tools/maxwell_lr_from_step.py with an independently reviewed real B-H curve.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import maxwell_diy_geometry as geom
import maxwell_lr_from_step as runner

ROOT = geom.ROOT
BH = ROOT / "design/v3/maxwell/N97_100C_ILLUSTRATIVE_NOT_OEM.csv"
BH_PROVENANCE = ROOT / "design/v3/maxwell/N97_100C_ILLUSTRATIVE_NOT_OEM.provenance.json"
ORIGINAL = ROOT / "design/v3/maxwell/elp38_lr_maxwell_contract.json"


def prepare(case_name: str, output: Path, *, generate_geometry: bool) -> dict:
    original = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    case = runner.load_case(original, case_name)
    if generate_geometry:
        geom.build_report(geom.OUT, write=True)
    src = geom.load_spec()
    generated = {x["id"]: x for x in src["cases"]}
    if case_name not in generated:
        raise ValueError("Selected case missing in concept geometry")
    concept = generated[case_name]
    if (case["turns"] != concept["turns"]
            or abs(case["analytic_gap_mm"]-concept["gap_mm"]) > 0.005
            or case["target_inductance_uh"] != concept["target_inductance_uH"]):
        raise ValueError("Stale Lr model vs analytic magnetic contract")
    path = geom.OUT/(case_name + ".step")
    if not path.is_file():
        raise FileNotFoundError(f"Generate the CadQuery STEP first: {path}")
    if not BH.is_file() or not BH_PROVENANCE.is_file():
        raise FileNotFoundError("Missing explicit-surrogate B-H source")
    if runner.check_bh_csv(BH):
        raise ValueError("Invalid B-H surrogate: " + str(runner.check_bh_csv(BH)))
    provenance = json.loads(BH_PROVENANCE.read_text(encoding="utf-8"))
    if (provenance["hardware_approved"] is not False
            or provenance["maxwell_executed"] is not False
            or "NOT_OEM" not in provenance["kind"]):
        raise ValueError("B-H table must remain an unverified surrogate")
    if not src["fabrication_approved"] is False or src["maxwell_solved"] is not False:
        raise ValueError("Concept must not falsely claim validation")
    cfg = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    newcase = runner.load_case(cfg, case_name)
    newcase["step_file"] = path.relative_to(ROOT).as_posix()
    cfg["n97_bh_100c_csv"] = BH.relative_to(ROOT).as_posix()
    cfg["aedt_material_name"] = "N97_100C_ILLUSTRATIVE_NOT_OEM"
    cfg["model_status"] = "DESIGN_OWNED_GEOMETRY_WITH_SYNTHETIC_BH_NOT_OEM"
    cfg["approval"] = {
        "winding_direction_confirmed": False,
        "cad_gap_matches_case": False,
        "geometry_source_reviewed_for_concept": False,
        "bh_curve_source_reviewed_for_concept": False,
        "manufacturer_geometry_verified": False,
    }
    cfg["hardware_fabrication_approved"] = False
    output.mkdir(parents=True, exist_ok=True)
    run_config = output / (case_name + "_non_oem_contract.json")
    run_config.write_text(json.dumps(cfg, indent=2)+"\n", encoding="utf-8")
    source_evidence = {
        "status": "READY_FOR_REAL_AEDT_CONCEPT_RUN_NOT_YET_EXECUTED",
        "case": case_name,
        "concept_step_file": newcase["step_file"],
        "geometry_source_sha256": runner.sha256(geom.CONTRACT),
        "step_sha256": runner.sha256(path),
        "bh_sha256": runner.sha256(BH),
        "bh_provenance_sha256": runner.sha256(BH_PROVENANCE),
        "model_status": "ENGINEER_RECONSTRUCTED_CORE_NOT_OEM",
        "bh_status": "ENGINEERING_SURROGATE_100C_NOT_OEM_MEASUREMENT",
        "fixed_target_l_uH": case["target_inductance_uh"],
        "target_not_guaranteed_by_gap_or_solver": True,
        "physical_winding_turns_not_realized": True,
        "secondary_and_ct_solvers_not_in_this_run": True,
        "maxwell_executed": False,
        "fab_release": False,
    }
    (output/"source_and_limits.json").write_text(
        json.dumps(source_evidence, indent=2)+"\n", encoding="utf-8")
    return cfg


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", action="store_true")
    g.add_argument("--build", action="store_true")
    g.add_argument("--solve", action="store_true")
    p.add_argument("--case", default="ELP38_Lr_3turn_0920uH")
    p.add_argument("--accept-synthetic-bh", action="store_true",
                   help="Only allow conceptual B-H on genuine Maxwell host")
    p.add_argument("--aedt-version", default=None)
    p.add_argument("--output", type=Path, default=ROOT/"design/v3/maxwell/local_runs")
    args = p.parse_args(argv)
    cfg = prepare(args.case, args.output, generate_geometry=args.prepare)
    if args.prepare:
        print("Concept-only STEP and local input contract prepared; Maxwell NOT run.")
        return 0
    if not args.accept_synthetic_bh:
        raise SystemExit("Add --accept-synthetic-bh to use a non-OEM B-H curve; "
                         "run may NEVER qualify hardware.")
    case = runner.load_case(cfg, args.case)
    original_config = runner.CONFIG
    runner.CONFIG = args.output/(args.case+"_non_oem_contract.json")
    try:
        runner.build(cfg, case, solve=args.solve, output=args.output, version=args.aedt_version)
    finally:
        runner.CONFIG = original_config
    print("Maxwell executable returned. Inspect original matrix, meshing, "
          "flux field, material provenance and run_manifest; NO hardware signoff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
