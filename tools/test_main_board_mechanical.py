"""A5 gates: the 1:1 power-stage placement has to be a checkable claim.

`hardware/dcx_mech/power_stage_placement.kicad_pcb` is a placement study, not a
routed board.  It carries the netlist on its pads so the ratsnest can be counted,
but there are no tracks, and every net is unconnected by design.  That means the
usual DRC gates (unconnected items, clearance) say nothing here, and a board file
that merely *parses* proves nothing either.

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

EVIDENCE = {"datasheet", "generated-json", "digitised-datasheet", "kicad-library",
            "PROVISIONAL"}


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
    magnetics = [p for p in mbm.PARTS if p.footprint in mbm.CORE_FOOTPRINTS]
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
                 "power_stage_placement.kicad_pro", "placement_report.json",
                 "dcx.pretty/BSC010N04LS6.kicad_mod"):
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
    """Anything not generated by this tool must be in hardware/stock_footprints.

    Nothing is borrowed on this board any more -- the SR FET land pattern is
    generated from the datasheet measurement -- but the rule stays live,
    because a part pointed at a library the project cannot see gets its
    courtyard skipped silently by DRC."""
    # Same re-keying board_file() uses: library files are named by stem, the
    # parts reference "dcx:<stem>".
    generated = {f"dcx:{Path(name).stem}" for name in mbm.footprint_library()}
    borrowed = {p.footprint for p in mbm.PARTS if p.footprint not in generated}
    if not borrowed:
        return
    provenance = (mbm.STOCK / "PROVENANCE.md").read_text(encoding="utf-8")
    for lib_id in sorted(borrowed):
        assert mbm.stock_footprint_path(lib_id).exists(), f"{lib_id} is not vendored"
        assert lib_id.split(":", 1)[1] in provenance, f"{lib_id} has no provenance entry"


def test_the_sr_fet_land_is_generated_from_the_datasheet_measurement():
    """The vendored TDSON-8 numbered all five drain lands "5", which left
    schematic drain pins 6-8 without a pad of their own.  The replacement is
    generated by the module that digitised the land figure, so the board cannot
    silently keep the old part -- and it must be labelled as a measurement, not
    as vendor CAD or a library copy."""
    sr = [p for p in mbm.PARTS if p.ref.startswith("SR")]
    assert len(sr) == 8
    assert {p.footprint for p in sr} == {"dcx:BSC010N04LS6"}
    assert {p.evidence for p in sr} == {"digitised-datasheet"}
    assert "BSC010N04LS6.kicad_mod" in mbm.footprint_library()
    # the land builder refuses a measurement whose own checks failed
    import make_sr_fault_board_pcb as srpcb
    land = json.loads((mbm.ROOT / "design/v3/pcb/bsc010n04ls6_land.json")
                      .read_text(encoding="utf-8"))
    assert land["checks"] and all(land["checks"].values())
    assert srpcb.bsc_source() == mbm.footprint_library()["BSC010N04LS6.kicad_mod"]
    # a measured land pattern is not a provisional one -- the old substring
    # test on the note put all eight FETs on the provisional list, and QH/QL
    # were the last two boxes until their own figures were digitised
    provisional = mbm.report()["land_pattern_provisional"]
    assert provisional == [], provisional


def test_the_primary_fets_land_is_generated_from_the_two_figures():
    """QH/QL used to sit on a generic ``SON_5x6`` box: nine schematic pins on
    nine pads of unspecified size.  The datasheet draws both the land (sect.
    7.2, a MIN/MAX table) and the stencil (sect. 7.3, callouts on the figure),
    so the footprint is now derived from those drawings and labelled as a
    measurement rather than as vendor CAD."""
    hs = [p for p in mbm.PARTS if p.ref in ("QH", "QL")]
    assert len(hs) == 2
    assert {p.footprint for p in hs} == {"dcx:CSD19531Q5A"}
    assert {p.evidence for p in hs} == {"digitised-datasheet"}
    assert "CSD19531Q5A.kicad_mod" in mbm.footprint_library()
    assert "Placeholder_SON_5x6.kicad_mod" not in mbm.footprint_library()
    import csd19531q5a_land as csd
    land = json.loads((mbm.ROOT / "design/v3/pcb/csd19531q5a_land.json")
                      .read_text(encoding="utf-8"))
    assert land["checks"] and all(land["checks"].values())
    assert csd.footprint_text(land) == mbm.footprint_library()["CSD19531Q5A.kicad_mod"]


def test_the_footprint_directory_holds_only_footprints_the_board_uses():
    """``write()`` adds files but never prunes, and ``fp-lib-table`` points at
    the whole directory -- so a deleted placeholder stays loadable by name until
    its file is removed too."""
    on_disk = {p.name for p in (mbm.OUT / "dcx.pretty").glob("*.kicad_mod")}
    assert on_disk == set(mbm.footprint_library())


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
    cores = [p for p in mbm.PARTS if p.footprint in mbm.CORE_FOOTPRINTS]
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


def test_oem_A720_max_height_carries_into_all_15_placed_parts():
    from cout_bank import CANDIDATES
    part=next(p for p in CANDIDATES if p["mpn"]=="KEMET A720V477M2R5APE003")
    assert part["height_mm"]==2.1
    physical=[p for p in mbm.report()["parts"] if p["ref"].startswith("Cout")]
    assert len(physical)==15
    assert all(p["h_mm_worst"]==2.1 for p in physical)


# ---------------------------------------------------------------- nets
def test_the_bank_refs_collide_with_nothing_the_schematic_already_uses():
    """The bank used to be C100-C114, but the schematic spends C101-C112 on the
    twelve IC decoupling capacitors.  Two parts sharing one designator is not a
    style problem: it is a 470 uF bulk part cross-referenced onto an 0603
    position the moment anyone compares the board with the BOM."""
    schematic = {r["ref"] for r in mbm.review_rows()}
    bank = {p.ref for p in mbm.PARTS if p.ref.startswith(mbm.BANK_PREFIX)}
    assert len(bank) == 15
    assert not bank & schematic
    assert "C101" in schematic, "the collision this rename avoids must still exist"


def test_every_landed_net_is_the_one_the_review_table_says():
    """Nets land on pads by *name*.  A pad whose name the table does not carry
    (the Lr's N1/N2 versus its "1"/"2", the U2 outline with no pads) silently
    drops off the board, and the ratsnest looks complete without it."""
    for part in mbm.PARTS:
        got = mbm.part_nets(part)
        if part.ref.startswith(mbm.BANK_PREFIX):
            assert set(got) == {"1", "2"}          # borrowed from the lumped Cout
            continue
        assert all(pad in mbm._pad_positions(part.footprint) for pad in got)
        assert set(got) == _expected_pads(part), part.ref


def _expected_pads(part) -> set[str]:
    """Independent read of the review table: a part's pads must be exactly the
    rows naming it, restricted to pads its footprint shows."""
    rows = [r for r in mbm.review_rows() if r["ref"] == part.ref and r["net"].strip()]
    local = set(mbm._pad_positions(part.footprint))
    return {r["pad"] for r in rows} & local


def test_a_part_the_table_has_no_row_for_carries_no_net():
    table = mbm.pad_nets()
    for part in mbm.PARTS:
        if part.ref not in table and not part.ref.startswith(mbm.BANK_PREFIX):
            assert mbm.part_nets(part) == {}, part.ref


def test_the_padless_outline_is_not_counted_as_a_connection():
    """U2 stands for the whole control section and has no pads.  Returning its
    eleven table rows anyway put it in the ground net, which would make the
    board report a connection that has no copper behind it."""
    u2 = next(p for p in mbm.PARTS if p.ref == "U2")
    assert mbm.pad_nets()[u2.ref], "the table does list U2 pins; it is the footprint that has none"
    assert mbm.part_nets(u2) == {}
    assert not mbm._pad_positions("dcx:Placeholder_12x12")


def test_the_sr_drain_pins_now_have_pads_of_their_own():
    """The vendored TDSON-8 numbered all five drain lands "5", so symbol pins
    6, 7 and 8 had no pad and the report listed 24 padless pins.  The digitised
    land pattern carries a finger per pin, so the list must now contain no SR
    pin at all -- the remaining entries are U2, whose outline stands for a
    whole functional block and has no pads by design."""
    report = mbm.nets_report()
    groups = report["netlist_pins_without_a_physical_pad"]
    flat = [x for v in groups.values() for x in v]
    assert not [x for x in flat if x.startswith("SR")], flat
    assert len(flat) == 10 and all(x.startswith("U2.") for x in flat), flat
    assert len(groups) == 1, "one reason, and it is the padless outline"
    assert any("no pads at all" in k for k in groups)
    # the pads exist as copper, not just as names
    positions = mbm._pad_positions("dcx:BSC010N04LS6")
    assert {str(n) for n in positions} == {"1", "2", "3", "4", "5", "6", "7", "8"}
    report = mbm.report()
    assert report["nets"]["netlist_pins_without_a_physical_pad"]


def test_the_two_pad_counts_are_both_reported_because_they_differ():
    """KiCad treats same-numbered pads of one footprint as one connected pad, so
    160 copper pads draw 144 pad entities.  Twice per SR FET: the drain base and
    one finger both carry the name 5, the source bar and one finger both carry 1.
    Reporting only one of the two numbers makes the other look like a missing
    connection.

    The ratsnest is shorter again (74, not 144 - 30) because KiCad also merges
    same-net lands whose copper overlaps -- the fingers sit 0.125 mm inside the
    base and bar.  That identity is deliberately not asserted: it is a
    connectivity-engine detail, not a property of the part table."""
    nets = mbm.nets_report()
    assert nets["physical_pads_netted"] > nets["pads_landed"]
    assert nets["physical_pads_netted"] - nets["pads_landed"] == 8 * 2
    board = (mbm.OUT / "power_stage_placement.kicad_pcb").read_text(encoding="utf-8")
    board_level = len(re.findall(r'^\t\(net \d+ "', board, re.M))
    assert board_level == nets["net_count"]
    assert board.count("(net ") - board_level == nets["physical_pads_netted"]


def test_the_four_secondary_groups_are_drawn_the_same_length():
    """The four SR groups are electrically identical, so a placement that gives
    one of them materially more copper than the others has broken the current
    sharing assumption before a single track is routed."""
    rows = {n["net"]: n for n in mbm.nets_report()["nets"]}
    for suffix in ("_A", "_B"):
        lengths = [rows[f"SEC{i}{suffix}"]["straight_line_mst_mm"] for i in range(1, 5)]
        assert len({round(x, 6) for x in lengths}) == 1, (suffix, lengths)
        # six pads: the transformer terminal, the four drain fingers (suffix _A)
        # or the source bar and its three fingers (_B), plus the Kelvin link's
        # SEC pad since package C placed R28-R35 (pad names, so the repeated
        # "5" counts once -- see physical_pads_netted)
        pad_counts = {rows[f"SEC{i}{suffix}"]["pads"] for i in range(1, 5)}
        assert pad_counts == {6}


def test_a_one_pad_net_is_listed_rather_than_read_as_routed():
    """Twenty nets still end in exactly one pad, and each for a stated reason.

    Package C turned GH/GL/GA*/GB* into two-pad nets by placing the gate
    resistors, but the driver *side* of each of those resistors is now the
    single-pad end (VG*_A/B, GH_DRV, GL_DRV) -- the driver lives on the control
    board.  The Kelvin links add VD*_A/B the same way.  CS1/CS2 stay because
    their rectifier sits in the padless U2 outline.  A net with one pad draws no
    ratsnest line, so nothing else would ever flag them.
    """
    nets = mbm.nets_report()
    single = set(nets["single_pad_nets"])
    assert single == {"CS1", "CS2", "GH_DRV", "GL_DRV"} | {
        f"{kind}{i}_{side}"
        for kind in ("VD", "VG") for i in range(1, 5) for side in ("A", "B")}
    assert len(single) == 20
    assert "owes no track" in nets["single_pad_nets_note"]


def test_every_gate_resistor_lands_directly_under_the_gate_it_serves():
    """Doc 34, package C: the gate resistors and Kelvin links go on this board.

    The point of deriving their centres from the FET land patterns is that each
    tap is one straight vertical track into the pad it serves.  That is also why
    the rows sit *below* the FETs: from above, the gate tap has to pass the
    source strip (0.10 mm of overlap at this x) and the inter-pad channel is
    0.615 mm against the 0.775 mm a 0.25 mm track needs with clearance and the
    half-pitch margin.
    """
    by_ref = {p.ref: p for p in mbm.PARTS}
    res = mbm._pad_positions(mbm.R0603_FP)
    sr = mbm._pad_positions("dcx:BSC010N04LS6")
    q5 = mbm._pad_positions("dcx:CSD19531Q5A")
    checked = 0
    for ref, fet, pads, fet_pad, res_pad in (
            [(f"R{20 + 2 * (i - 1)}", f"SR{i}A", sr, "4", "2") for i in range(1, 5)]
            + [(f"R{21 + 2 * (i - 1)}", f"SR{i}B", sr, "4", "2") for i in range(1, 5)]
            + [(f"R{28 + 2 * (i - 1)}", f"SR{i}A", sr, "5", "1") for i in range(1, 5)]
            + [(f"R{29 + 2 * (i - 1)}", f"SR{i}B", sr, "5", "1") for i in range(1, 5)]
            + [("R4", "QH", q5, "4", "2"), ("R5", "QL", q5, "4", "2")]):
        part, transistor = by_ref[ref], by_ref[fet]
        assert part.footprint == mbm.R0603_FP, ref
        assert part.rot == 0, (ref, "extract_pads ignores rotation; only 0 works")
        want = transistor.x + pads[fet_pad][0]
        got = part.x + res[res_pad][0]
        assert abs(got - want) < 1e-9, (ref, fet, got, want)
        assert part.y > transistor.y + transistor.d_mm / 2, (
            ref, "the resistor must sit below the FET, not above it")
        checked += 1
    assert checked == 18


def test_the_resistor_values_come_from_the_register_not_the_review_table():
    """The review table still calls all eighteen "PLACEHOLDER 0603 10k".

    A 10 k gate resistor would slow a real SR edge by an order of magnitude and a
    10 k Kelvin link would not sense anything, so the value has to come from the
    register that owns it -- and that has to be checked against the file, not
    against a constant in the test.
    """
    eco = json.loads(mbm.ECO.read_text(encoding="utf-8"))["rows"]
    stated = {r["ref"]: r["existing_value_or_rating"] for r in eco}
    plate = {p.ref: p.value for p in mbm.PARTS if p.footprint == mbm.R0603_FP}
    assert sorted(plate) == sorted([f"R{i}" for i in (4, 5)] + [f"R{i}" for i in range(20, 36)])
    for ref, value in plate.items():
        assert value.split()[0] in stated[ref], (ref, value)
        assert value == " ".join(stated[ref].split(";")[0].split()[:2])
    assert {plate[f"R{i}"] for i in range(20, 28)} == {"2.2 ohm"}
    assert {plate[f"R{i}"] for i in range(28, 36)} == {"0 ohm"}
    assert {plate["R4"], plate["R5"]} == {"2.2 ohm"}


def test_the_lumped_cout_is_disclosed_rather_than_counted_as_fifteen_parts():
    nets = mbm.nets_report()
    lump = nets["lumped_from_one_netlist_element"]
    (key,) = lump.keys()
    assert key.startswith("Cout1..Cout15")
    assert "BOM" in lump[key]


def test_the_board_declares_every_net_it_places():
    """A ``(net N "NAME")`` child on a pad is a reference to the board's net
    table; an undeclared one is what KiCad reports as a dangling reference."""
    board = (mbm.OUT / "power_stage_placement.kicad_pcb").read_text(encoding="utf-8")
    declared = set(re.findall(r'^\t\(net \d+ "([^"]*)"\)', board, re.M))
    assert len(declared) == mbm.nets_report()["net_count"]
    used = set(re.findall(r'\(net \d+ "([^"]*)"\)', board))
    assert used == declared, used - declared


def test_the_committed_board_is_netted_and_says_it_is_not_routed():
    board = (mbm.OUT / "power_stage_placement.kicad_pcb").read_text(encoding="utf-8")
    assert "NETTED PLACEMENT" in board
    assert "no routing" in board
    assert mbm.report()["nets"]["status"] == "NETTED_PLACEMENT_NOT_ROUTED"
