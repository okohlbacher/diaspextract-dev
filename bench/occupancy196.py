#!/usr/bin/env python3
"""occupancy196.py PROFDIR OUTPREFIX: occupancy, memory-pressure and contention per phase for the prof196 runs.
Each run dir holds proc.tsv/threads.tsv/clock.txt (procsample.py), vm.tsv (system /proc/meminfo+vmstat, 1 s) and
run.log with DIASPEXTRACT_PHASE_TRACE lines "[phase] B|E <name> <CLOCK_MONOTONIC s> <depth>"."""
import sys, os, re
import pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt

RUNS = ["v190_t64", "perf_t64", "v190_t16", "perf_t16"]
LABEL = {"v190": "v1.9.0", "perf": "perf-196"}

def load(d):
    t0 = float(dict(l.split("\t") for l in open(f"{d}/clock.txt").read().split("\n") if l)["monotonic_t0"])
    p = pd.read_csv(f"{d}/proc.tsv", sep="\t", na_values="NA")
    vm = pd.read_csv(f"{d}/vm.tsv", sep="\t"); vm["t"] -= t0
    ph = []   # "[phase] X <name> <begin> <end> <nested>" from phaseAdd_ (every phase, top-level and enclosed)
    for l in open(f"{d}/run.log", errors="replace"):
        m = re.match(r"\[phase\] X (.+) ([0-9.]+) ([0-9.]+) ([01])$", l.strip())
        if m: ph.append((m.group(1), float(m.group(2)) - t0, float(m.group(3)) - t0, int(m.group(4))))
    ph = pd.DataFrame(ph, columns=["phase", "b", "e", "depth"]).sort_values("b")
    ph.loc[ph.phase == "LOAD(stream)", "b"] = ph.loc[ph.phase == "LOAD(stream)", "b"].clip(lower=0)
    # per-sample rates
    dt = p["t"].diff()
    for c in ["minflt", "majflt", "vcsw", "ivcsw", "stime_s", "utime_s"]:
        p[f"r_{c}"] = p[c].diff() / dt
    p["sys_frac"] = p["r_stime_s"] / (p["r_stime_s"] + p["r_utime_s"])
    for c in ["pgmajfault", "pswpin", "pswpout", "pgscan_direct", "allocstall_normal", "compact_stall"]:
        if c in vm: vm[f"r_{c}"] = vm[c].diff() / vm["t"].diff()
    return p, vm, ph

def phase_table(p, ph):
    rows = []
    top = ph[ph.depth == 0]
    for _, r in top.iterrows():
        s = p[(p.t >= r.b) & (p.t < r.e)]
        rows.append(dict(phase=r.phase, start=round(r.b, 1), wall=round(r.e - r.b, 1),
                         cores=round(s.active_cores.mean(), 1), cores_p10=round(s.active_cores.quantile(.1), 1),
                         sys_pct=round(100 * s.sys_frac.mean(), 1), minflt_k_s=round(s.r_minflt.mean() / 1e3, 1),
                         majflt=int((s.majflt.max() - s.majflt.min()) if len(s) else 0),
                         vcsw_k_s=round(s.r_vcsw.mean() / 1e3, 1), ivcsw_k_s=round(s.r_ivcsw.mean() / 1e3, 2),
                         rss_gb_max=round(s.rss_kb.max() / 2**20, 2)))
    # enclosed phases summed
    for n, g in ph[ph.depth > 0].groupby("phase"):
        rows.append(dict(phase=f"  {n} (enclosed, n={len(g)})", wall=round((g.e - g.b).sum(), 1)))
    return pd.DataFrame(rows)

def main(prof, out):
    data = {r: load(f"{prof}/{r}") for r in RUNS if os.path.exists(f"{prof}/{r}/proc.tsv")}
    cols = plt.get_cmap("tab10")
    fig, axes = plt.subplots(len(data), 1, figsize=(13, 3.3 * len(data)), squeeze=False)
    for ax, (r, (p, vm, ph)) in zip(axes[:, 0], data.items()):
        arm, t = r.split("_t"); top = ph[ph.depth == 0]
        for i, (_, x) in enumerate(top.iterrows()):
            ax.axvspan(x.b, x.e, color=cols(i % 10), alpha=.12, lw=0)
            ax.text((x.b + x.e) / 2, int(t) * 1.02, x.phase.replace("(", "\n("), ha="center", va="bottom", fontsize=6.5)
        # nested tile reads as ticks
        for _, x in ph[(ph.depth > 0) & ph.phase.str.startswith("LOAD")].iterrows():
            ax.plot([x.b, x.e], [-1.5, -1.5], color="k", lw=2, solid_capstyle="butt")
        ax.plot(p.t, p.active_cores, lw=.6, color="C0", label="busy cores")
        ax.plot(p.t, p.n_running, lw=.4, color="C2", alpha=.6, label="threads in R")
        ax.axhline(int(t), color="grey", ls=":", lw=.8)
        a2 = ax.twinx(); a2.plot(p.t, p.rss_kb / 2**20, color="C3", lw=.9, label="RSS GB"); a2.set_ylabel("RSS (GB)", color="C3")
        ax.set_ylim(-3, int(t) * 1.25); ax.set_ylabel("cores")
        ax.set_title(f"{LABEL[arm]}, {t} threads: {p.t.max():.0f} s; black ticks under the axis = tile reads", fontsize=9, loc="left")
        ax.legend(loc="lower left", fontsize=7); ax.set_xlim(0, p.t.max())
    axes[-1, 0].set_xlabel("wall time (s)"); fig.tight_layout(); fig.savefig(f"{out}-occupancy.png", dpi=130)

    fig, axes = plt.subplots(len(data), 1, figsize=(13, 2.6 * len(data)), squeeze=False)
    for ax, (r, (p, vm, ph)) in zip(axes[:, 0], data.items()):
        ax.plot(p.t, p.r_minflt / 1e3, lw=.6, label="minor faults (k/s)")
        ax.plot(p.t, p.r_vcsw / 1e3, lw=.6, label="voluntary csw (k/s)")
        ax.plot(p.t, p.r_ivcsw / 1e3, lw=.6, label="involuntary csw (k/s)")
        ax.plot(p.t, 100 * p.sys_frac, lw=.6, label="system time (%)")
        ax.plot(vm.t, vm.get("r_pgmajfault", 0), lw=.8, ls="--", label="major faults/s (system)")
        ax.set_yscale("symlog", linthresh=1); ax.set_title(f"{r}: faults, context switches, system share; "
            f"MemAvailable min {vm.mem_avail_mb.min()/1024:.0f} GB, swap used max {vm.swap_used_mb.max()} MB", fontsize=9, loc="left")
        ax.legend(fontsize=6.5, ncol=5, loc="upper right"); ax.set_xlim(0, p.t.max())
    fig.tight_layout(); fig.savefig(f"{out}-pressure.png", dpi=130)

    with open(f"{out}-phases.md", "w") as f:
        for r, (p, vm, ph) in data.items():
            f.write(f"\n### {r}\n\n" + phase_table(p, ph).to_string(index=False) + "\n")
            sw = {c: int(vm[c].iloc[-1] - vm[c].iloc[0]) for c in ["pgmajfault", "pswpin", "pswpout", "pgscan_direct",
                  "allocstall_normal", "compact_stall", "thp_fault_alloc", "thp_fault_fallback", "numa_miss"] if c in vm}
            f.write(f"\nsystem during run: MemAvailable min {vm.mem_avail_mb.min()/1024:.0f} GB, swap used max "
                    f"{vm.swap_used_mb.max()} MB, deltas {sw}\n")
    print(open(f"{out}-phases.md").read())

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
