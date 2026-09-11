#!/usr/bin/env python3
"""Build the dnoise overview table straight from the chain logs, so no number is copied by hand.

Reads chain_dnoise.sh logs (arms default = MS1 only, msms = MS1 + MS2) and chain_dnoise2.sh logs (arms
control = the original .d rerun on the same node, noop = every dnoise stage off, ms2only), plus a JSON of
each dataset's recorded control searches (the pinned output's Sage, MSFragger and entrapment, which a
digest-identical rerun reproduces exactly). Missing values print as "…" so a partial run still renders.

usage: dnoise_table.py controls.json LOG [LOG ...]
       dnoise_table.py --selftest
controls.json: {"D": {"sage": 13491, "msf": 12918, "entrap": "1.30% (1.05-1.55%)"}, "TNBC009": {...}}
"""
import ast, json, re, sys

ROWS = [("control", "control, original file"), ("noop", "dnoise, every stage off"),
        ("default", "dnoise MS1 only (its default)"), ("ms2only", "dnoise MS2 only"),
        ("msms", "dnoise MS1 + MS2")]


def parse(text):
    """dataset -> arm -> fields, from every '--- DS/arm' block in a log."""
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"--- (\S+)/(\S+) ", line)
        if m:
            cur = out.setdefault(m.group(1), {}).setdefault(m.group(2), {})
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("dnoise stats "):
            cur["dn"] = ast.literal_eval(s[len("dnoise stats "):])
        elif m := re.match(r"size (\S+)\s+\S+/den\.d$", s):
            cur["size"] = m.group(1)
        # chain logs label the timed arm by its binary: spextractor before the rename to DIAspeXtractor, diaspextractor after
        elif m := re.match(r"(?:dia)?spextractor Elapsed \(wall clock\).*: ([\d:.]+)", s):
            cur["wall"] = m.group(1)
        elif m := re.match(r"(?:dia)?spextractor Maximum resident set size \(kbytes\): (\d+)", s):
            cur["peak_gb"] = int(m.group(1)) / 1e6
        elif m := re.match(r"Wrote (\d+) pseudo", s):
            cur["spectra"] = int(m.group(1))
        elif m := re.match(r"\[ms1-hist\] picked MS1 peaks (\d+)", s):
            cur["ms1_picked"] = int(m.group(1))
        elif m := re.match(r"digest (\w+)", s):
            cur["digest"] = m.group(1)
        elif "output identical to the control" in s:
            cur["identical"] = True
        elif m := re.match(r"Sage unique peptides \(rank1, q<=0\.01\): (\d+)", s):
            cur["sage"] = int(m.group(1))
        elif m := re.match(r"entrapment \S+\s+(\d+)\s+(\d+)\s+\S+\s+([\d.]+%)\s+([\d.]+-[\d.]+%)", s):
            cur["entrap"] = f"{m.group(3)} ({m.group(4)})"
        elif m := re.match(r"MSFragger: \w+ : (\d+) target peptides", s):
            cur["msf"] = int(m.group(1))
        elif m := re.match(r"peptide sets vs control: common (\d+), control-only (\d+), dnoise-only (\d+)", s):
            cur["sets"] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return out


def delta(v, base):
    if v is None or base in (None, 0):
        return "…"
    return f"{v:,} ({100.0 * (v - base) / base:+.1f}%)"


def table(ds, arms, ctrl):
    print(f"\n### {ds}\n")
    print("| configuration | MS1 points kept | all points kept | .d size | wall | peak | pseudo-spectra | picked MS1 peaks "
          "| Sage peptides | MSFragger peptides | entrapment FDR (95% CI) | Sage set vs control: common / lost / gained |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for key, label in ROWS:
        a = arms.get(key, {})
        dn = a.get("dn") or {}
        if key == "control":
            sage, msf, ent, sets = ctrl.get("sage"), ctrl.get("msf"), ctrl.get("entrap", "…"), "reference"
        elif a.get("identical"):
            sage, msf, ent, sets = ctrl.get("sage"), ctrl.get("msf"), ctrl.get("entrap", "…"), "identical output"
        else:
            sage, msf, ent = a.get("sage"), a.get("msf"), a.get("entrap", "…")
            sets = " / ".join(f"{x:,}" for x in a["sets"]) if "sets" in a else "…"
        cells = [
            label,
            f"{dn['ms1_kept_pct']:.1f}%" if "ms1_kept_pct" in dn else ("100% (original)" if key == "control" else "…"),
            f"{dn['kept_pct']:.1f}%" if "kept_pct" in dn else ("100% (original)" if key == "control" else "…"),
            a.get("size", "…"),
            a.get("wall", "…"),
            f"{a['peak_gb']:.2f} GB" if "peak_gb" in a else "…",
            f"{a['spectra']:,}" if "spectra" in a else "…",
            f"{a['ms1_picked']:,}" if "ms1_picked" in a else "…",
            f"{sage:,}" if key == "control" and sage else delta(sage, ctrl.get("sage")),
            f"{msf:,}" if key == "control" and msf else delta(msf, ctrl.get("msf")),
            ent,
            sets,
        ]
        print("| " + " | ".join(str(c) for c in cells) + " |")


SAMPLE = """--- D/default (dnoise flags: defaults) 12:24 load 11.48 ---
dnoise exit=0
  dnoise stats {'frames': 17448, 'ms1_frames': 1343, 'msms_frames': 16105, 'raw_ms1_points': 927158066, 'kept_ms1_points': 118053254, 'ms1_kept_pct': 12.73, 'raw_points': 2471762904, 'kept_points': 1662658092, 'kept_pct': 67.27}
  size 7.5G	/scratch/kohlbach/dnoise_eval/D/default/den.d
  size 9.2G	/ceph/ibmi/abi/data/2026_AGXT_PH1_liver_diaPASEF/raw_d/FKL4341.d
spextractor exit=0
  diaspextractor Elapsed (wall clock) time (h:mm:ss or m:ss): 3:06.84
  spextractor Maximum resident set size (kbytes): 21408832
  Wrote 496722 pseudo
  [ms1-hist] picked MS1 peaks 43546607 by intensity: <100 9673713 (22.2%)
  digest e43672a0d74b355a
  Sage unique peptides (rank1, q<=0.01): 12917
  entrapment peptide-hypothesis ratio = 0.6805 (1/r = 1.469)
  entrapment arm             target entrap   raw%   FDR%       FDR 95% CI
  entrapment Ddefault         12332    114  0.92%  1.36%   1.13-1.61%
  MSFragger: baseline : 12404 target peptides @1% FDR   (distinct pep+mod keys: 204006)
  peptide sets vs control: common 11590, control-only 1901, dnoise-only 1327
--- D/noop (dnoise --config ms1_off.toml ) 13:40 load 9 ---
  digest 8c1b047f3f70066c (reproduces the pin 8c1b047f)
  output identical to the control: searches would reproduce the control's (not re-run)
"""


def selftest():
    p = parse(SAMPLE)
    d = p["D"]["default"]
    assert d["dn"]["ms1_kept_pct"] == 12.73 and d["size"] == "7.5G", d
    assert d["wall"] == "3:06.84" and abs(d["peak_gb"] - 21.408832) < 1e-9 and d["spectra"] == 496722
    assert d["ms1_picked"] == 43546607 and d["sage"] == 12917 and d["msf"] == 12404
    assert d["entrap"] == "1.36% (1.13-1.61%)" and d["sets"] == (11590, 1901, 1327), d
    assert p["D"]["noop"].get("identical") is True
    assert delta(12917, 13491) == "12,917 (-4.3%)"
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest(); sys.exit()
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    controls = json.load(open(sys.argv[1]))
    merged = {}
    for path in sys.argv[2:]:
        for ds, arms in parse(open(path).read()).items():
            merged.setdefault(ds, {}).update(arms)
    for ds in merged:
        table(ds, merged[ds], controls.get(ds, {}))
