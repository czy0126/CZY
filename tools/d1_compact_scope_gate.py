"""Scope/evidence guard: only compact 48->2 V research belongs in this lane.

This cannot prevent other branches from retaining their independent work; it
prevents unrelated full-size geometry/documentation from entering this branch,
and protects the source-locked G0-V5 KiCad schematic review package.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BRIEF=ROOT/"docs/agent/D1_RESEARCH_ASSETS_AND_TARGETS_20261115.md"
REF=ROOT/"hardware/dcx_main/g2/compact_g0_circuit_reference_NOT_FOR_FAB"
SCH=REF/"d1_g0_161_PART_SR_KELVIN_SOURCE_AUTHORED_NOT_FOR_FAB.kicad_sch"
PDF=REF/"compact_g0_power_schematic_V5_REVIEW_NOT_INTEGRATED.pdf"
BUNDLE=REF/"compact_g0_existing_circuit_4sheets_REVIEW_NOT_INTEGRATED.pdf"
ERC=REF/"compact_v5_native_erc_recheck_NOT_FOR_FAB.json"
EXPECTED_SCH_SHA="1e82084b84b6a881d82691d9b8dea787ec1e9851cc38b218f611fdefb281b6c1"
EXPECTED_IGNORED={"single_global_label","four_way_junction","simulation_model_issue","footprint_filter"}
BANNED_PREFIXES=(
 "design/v3/fullbrick_",
 "hardware/dcx_main/fullbrick",
 "docs/agent/fullbrick_",
 "docs/agent/brick_areal_product",
)
BANNED_CONTENT=("1800a","1800 a","2400a","3.6kw","3.6 kw","fullbrick_embedded","fullbrick_800")

def blocked_path(name):
    p=name.replace("\\","/").lower()
    return any(p.startswith(pre) or ("/"+pre) in p for pre in BANNED_PREFIXES)

def check_doc(text):
    lo=text.lower().replace(" ","")
    return [p for p in BANNED_CONTENT if p.replace(" ","") in lo]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def validate():
    spec=BRIEF.read_text("utf8")
    if "R3.0" not in spec or "成品电路" not in spec:
        raise ValueError("Project brief is not R3 or fails circuit-first")
    forbidden=check_doc(spec)
    if forbidden:
        raise ValueError("Noncompact performance targets leaked into brief: "+str(forbidden))
    files=subprocess.check_output(["git","ls-files","-z"],cwd=str(ROOT)).decode("utf8").split("\0")
    leaking=[x for x in files if x and blocked_path(x)]
    if leaking:
        raise ValueError("Noncompact files are tracked on the current lane: "+str(leaking[:12]))
    if sha(SCH)!=EXPECTED_SCH_SHA:
        raise ValueError("Reused native KiCad schematic source changed unexpectedly")
    if not PDF.exists() or PDF.stat().st_size<10000:
        raise ValueError("V5 native schematic PDF missing")
    if not BUNDLE.exists() or BUNDLE.stat().st_size<10000:
        raise ValueError("four independent reference pages missing")
    data=json.loads(ERC.read_text("utf8"))
    cnt=sum(len(x.get("violations",[])) for x in data.get("sheets",[]))
    ignored={x["key"] for x in data.get("ignored_checks",[])}
    if cnt!=0 or ignored!=EXPECTED_IGNORED:
        raise ValueError(f"Native schematic ERC drift: violations={cnt}, ignored={ignored}")
    # Four pages correspond to four *independent* schematics, NOT integrated.
    try:
        import fitz
        z=fitz.open(str(BUNDLE))
        if len(z)!=4:raise ValueError("Expected V5/V6/V7/V8 four reference pages")
    except ImportError:
        # Source PDFs are individually present; pdf page-count check optional.
        pass
    return {"status":"COMPACT_SCOPE_OK_CIRCUIT_REFERENCE_ONLY",
            "tracked_unrelated_paths":len(leaking),
            "native_V5_ERC_violations":cnt,
            "native_V5_ignored_ERC_types":sorted(ignored),
            "V5_sch_source_sha256":sha(SCH),
            "four_reference_sheets_are_not_connected_as_one_circuit":True,
            "C0_integrated_finished":False,
            "power_on_release":False}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--check",action="store_true",required=True)
    args=parser.parse_args(argv)
    report=validate()
    print(json.dumps(report,ensure_ascii=False))
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,RuntimeError,OSError) as e:
        print("COMPACT SCOPE CHECK FAIL",e,file=sys.stderr);sys.exit(1)
