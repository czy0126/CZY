"""V7 isolated recovery attempt for V6 OCM route after native EDA timeout.

Only changes target filename and receipt prefix; all geometry, source SHA,
native island verification and timeout-safe behavior remain in V6 logic.
The failed V6 original copy must NEVER be reopened for a second --apply.
V7 is NOT_FOR_FAB, even if real native DRC improves.
"""
from pathlib import Path
import route_t530_oem_v6_ocm_one_real_island_join as V6

HERE = Path(__file__).resolve().parent
TARGET = HERE / "dcx_main_board_g2_T530_OEM_DENSITY_B_V7_REAL_OCM_R17_C11_LINK_NOT_FOR_FAB.eprj2"
PREFIX = "g2_t530_oem_v7_ocm_r17_c11"


def configure_for_isolated_trial():
    """Only switch output paths when this specific trial is executed.

    Importing evidence/tests must never change the V6 source-locked behavior.
    """
    V6.TARGET = TARGET
    V6.PREFIX = PREFIX
    V6.PLAN = HERE / (PREFIX + "_route_plan.json")
    V6.DELTA = HERE / (PREFIX + "_drc_delta.json")
    V6.RAW = HERE / (PREFIX + "_drc_raw.json")
    V6.REOPEN = HERE / (PREFIX + "_reopen_readback.json")


if __name__ == "__main__":
    configure_for_isolated_trial()
    raise SystemExit(V6.main())
