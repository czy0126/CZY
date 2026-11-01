"""Plot the REG-sequencing experiment and the 7 ms startup trajectory.

Inputs are the actual LTspice RAW files produced by sim/v2. Nothing here is
hardware evidence; the title of every figure says so.
"""

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PyLTSpice import RawRead  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "design" / "v2"


def load(name: str) -> tuple[np.ndarray, callable]:
    """Return the time vector and a trace accessor for step 0."""
    raw = RawRead(str(ROOT / "sim" / "v2" / f"{name}.raw"))

    def trace(trace_name: str) -> np.ndarray:
        return np.asarray(raw.get_trace(trace_name).get_wave(0))

    return np.asarray(raw.get_trace("time").get_wave(0)), trace


def main() -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax_reg, ax_out, ax_gate, ax_long = axes.flat

    for name, label in [
        ("integrated_oc_proxy", "REG 110-130 us (baseline)"),
        ("startup_seq_test", "REG 130-150 us (delayed)"),
    ]:
        t, get = load(name)
        m = (t >= 90e-6) & (t <= 180e-6)
        ax_reg.plot(t[m] * 1e6, get("V(reg)")[m], label=f"{label}: REG")
        ax_reg.plot(t[m] * 1e6, get("V(pre1)")[m], "--", label=f"{label}: PRE1")
        ax_out.plot(t[m] * 1e6, get("V(out)")[m], label=label)
        ax_gate.plot(t[m] * 1e6, get("V(ga1)")[m], label=label)

    ax_reg.axhspan(1.0, 4.5, color="tab:orange", alpha=0.12)
    ax_reg.axhline(1.5, color="tab:red", lw=0.8, ls=":")
    ax_reg.text(92, 4.6, "pre-arm window REG 1-4.5 V", fontsize=8)
    ax_reg.set_title("REG ramp vs PRE1 latch")
    ax_out.set_title("Output voltage")
    ax_gate.set_title("SR channel-1 gate")
    for ax, ylabel in [(ax_reg, "V (V)"), (ax_out, "V(out) (V)"), (ax_gate, "V(ga1) (V)")]:
        ax.set_xlabel("Time (us)")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.25)

    t, get = load("integrated_oc_long")
    step = max(1, len(t) // 200_000)
    sl = slice(None, None, step)
    ax_long.plot(t[sl] * 1e3, get("V(out)")[sl], label="V(out)")
    ax_long.plot(t[sl] * 1e3, get("V(ss)")[sl], label="V(ss)")
    ax_long.plot(t[sl] * 1e3, get("V(pre1)")[sl], label="V(pre1)", ls="--")
    ax_long.set_title("7 ms run: truncated at 6.706 ms, no completion marker")
    ax_long.set_xlabel("Time (ms)")
    ax_long.set_ylabel("V (V)")
    ax_long.grid(alpha=0.25)

    for ax in axes.flat:
        ax.legend(fontsize=7)

    fig.suptitle(
        "UCC24624 REG sequencing diagnostic - SIMULATION ONLY, surrogate models, not hardware validated",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(OUT / "startup_sequencing_evidence.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
