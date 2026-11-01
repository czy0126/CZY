"""A5 gates: the 1:1 power-stage placement has to be a checkable claim.

`hardware/dcx_mech/power_stage_placement.kicad_pcb` is a placement study, not a
routed board -- there are no nets, no tracks, and every pad is unconnected by
design.  That means the usual DRC gates (unconnected items, clearance) say
nothing here, and a board file that merely *parses* proves nothing either.

So the gates are the two questions a placement study exists to answer:

* does every outline fit inside the board without touching its neighbour, and
* does the stack of parts fit under the 10 mm height limit?

The second one is the reason this deliverable exists at all: five ELP32 cores
at 9.8 mm worst case.  The height JSON's flat-board case is 9.94 mm, i.e. it
clears 10 mm by 60 um -- a number that is a coincidence, not a margin -- and
the 0.5 mm clamp case is 10.44 mm, over.  A placement document that quietly
drops that finding would look like progress and be the opposite, so
`test_the_flat_board_clears_the_limit_by_less_than_a_manufacturing_tolerance`
asserts the *margin is unreal*, and the clamp failure with it: if someone later
edits the numbers until the flat board "comfortably passes", this goes red.

The mechanical board is regenerated from one table, so the last test keeps the
committed `.kicad_pcb` byte-identical to what the table produces -- the same
stale-generated-file contract `tools/ci_check.py` enforces elsewhere.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_board_mechanical as mbm  # noqa: E402

EVIDENCE = {"datasheet", "generated-json", "kicad-library", "PROVISIONAL"}


def test_no_two_parts_overlap():
    """Bounding boxes must not touch.  `overlaps()` returns a pair whenever the
    intersection area is positive, so an exact edge contact (area 0) is allowed
    and a 0.01 mm intrusion is not."""
    bad = mbm.overlaps(mbm.PARTS)
    assert bad == [], [f"{a} x {b} by {area:.2f} mm^2" for a, b, area in bad]


def test_every_part_is_inside_the_board_outline():
    w, d = mbm.board_rect(mbm.PARTS)
    for part in mbm.PARTS:
        x0, y0, x1, y1 = mbm.bbox(part)
        assert 0.0 <= x0 and x1 <= w, f"{part.ref} sticks out in x: {x0:.2f}..{x1:.2f} of {w:.2f}"
        assert 0.0 <= y0 and y1 <= d, f"{part.ref} sticks out in y: {y0:.2f}..{y1:.2f} of {d:.2f}"


def test_every_dimension_states_its_evidence_class():
    """The whole document is worthless if a provisional case size travels
    without its label.  Three classes are allowed and PROVISIONAL is the only
    one that may appear in the "assumed" list of the report."""
    for part in mbm.PARTS:
        assert part.evidence in EVIDENCE, f"{part.ref}: {part.evidence!r}"
        if part.evidence == "PROVISIONAL":
            assert part.note, f"{part.ref} is assumed but carries no note saying what is assumed"
    report = mbm.report()
    assumed = {p["ref"] for p in report["parts"] if p["evidence"] == "PROVISIONAL"}
    assert assumed == {p.ref for p in mbm.PARTS if p.evidence == "PROVISIONAL"}
    assert assumed, "every dimension provisional means the table is a guess; state it"


def test_the_flat_board_clears_the_limit_by_less_than_a_manufacturing_tolerance():
    """The mechanical finding, asserted as a *thin* margin on purpose.

    9.94 mm against a 10 mm limit is 60 um.  Nothing on a first article is
    specified to 60 um: glue dispense, label thickness and core flatness are
    each larger than that.  Adding the 0.5 mm clamp -- the obvious way to hold
    five loose cores down -- puts the same stack at 10.44 mm, over the limit.

    So the placement has to say two things at once: every outline fits in X/Y,
    and the Z stack does not fit at all unless the cores sit in pockets.
    """
    magnetics = [p for p in mbm.PARTS if p.footprint == mbm.ELP32_FP]
    assert len(magnetics) == 5, "T1-T4 and Lr are all on ELP32"
    report = mbm.report()
    height = report["height"]
    assert height["parts_max_height_mm"] <= mbm.HEIGHT_LIMIT_MM, (
        "a bare part taller than the limit makes the board impossible; the "
        "pocket rescues the stack, a larger limit would not")
    assert height["flat_board_margin_mm"] < 0.1, (
        "the flat board only 'passes' by 60 um -- if this number grew, someone "
        "changed the height stack and has to re-read this section, not relax it")
    assert height["clamp_case_margin_mm"] < 0.0, "the clamp case is the one that fails"
    assert height["pocket_required_refs"] == sorted(p.ref for p in magnetics)
    # the input terminal is a second, independent 10.0 mm user of the same budget
    assert "J_IN" in height["at_limit_refs"]


def test_the_lr_shares_the_transformer_core_so_it_shares_the_pocket():
    """Lr is on the same ELP32 as T1-T4 (lr_design.json), so a mechanical
    drawing that pockets only the transformers would fail on the bench."""
    lr = next(p for p in mbm.PARTS if p.ref == "Lr")
    t1 = next(p for p in mbm.PARTS if p.ref == "T1")
    assert (lr.w_mm, lr.d_mm) == (t1.w_mm, t1.d_mm)


def test_the_committed_board_is_what_the_table_produces(tmp_path):
    """Regenerate into a temp directory and compare bytes.

    Timestamps are excluded from the board file for exactly this reason; a
    generated artifact that changes on every run cannot be checked by a diff
    and hides real edits behind noise."""
    mbm.write(tmp_path)
    for name in ("power_stage_placement.kicad_pcb", "fp-lib-table",
                 "power_stage_placement.kicad_pro", "placement_report.json"):
        committed = mbm.OUT / name
        assert committed.exists(), f"{name} is not committed"
        # Autocrlf rewrites this working copy on checkout; the generator always
        # writes LF, so compare with line endings normalised.  `current_manifest.sha256()`
        # does the same thing for the same reason.
        assert _normalised(committed) == _normalised(tmp_path / name), (
            f"{name} is stale -- run python tools/main_board_mechanical.py")


def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_the_report_lists_every_part_once():
    report = mbm.report()
    refs = [p["ref"] for p in report["parts"]]
    assert len(refs) == len(set(refs))
    assert set(refs) == {p.ref for p in mbm.PARTS}
    json.dumps(report)                       # must be serialisable as-is


def test_the_committed_svg_is_drawn_at_one_to_one():
    """``--scale 1 --page-size-mode 2`` crops the page to the board, so the SVG's
    ``width`` is the board's real size in millimetres.  That is the whole point
    of a 1:1 drawing: someone can print it and lay a core on it.  A "fit to
    page" export would tile the same geometry at some arbitrary scale and read
    identically to the eye, so the number is what has to be checked."""
    svg = (mbm.OUT / "placement_1to1.svg").read_text(encoding="utf-8")
    match = re.search(r'width="([0-9.]+)mm"', svg)
    assert match, "the SVG is not in millimetres"
    w, _ = mbm.board_rect()
    # KiCad crops to the drawn extents, so a few hundredths of a millimetre of
    # line width is expected; a fit-to-page scaling would be off by any amount.
    assert abs(float(match.group(1)) - w) < 0.5, f"{match.group(1)} mm wide for a {w} mm board"


def test_the_document_quotes_the_report_it_describes():
    """`design/v3/A5_机械布置_2026-11-01.md` is the only thing a person reads
    before laying a core on the drawing.  Its numbers must come from
    `placement_report.json`, and its provisional list must come from the parts
    table -- a hand-written "all sizes verified" would otherwise outlive the
    data it describes."""
    doc = (mbm.OUT.parent.parent / "design/v3/A5_机械布置_2026-11-01.md").read_text(encoding="utf-8")
    doc = doc.replace("−", "-")          # the tables use a real minus sign
    data = mbm.report()
    assert f"{data['board']['width_mm']:.1f} × {data['board']['depth_mm']:.1f} mm" in doc
    assert f"{data['clearance']['min_gap_mm']:.1f} mm" in doc
    height = data["height"]
    assert f"{height['flat_board_worst_case_mm']:.2f} mm" in doc
    assert f"{height['flat_board_margin_mm']:+.2f} mm" in doc
    assert f"{height['clamp_case_worst_case_mm']:.2f} mm" in doc
    assert f"{height['clamp_case_margin_mm']:+.2f} mm" in doc
    for ref in data["provisional"]:
        assert ref in doc, f"{ref} is provisional but the document does not say so"
    assert "沉槽" in doc, "the pocket requirement is the whole point of this document"


KICAD_CLI = mbm.find_kicad_cli()
# A skip here means the DRC was **not re-run**; it is never a pass.  Say so in
# the reason so a green CI run on a machine without KiCad is not read as "the
# board was re-checked".
NO_KICAD = pytest.mark.skipif(
    KICAD_CLI is None,
    reason="kicad-cli not found (KICAD_CLI / PATH / standard install): the DRC was "
           "NOT reproduced -- the committed drc.json is the last real run")


@NO_KICAD
def test_kicad_reports_no_drc_errors_and_no_unknown_footprints(tmp_path):
    """Two separate assertions, because they fail for different reasons.

    * Errors: a placement study gets none only if the courtyards really do not
      touch -- this is DRC re-checking the python `overlaps()` test with a
      different engine, which is worth having.
    * `lib_footprint_issues`: the trap already documented for the schematic
      side.  A footprint from a library the project cannot see is silently
      treated as a black box, so its courtyard is not checked either.
    """
    out = tmp_path / "drc.json"
    subprocess.run([str(KICAD_CLI), "pcb", "drc", "--format", "json",
                    "--severity-all", "-o", str(out), str(mbm.OUT / "power_stage_placement.kicad_pcb")],
                   check=False, capture_output=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    violations = data.get("violations", [])
    errors = [v for v in violations if v["severity"] == "error"]
    assert errors == [], [f"{v['type']}: {v['description']}" for v in errors[:5]]
    unknown = [v for v in violations if v["type"] == "lib_footprint_issues"]
    assert unknown == [], [v["description"] for v in unknown[:5]]


# ---------------------------------------------------------------- Issue #11
# The generator used to hardcode C:\Users\<user>\...\KiCad\10.0, so
# test_the_committed_board_is_what_the_table_produces failed on any other
# machine -- including the Windows CI runner.  The board is reproducible again
# only if these gates hold *without* a KiCad install.
def test_the_generator_names_no_user_directory():
    """No absolute path, and in particular no home directory, in the source."""
    text = Path(mbm.__file__).read_text(encoding="utf-8")
    assert "C:\\Users" not in text and "/Users/" not in text, (
        "a user directory is hardcoded again; locate KiCad with find_kicad_cli() "
        "and footprints with stock_footprint_path()")
    for path in re.findall(r'Path\(r?["\']([A-Za-z]:[^"\']*)', text):
        pytest.fail(f"absolute path {path!r} in the generator; it will not exist elsewhere")


def test_every_borrowed_footprint_is_vendored_with_provenance():
    """Anything not generated by this tool must be in hardware/stock_footprints."""
    # Same re-keying board_file() uses: library files are named by stem, the
    # parts reference "dcx:<stem>".
    generated = {f"dcx:{Path(name).stem}" for name in mbm.footprint_library()}
    borrowed = {p.footprint for p in mbm.PARTS if p.footprint not in generated}
    assert borrowed, "nothing borrowed -- drop this test if that is really true"
    provenance = (mbm.STOCK / "PROVENANCE.md").read_text(encoding="utf-8")
    for lib_id in sorted(borrowed):
        assert mbm.stock_footprint_path(lib_id).exists(), f"{lib_id} is not vendored"
        assert lib_id.split(":", 1)[1] in provenance, f"{lib_id} has no provenance entry"


def test_regeneration_needs_no_kicad_install(tmp_path, monkeypatch):
    """Scrub every KiCad hint and the board must still come out byte-identical.

    This is the test the CI runner needed: it simulates a machine with no KiCad
    at all by removing KICAD_CLI / KICAD_SHARE and both Windows install roots
    from the environment it sees.
    """
    for name in ("KICAD_CLI", "KICAD_SHARE", "LOCALAPPDATA", "PROGRAMFILES",
                 "PROGRAMFILES(X86)"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert mbm.find_kicad_cli() is None
    mbm.write(tmp_path)
    for name in ("power_stage_placement.kicad_pcb", "power_stage_placement.kicad_pro"):
        assert _normalised(tmp_path / name) == _normalised(mbm.OUT / name), (
            f"{name} does not reproduce without KiCad -- a vendored input is missing")


def test_a_missing_vendored_footprint_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(mbm, "STOCK", tmp_path / "nowhere")
    with pytest.raises(SystemExit) as exc:
        mbm._stock_footprint("Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm")
    message = str(exc.value)
    assert "PROVENANCE.md" in message and "home directory" in message


def test_the_project_raises_missing_courtyard_to_error():
    """The DRC result is only worth quoting if this check is actually on.

    KiCad's shipped severity for `missing_courtyard` is *ignore*, so the old
    project file reported `ignored_checks: 5` and a board with no courtyards at
    all would have passed -- exactly what Issue #11 flagged."""
    project = json.loads((mbm.OUT / "power_stage_placement.kicad_pro")
                         .read_text(encoding="utf-8"))
    severities = project["board"]["design_settings"]["rule_severities"]
    assert severities["missing_courtyard"] == "error"


def _drop_first_courtyard(text: str) -> str:
    """Remove the first ``(fp_rect ... F.CrtYd ...)`` block, paren-matched."""
    search_from = 0
    while (start := text.find("(fp_rect", search_from)) != -1:
        depth, end = 0, start
        while end < len(text):
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            if depth == 0:
                break
            end += 1
        if "F.CrtYd" in text[start:end + 1]:
            return text[:start] + text[end + 1:]
        search_from = end + 1
    return text


@NO_KICAD
def test_the_courtyard_check_can_fail(tmp_path):
    """Falsification: drop one courtyard and KiCad must report an error.

    Without this, `test_kicad_reports_no_drc_errors...` is satisfied equally by
    a board that is clean and by a board whose courtyards are never examined.
    """
    text = (mbm.OUT / "power_stage_placement.kicad_pcb").read_text(encoding="utf-8")
    broken = _drop_first_courtyard(text)
    assert broken != text, "no courtyard found to remove"
    (tmp_path / "broken.kicad_pcb").write_text(broken, encoding="utf-8", newline="\n")
    (tmp_path / "broken.kicad_pro").write_text(
        (mbm.OUT / "power_stage_placement.kicad_pro").read_text(encoding="utf-8"),
        encoding="utf-8", newline="\n")
    (tmp_path / "fp-lib-table").write_text(
        (mbm.OUT / "fp-lib-table").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    shutil.copytree(mbm.OUT / "dcx.pretty", tmp_path / "dcx.pretty")
    out = tmp_path / "drc.json"
    subprocess.run([str(KICAD_CLI), "pcb", "drc", "--format", "json", "--severity-all",
                    "-o", str(out), str(tmp_path / "broken.kicad_pcb")],
                   check=False, capture_output=True)
    violations = json.loads(out.read_text(encoding="utf-8")).get("violations", [])
    assert any(v["type"] == "missing_courtyard" and v["severity"] == "error"
               for v in violations), [v["type"] for v in violations]


def test_the_vendored_footprint_matches_the_installed_library():
    """Cross-check the copy against a real KiCad install, when there is one."""
    share = mbm.find_kicad_share()
    if share is None:
        pytest.skip("no KiCad install found: the vendored copy was NOT compared "
                    "against the official library here")
    installed = share / "footprints" / "Package_SON.pretty" / \
        "Infineon_PG-TDSON-8_6.15x5.15mm.kicad_mod"
    if not installed.exists():
        pytest.skip(f"{installed} is not in this KiCad install; nothing to compare")
    assert (_normalised(installed)
            == _normalised(mbm.stock_footprint_path(
                "Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm"))), (
        "the vendored footprint no longer matches the installed library -- "
        "update the copy and PROVENANCE.md together")


# ---------------------------------------------------------------- Issue #12
# The first blocking question in #12 is what "≤10 mm" even measures.  These
# gates keep the answer -- a datum, a tolerance chain, and an explicit hole
# where TIM / cold plate / fasteners would go -- from drifting back into a
# single number that looks signed off.
def test_the_section_states_a_datum_and_leaves_the_undefined_as_none():
    """A height with no datum is not a drawing.

    Everything in ``PARTS`` is measured above the PCB top, but nothing above
    that is defined anywhere in this repo.  So the section has to name the
    datum and carry ``None`` for the case that includes TIM and a cold plate,
    because filling that number in from imagination is the failure mode.
    """
    section = mbm.mechanical_section()
    assert "PCB" in section["datum"] and "Z = 0" in section["datum"]
    assert section["definitions"]["D_with_tim_and_cold_plate_mm"] is None
    assert len(section["undefined_above_the_stack"]) >= 3
    for item in ("TIM", "冷板", "紧固件"):
        assert any(item in x for x in section["undefined_above_the_stack"]), item
    assert "未签核" in section["gate"]


def test_the_pocket_only_buys_back_the_clamp():
    """The uncomfortable number, asserted so it cannot be quietly improved.

    0.5 mm of pocket and 0.5 mm of clamp cancel: C equals A to the micron.
    Anyone reading "we pocketed the cores, so we fit" is being told something
    true and useless -- the margin is the original 60 um either way.
    """
    d = mbm.mechanical_section()["definitions"]
    assert d["C_pocket_0p5_with_clamp_mm"] == pytest.approx(
        d["A_flat_no_pocket_no_clamp_mm"], abs=1e-3)
    assert d["B_pocket_0p5_no_clamp_mm"] < d["A_flat_no_pocket_no_clamp_mm"]


def test_the_section_agrees_with_the_magnetics_height_stack():
    """Two independent sums of the same stack must match.

    `mechanical_section()` sums its own rows; `magnetics_design.json` sums its
    own.  If they disagree the generator raises, so this test only has to prove
    the check is live: perturb the glue constant and the section must refuse.
    """
    import magnetics_design as md
    json_worst = (mbm._load("magnetics/magnetics_design.json")["height"]
                  ["flat_no_pocket"]["worst_case_m"] * 1e3)
    core = float(md.CORE["height_max_m"]) * 1e3
    assert core + mbm.GLUE_MAX_MM + mbm.LABEL_MAX_MM == pytest.approx(json_worst, abs=1e-9)
    original = mbm.GLUE_MAX_MM
    try:
        mbm.GLUE_MAX_MM = original + 0.05
        with pytest.raises(SystemExit) as exc:
            mbm.mechanical_section()
        assert "magnetics_design.json" in str(exc.value)
    finally:
        mbm.GLUE_MAX_MM = original


def test_the_report_carries_the_section():
    section = mbm.report()["section"]
    json.dumps(section, ensure_ascii=False)          # must serialise as-is
    assert section == mbm.mechanical_section()


def test_the_pocket_table_is_derived_from_the_cores_on_the_board():
    """Areas come from the ELP32 outline times the number of cores *placed*,
    not from a remembered count of five."""
    pocket = mbm.pocket_requirements()
    cores = [p for p in mbm.PARTS if p.footprint == mbm.ELP32_FP]
    assert pocket["cores"] == len(cores) == 5
    w, d = mbm.board_rect()
    assert pocket["board_area_mm2"] == pytest.approx(w * d, abs=0.2)
    expected = 31.75 * 25.4 * len(cores)
    assert pocket["pocket_total_mm2"] == pytest.approx(expected, abs=0.2)
    # 20 % of the board is a number a fabricator will react to
    assert 19.0 < pocket["fraction_of_board_pct"] < 21.0


def test_the_pocket_does_not_eat_the_output_plane():
    """The two A6 findings have to be checked against each other.

    A 0.5 mm cavity under every core removes copper; the 100 A plane is already
    three times over budget.  They happen not to collide -- cores at y <= 65,
    the SR-to-busbar channel at y = 82..116 -- but "happen not to" is exactly
    what a later edit can undo."""
    pocket = mbm.pocket_requirements()
    assert pocket["pocket_overlaps_output_plane"] is False
    assert pocket["core_footprint_y_mm"][1] < pocket["output_channel_y_mm"][0]
    assert pocket["checked_non_issues"]


def test_the_pocket_leaves_a_known_dielectric_and_says_it_is_unconfirmed():
    pocket = mbm.pocket_requirements()
    assert pocket["remaining_dielectric_mm"] == pytest.approx(1.1, abs=1e-9)
    # the routed-cavity tolerance moves the remaining layer, so it is a range
    lo, hi = pocket["remaining_dielectric_range_mm"]
    assert lo < 1.1 < hi
    assert pocket["manufacturability"]["status"] == "未询问"
    assert "不得冻结" in pocket["gate"]
    for topic in ("叠层", "绝缘", "板弯"):
        assert any(topic in x for x in pocket["undefined"]), topic


def test_the_report_carries_the_pocket_table():
    pocket = mbm.report()["pocket"]
    json.dumps(pocket, ensure_ascii=False)
    assert pocket == mbm.pocket_requirements()


def test_the_section_document_quotes_the_report():
    """`A6_机械剖面_2026-11-01.md` is what a person reads before believing the
    height claim.  Every number in it has to come from the report.

    Same contract as the A5 document test: a hand-written table outlives the
    data it describes, and the one that matters here is the ``C = A`` equality
    -- if the pocket ever stops cancelling the clamp, the prose is wrong even
    though the JSON is right.
    """
    doc = (mbm.OUT.parent.parent / "design/v3/A6_机械剖面_2026-11-01.md").read_text(encoding="utf-8")
    doc = doc.replace("−", "-")          # the tables use a real minus sign
    section = mbm.report()["section"]
    d = section["definitions"]
    assert f"{d['A_flat_no_pocket_no_clamp_mm']:.2f} mm" in doc
    assert f"{d['B_pocket_0p5_no_clamp_mm']:.2f} mm" in doc
    assert f"{d['C_pocket_0p5_with_clamp_mm']:.2f} mm" in doc
    assert f"{section['clamp_case_margin_mm']:+.2f} mm" in doc
    assert f"{section['pocket_case_margin_mm']:+.2f} mm" in doc
    for row in section["upward"] + section["downward"]:
        assert f"{abs(row['worst_mm']):.2f} mm" in doc, row["item"]
    for item in section["undefined_above_the_stack"]:
        assert item in doc, f"{item} is undefined but the doc omits it"
    assert "Z = 0" in doc and "未签核" in doc
    pocket = mbm.report()["pocket"]
    for key in ("pocket_per_core_mm2", "pocket_total_mm2", "board_area_mm2", "depth_mm"):
        assert f"{pocket[key]:.1f} mm²" in doc or f"{pocket[key]:.1f} mm" in doc, key
    assert f"{pocket['fraction_of_board_pct']:.1f} %" in doc
    assert f"{pocket['remaining_dielectric_mm']:.1f} mm" in doc
    assert pocket["manufacturability"]["status"] in doc


def test_the_committed_drc_report_checked_courtyards():
    """The committed drc.json must come from a run where the check was on."""
    data = json.loads((mbm.OUT / "drc.json").read_text(encoding="utf-8"))
    ignored = data.get("ignored_checks", [])
    keys = [x["key"] if isinstance(x, dict) else x for x in ignored]
    assert "missing_courtyard" not in keys, (
        "the committed DRC ignored missing_courtyard; regenerate with "
        "python tools/main_board_mechanical.py --check")
    assert not [v for v in data.get("violations", []) if v["type"] == "missing_courtyard"]
