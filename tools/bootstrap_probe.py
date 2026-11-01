"""Check the GD2-first bootstrap sequence in the Task 2 startup deck.

SIMULATION ONLY.  The deck uses a behavioural bootstrap (Dbt/Cbt and the
Bgh/Bgl logic blocks) instead of a UCC27282; this probe only asks whether
the sequence that a real bootstrap needs is present:

  1. GD2 (low-side reference) starts switching first.
  2. Cbt charges to >5.5 V through Dbt while the low side is on.
  3. Only then does the high-side gate see a real Vgs.

Usage: python tools/bootstrap_probe.py [deck]
"""

from pathlib import Path

import numpy as np
from PyLTSpice import RawRead

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "startup_ct"
    raw = RawRead(str(ROOT / "sim" / "v2" / f"{name}.raw"))

    def wave(trace: str) -> np.ndarray:
        return np.asarray(raw.get_trace(trace).get_wave(0))

    t = wave("time")
    gd1, gd2 = wave("V(gd1)"), wave("V(gd2)")
    hb, sw = wave("V(hb)"), wave("V(sw)")
    vboot = hb - sw

    t_gd2 = float(t[np.argmax(gd2 > 2.0)]) if np.any(gd2 > 2.0) else float("nan")
    t_gd1 = float(t[np.argmax(gd1 > 2.0)]) if np.any(gd1 > 2.0) else float("nan")
    m_before = t < t_gd1
    print(f"deck                 : {name}")
    print(f"GD2 first high       : {t_gd2 * 1e6:.1f} us")
    print(f"GD1 first high       : {t_gd1 * 1e6:.1f} us  (GD2 leads by {(t_gd1 - t_gd2) * 1e6:.1f} us)")
    print(f"VBoot max before GD1 : {vboot[m_before].max():.3f} V")
    print(f"VBoot at GD1 rise    : {np.interp(t_gd1, t, vboot):.3f} V")
    print(f"VBoot max overall    : {vboot.max():.3f} V")
    m_win = (t >= 0) & (t <= 200e-6)
    print(f"VGD1 max in 0-200 us : {gd1[m_win].max():.3f} V")


if __name__ == "__main__":
    main()
