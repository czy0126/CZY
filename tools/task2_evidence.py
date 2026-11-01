"""Plot the Task 2 CT evidence from the actual LTspice RAW files.

SIMULATION ONLY - behavioural UCC25600/UCC27282/SR surrogates, not hardware.
Four panels:

  a) 0-130 us       : GD2-first gate order and bootstrap capacitor voltage (driver model)
  b) 0-7 ms         : cold-start output trajectory vs SS and OC
  c) 3.90-4.10 ms   : 1 mOhm short -> OC trip, gate shutdown, peak current
  d) 3.94-4.06 ms   : OC pin voltage for the three sensing time constants

Usage: python tools/task2_evidence.py
"""

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PyLTSpice import RawRead  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "design" / "v2" / "task2_ct_evidence.png"


def load(name: str, traces: list[str]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return time and the requested traces from <name>.raw."""
    raw = RawRead(str(ROOT / "sim" / "v2" / f"{name}.raw"))
    t = np.asarray(raw.get_trace("time").get_wave(0))
    return t, {tr: np.asarray(raw.get_trace(tr).get_wave(0)) for tr in traces}


def thin(t: np.ndarray, y: np.ndarray, n: int = 4000) -> tuple[np.ndarray, np.ndarray]:
    """Decimate to at most n points so plotting stays fast."""
    step = max(1, len(t) // n)
    return t[::step], y[::step]


def panel_bootstrap(ax: plt.Axes) -> None:
    # Driver-integrated deck: real UCC27282 behavioural model.  HO is HS-referenced,
    # so the gate waveform is V(ho,sw), not V(ho) to ground (that adds V(sw)).
    t, tr = load("startup_ct_drv_long", ["V(lo)", "V(ho)", "V(hb)", "V(sw)"])
    m = t <= 130e-6
    ax.plot(t[m] * 1e6, tr["V(lo)"][m], label="LO gate (first edge 70.80 us)")
    ax.plot(t[m] * 1e6, (tr["V(ho)"] - tr["V(sw)"])[m], label="HO gate vs HS (first 72.52 us)")
    ax.plot(t[m] * 1e6, (tr["V(hb)"] - tr["V(sw)"])[m], "--", label="VBoot = V(hb,sw)")
    ax.axhline(3.7, color="tab:red", lw=0.7, ls=":")
    ax.set_title("a) pre-start Cboot charging + first 10 cycles (~200 kHz)")
    ax.set_xlabel("t (us)")
    ax.set_ylabel("V (V)")


def panel_long(ax: plt.Axes) -> None:
    t, tr = load("startup_ct_drv_long", ["V(out)", "V(ss)", "V(oc)"])
    tl, out = thin(t, tr["V(out)"])
    ax.plot(tl * 1e3, out, label="Vout")
    ax.plot(t * 1e3, tr["V(ss)"], label="V(ss)")
    ax.plot(t * 1e3, tr["V(oc)"], label="V(oc) sense")
    ax.axhline(1.0, color="tab:red", lw=0.7, ls=":")
    ax.set_title("b) 7 ms cold start, UCC27282 driver, uic (no precharge)")
    ax.set_xlabel("t (ms)")
    ax.set_ylabel("V (V)")


def panel_fault(ax: plt.Axes) -> None:
    t, tr = load("startup_ct_fault_drv", ["V(oc)", "I(Lr)", "V(gl)"])
    m = (t >= 3.90e-3) & (t <= 4.10e-3)
    ax.plot(t[m] * 1e3, tr["I(Lr)"][m], label="I(Lr)")
    ax2 = ax.twinx()
    ax2.plot(t[m] * 1e3, tr["V(oc)"][m], color="tab:red", label="V(oc) (V)")
    ax2.plot(t[m] * 1e3, tr["V(gl)"][m] / 12.0, color="tab:green", label="V(gl)/12")
    ax2.axhline(1.0, color="tab:red", lw=0.7, ls=":")
    ax2.set_ylim(0, 1.4)
    ax.axvline(3.95, color="0.4", lw=0.7, ls="--")
    ax.set_title("c) 1 mOhm short at 3.95 ms, driver deck: trip 4.0013 ms")
    ax.set_xlabel("t (ms)")
    ax.set_ylabel("I(Lr) (A)")
    ax2.set_ylabel("V(oc) (V) / V(gl)/12")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper right")


def panel_variants(ax: plt.Axes) -> None:
    for name, label in [
        ("startup_ct_fault", "Cf 47n / Coc 10n: 51.3 us"),
        ("startup_ct_fault_f10", "Cf 10n / Coc 10n: 30.2 us"),
        ("startup_ct_fault_f10_c1", "Cf 10n / Coc 1n: 13.0 us"),
    ]:
        t, tr = load(name, ["V(oc)"])
        m = (t >= 3.94e-3) & (t <= 4.06e-3)
        ax.plot(t[m] * 1e3, tr["V(oc)"][m], label=label)
    ax.axhline(1.0, color="tab:red", lw=0.7, ls=":")
    ax.axvline(3.95, color="0.4", lw=0.7, ls="--")
    ax.set_title("d) OC pin network sets the delay, not the CT filter")
    ax.set_xlabel("t (ms)")
    ax.set_ylabel("V(oc) (V)")


def restart_figure() -> None:
    """Full shutdown (bus + aux off 4.5-6.1 ms) and restart."""
    t, tr = load("startup_ct_restart_drv", ["V(out)", "V(ss)", "V(oc)", "V(gl)", "I(Lr)"])
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.2))
    tl, out = thin(t, tr["V(out)"])
    ax.plot(tl * 1e3, out, label="Vout")
    ax.plot(t * 1e3, tr["V(ss)"], label="V(ss)")
    ax.axvspan(4.5, 6.1, color="tab:red", alpha=0.10, label="bus + aux removed")
    ax.set_title("full shutdown and restart")
    ax.set_xlabel("t (ms)")
    ax.set_ylabel("V (V)")

    m = (t >= 4.40e-3) & (t <= 7.20e-3)
    ax2.axvspan(4.6, 6.1, color="tab:red", alpha=0.10)
    ax2.plot(t[m] * 1e3, tr["I(Lr)"][m], label="I(Lr)")
    ax2b = ax2.twinx()
    ax2b.plot(t[m] * 1e3, tr["V(oc)"][m], color="tab:red", label="V(oc)")
    ax2b.plot(t[m] * 1e3, tr["V(gl)"][m] / 12.0, color="tab:green", label="V(gl)/12")
    ax2b.set_ylim(0, 1.4)
    ax2b.set_ylabel("V(oc) (V) / V(gl)/12")
    ax2.set_title("driver deck: outputs off, restart at 6.1 ms (LO 6151.2 us)")
    ax2.set_xlabel("t (ms)")
    ax2.set_ylabel("I(Lr) (A)")
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax2b.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left")
    for axis in (ax, ax2):
        axis.grid(alpha=0.25)
        axis.legend(fontsize=7)
    fig.suptitle("Task 2 restart - SIMULATION ONLY, surrogate models, not hardware validated", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT.with_name("task2_restart_evidence.png"), dpi=160)
    plt.close(fig)
    print(f"wrote {OUT.with_name('task2_restart_evidence.png')}")


def surge_comparison() -> None:
    """Css 10n vs 50n: the startup peak is set by the first-cycle tank inrush."""
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.2))
    for name, label, color in [
        ("startup_ct_drv", "Css = 10 nF (first GD2 70.8 us)", "tab:blue"),
        ("startup_ct_drv_css50", "Css = 50 nF (first GD2 344.8 us)", "tab:orange"),
    ]:
        t, tr = load(name, ["I(Lr)", "V(ss)"])
        m = t <= 0.6e-3
        ax.plot(t[m] * 1e3, np.abs(tr["I(Lr)"][m]), color=color, lw=0.8, label=label)
    ax.axhline(36.0, color="0.4", lw=0.7, ls=":")
    ax.set_title("a) 5x softer soft start leaves the peak unchanged")
    ax.set_xlabel("t (ms)")
    ax.set_ylabel("|I(Lr)| (A)")

    for name, label, color in [
        ("startup_ct_drv", "SS, Css 10 nF", "tab:blue"),
        ("startup_ct_drv_css50", "SS, Css 50 nF", "tab:orange"),
    ]:
        t, tr = load(name, ["V(ss)"])
        m = t <= 0.6e-3
        ax2.plot(t[m] * 1e3, tr["V(ss)"][m], color=color, label=label)
    ax2.axhline(1.2, color="tab:red", lw=0.7, ls=":")
    ax2.set_title("b) SS crosses the 1.2 V enable at 68.6 us / 343 us")
    ax2.set_xlabel("t (ms)")
    ax2.set_ylabel("V(ss) (V)")
    for a in (ax, ax2):
        a.grid(alpha=0.25)
        a.legend(fontsize=7)
    fig.suptitle("Task 2 startup-surge single-parameter test - SIMULATION ONLY", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT.with_name("task2_css_surge.png"), dpi=160)
    plt.close(fig)
    print(f"wrote {OUT.with_name('task2_css_surge.png')}")


def main() -> None:
    restart_figure()
    surge_comparison()
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5))
    panel_bootstrap(axes[0, 0])
    panel_long(axes[0, 1])
    panel_fault(axes[1, 0])
    panel_variants(axes[1, 1])
    for ax in axes.flat:
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7)
    fig.suptitle("Task 2: real-CT startup and OC response - SIMULATION ONLY, surrogate models, not hardware validated", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT, dpi=160)
    plt.close(fig)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
