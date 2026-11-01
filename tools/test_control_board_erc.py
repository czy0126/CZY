"""The control-validation board's ERC has to be a report about the circuit.

On 2026-10-31 this board's committed ERC report read "3 warnings, 0 errors",
all three of them ``lib_symbol_issues``: *the library is not in the current
configuration*.  Nothing about the schematic was wrong.  ``kicad-cli`` only
loads a project's ``sym-lib-table`` when a ``.kicad_pro`` sits next to the
schematic; without one ``${KIPRJMOD}`` is undefined, so both project-local
libraries are invisible and every symbol from them is flagged.

The trap this file guards is that those warnings look like design defects.
Three "unknown library" warnings on U1/Q1/Q2 invite a reader to go and edit
the symbols -- which would change nothing -- instead of adding the missing
project file.  Two tests, one for the cause and one for the effect:

* the static one runs everywhere (CI has no KiCad) and fails the moment the
  project file or a ``${KIPRJMOD}`` target is missing;
* the live one re-runs ERC when ``kicad-cli`` is installed and requires zero
  violations at *every* severity.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_control_board as mcb  # noqa: E402

BOARD = mcb.OUT


def test_the_project_file_carries_the_generated_root_sheet_uuid():
    """A project file whose root-sheet uuid does not match the schematic is
    worse than none: ``kicad-cli`` reports a project with no root sheet and the
    library table still is not read."""
    pro = json.loads(mcb.project_file())
    assert pro["sheets"] == [[mcb.uid("root"), "Root"]]
    sch = (BOARD / "control_validation.kicad_sch").read_text(encoding="utf-8")
    assert f'(uuid "{mcb.uid("root")}")' in sch


def test_every_project_library_points_at_a_file_that_exists():
    """`${KIPRJMOD}` is the project directory; if the target is missing the
    library is equally invisible and the same three warnings come back."""
    table = (BOARD / "sym-lib-table").read_text(encoding="utf-8")
    targets = re.findall(r"\$\{KIPRJMOD\}/([^\"]+)", table)
    assert targets, "sym-lib-table names no project libraries"
    for name in targets:
        assert (BOARD / name).exists(), f"{name} is referenced but not committed"


def test_the_project_file_is_committed_next_to_the_schematic():
    """The static half of the fix, and the reason it does not depend on KiCad
    being installed: CI runs without ``kicad-cli``."""
    assert (BOARD / "control_validation.kicad_pro").exists(), (
        "without a .kicad_pro, kicad-cli never loads sym-lib-table and every "
        "custom-library symbol is reported as an unknown library")


@pytest.mark.skipif(not mcb.KICAD_CLI.exists(), reason="kicad-cli is not installed here")
def test_erc_reports_no_violations_at_any_severity():
    sch = BOARD / "control_validation.kicad_sch"
    out = BOARD / "erc.json"
    subprocess.run([str(mcb.KICAD_CLI), "sch", "erc", "--severity-all", "--format", "json",
                    str(sch), "-o", str(out)], check=False, capture_output=True)
    violations = mcb.erc_violations()
    assert violations == [], [f"{v['severity']} {v['type']}: {v['description']}"
                              for v in violations]
