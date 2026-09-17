#!/usr/bin/env python3
"""Self-contained review brief for the 1.3.1 negative-C2 fix (kimi + vibe have no shell headless; codex gets the same
brief plus a worktree). Usage: build_brief.py <base sha> <head sha> <out.md>"""
import json, re, subprocess, sys
from pathlib import Path

DEV = Path("/Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract")
EVID = Path("/Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/output/diaweaver-comparison/pxd029836-run1-evidence/c2neg131")
SCR = Path("/private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/e4677b2f-9916-478b-9db2-706d8e88d289/scratchpad/c2neg131")
base, head, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])


def git(*a):
    return subprocess.run(["git", "-C", str(DEV), *a], capture_output=True, text=True, check=True).stdout


def show(path, lo=None, hi=None):
    """Numbered lines of a file at HEAD (the branch under review)."""
    lines = git("show", f"{head}:{path}").splitlines()
    lo = lo or 1
    hi = hi or len(lines)
    return "\n".join(f"{i:5d}| {lines[i - 1]}" for i in range(lo, min(hi, len(lines)) + 1))


def redact(s):
    # raw acquisition names can carry personal names; the run number is enough
    return re.sub(r"\(?[0-9]{8}_PRO2_[A-Za-z0-9_.]*?_(\d{4})\.d\)?", r"<run \1>", s)


stat = git("diff", "--stat", f"{base}..{head}")
diff = git("diff", f"{base}..{head}", "--", ".", ":!tests/calibration_golden.json")
gold_diff_stat = git("diff", "--stat", f"{base}..{head}", "--", "tests/calibration_golden.json")
gold = json.loads(git("show", f"{head}:tests/calibration_golden.json"))
gold_summary = []
for f in gold:
    hdr = {k: v for k, v in f.items() if k != "cases"}
    t1s = sorted({c["t1"] for c in f["cases"]})
    tofs = sorted({c["tof"] for c in f["cases"]})
    gold_summary.append(f"- {json.dumps(hdr)}\n  {len(f['cases'])} cases; frames {sorted({c['frame'] for c in f['cases']})}; "
                        f"t1 {t1s[0]:.9f}..{t1s[-1]:.9f}; tof probes {tofs}; mz {min(c['mz'] for c in f['cases']):.6f}.."
                        f"{max(c['mz'] for c in f['cases']):.6f}")
first_new = json.dumps(gold[3]["cases"][:3], indent=1)

gen = (EVID / "sdk_golden_pxd029836.py").read_text()
sdk_out = redact("\n".join(l for l in (EVID / "sdk_golden.out").read_text().splitlines()
                           if l.startswith("PXD029836") or l.startswith("removed") or l.startswith("ibminode") or l.startswith("2026")))
margins = redact((EVID / "margins.out").read_text())
calrows = "\n".join(re.sub(r"^\S+ (\S+?_(\d{4})\.d)", r"run \2", l) for l in (EVID / "calrows.out").read_text().splitlines())
mutate = (EVID / "mutate.out").read_text()
ctest = "\n".join(l for l in (SCR / "final-clang.ctest").read_text(errors="replace").splitlines()
                  if re.search(r"OK|negative|Passed|tests passed|FAIL", l))

ctx = f"""
### A. `src/TdfMzCalibration.h` at {head[:10]} (whole file; the conversion functions are unchanged except comments)
```cpp
{show("src/TdfMzCalibration.h")}
```

### B. `src/TdfLoad.h` at {head[:10]}: the axis bounds and the calibration reader (the tool's own sqlite reader)
```cpp
{show("src/TdfLoad.h", 1, 145)}
```

### C. `src/diaspextract.cpp`: the flight-time axis (every caller of mzToTof/tofToMz in the tool)
```cpp
{show("src/diaspextract.cpp", 626, 680)}
...
{show("src/diaspextract.cpp", 892, 912)}
...
{show("src/diaspextract.cpp", 1072, 1098)}
...
{show("src/diaspextract.cpp", 1236, 1266)}
...
{show("src/diaspextract.cpp", 1540, 1570)}
...
{show("src/diaspextract.cpp", 3118, 3130)}
...
{show("src/diaspextract.cpp", 3228, 3250)}
...
{show("src/diaspextract.cpp", 4098, 4126)}
```
The m/z quanta in the compact store are `uint32` at 1e-5 Da (so at most 42,949.67). `sd` in `best` is OpenMS's
robust running SD of accepted peaks, each within +-3 sd of the running centroid.

### D. `src/MzPeakStreamLoad.h`: the mzPeak exact-m/z path
```cpp
{show("src/MzPeakStreamLoad.h", 56, 162)}
```

### E. `src/DnoiseMs1.h`: the MS1 denoiser's point recovery (inverts the loader's m/z with mzToTof)
```cpp
{show("src/DnoiseMs1.h", 438, 470)}
```

### F. `patches/openms-brukertims-mz-calibration.patch` (UNCHANGED by this branch): the OpenMS loader that converts
every peak for the tool. It includes the same header (installed into the OpenMS tree by scripts/apply_openms_patches.sh
and by the deploy transaction scripts/sync_cluster.sh, which then runs `make diaspextract`, rebuilding libOpenMS).
```diff
{show("patches/openms-brukertims-mz-calibration.patch", 84, 192)}
```
"""

brief = f"""# Adversarial review: DIAspeXtract 1.3.1 accepts a negative MzCalibration C2 (branch fix/c2-negative-1.3.1)

**Review only. Do not modify, create or delete any file.** If you are running without a shell, everything you need is
inline below: do not try to run commands. If you do have a read-only shell (codex), the working directory is a git
worktree of the branch head `{head}`; the base is main `{base}` (`git diff {base[:7]}..HEAD`).
If something is fine, say so briefly rather than padding. For every finding give `file:line`, a concrete failing
input (numbers), a severity (CRITICAL/HIGH/MEDIUM/LOW) and **whether it would bite on real data or is theoretical**.

## Context

DIAspeXtract is a C++ OpenMS TOPP tool that extracts pseudo-MS/MS spectra from Bruker timsTOF diaPASEF `.d` data. Its
m/z comes from a license-free, header-only re-implementation of Bruker's TOF->m/z calibration (ModelType 1), identified
numerically against Bruker's own libtimsdata (`tims_index_to_mz`) used as a local oracle:

    t_ns   = tof * DigitizerTimebase + DigitizerDelay
    C1_eff = C1 * (1 + dC1 * (T1_ref - T1_frame) / 1e6)       # digitizer temperature, per frame
    b      = 1e6 / sqrt(C1_eff)                               # frameFactor()
    t_ns   = C0 + b * u + C2 * u^2,   u = sqrt(m + C4)          # solved for u; m = u^2 - C4

`tofToMz` uses the cancellation-free root `u = 2 (t - C0) / (b + sqrt(disc))`, `disc = b^2 - 4 C2 (C0 - t)`, and returns
NaN for `disc < 0`, `t <= C0`, `denom <= 0`, `m <= 0`. `mzToTof` is the closed-form forward law.

Until 1.3.0 `unsupportedReason()` refused every `C2 < 0` ("flips the root branch"). The public PXD029836 (timsTOF Pro 2,
acquisition software 2.0.53) stores C2 < 0 in all 23 runs (four vectors, -0.000586..-0.001228), so 1.3.0 refused them
all (exit 6, 0.03 s). A read-only SDK check showed the shipped formula with the negative C2 matches the vendor to
~6e-6 ppm; dropping C2 is 19-40 ppm off, flipping its sign 38-80 ppm off.

The fix (one commit, `{head[:10]}`): for C2 < 0, `unsupportedReason()` runs a DOMAIN check (`negativeC2Reason`): accept
only if `disc >= b^2/4` (slope dt/du >= half its linear value) for every TOF index up to `kDomainMaxTof` = 1e8, every
m/z up to `kDomainMaxMz` = 1e5, at every frame temperature within `kDomainT1Span` = 1000 K of T1_ref (checked at the
smallest b, i.e. the largest C1 factor). A new `frameReason(t1)` refuses (for C2 < 0 only) a frame whose T1 is outside
that span; the tool's sqlite reader `loadTdfCalibration` calls it per frame. The OpenMS loader patch is unchanged (it
calls `isSupported()` only; it never sees DigitizerNumSamples or a per-frame check). The conversion functions are
unchanged. New golden cases: 210 vendor values (six PXD029836 runs x 5 frames x 7 TOF probes), generated on the cluster
by the SDK script in section 5.

## Invariants the code must keep (attack these)

1. **Fail closed, never approximate.** A calibration the model does not cover must be refused, never converted with a
   plausible-looking wrong mass. NaN is acceptable only where the tool drops and counts the peak.
2. **Bit identity for every file accepted before.** Zero and positive C2 files must produce byte-identical spectra
   (four digest pins: dataset D e43672a0 / 8c1b047f, TNBC run 009 3aafd0b5 / bff54a1f). The claim is by construction:
   tofToMz/mzToTof/frameFactor unchanged, no new branch for C2 >= 0. The digest gate has NOT run yet.
3. **The golden cases must be independent of the code under test**: vendor values from `tims_index_to_mz`, never from
   the tool's formula.
4. **The shipped code is the tested code**: the same header is compiled into libOpenMS (loader patch) and the tool,
   and the C++ golden test includes it directly.
5. **The domain check must be conservative** over everything the tool can hand the model: every TOF index the loaders
   convert, every m/z the tool inverts (`mzToTof`), every frame temperature. And it must not refuse plausible real files.
6. `mzToTof` for C2 < 0 is non-monotonic beyond the parabola's vertex (m_vertex = b^2/(4 C2^2) - C4). Callers that turn
   an m/z bound into a TOF bound rely on monotonicity.

## Questions (numbered; answer each)

1. **Root choice.** Derive it: for C2 < 0 and C0 < t < C0 + b^2/(4|C2|), are both roots positive, and is
   `2(t - C0)/(b + sqrt(disc))` always the rising-branch (physical) one? Any t or b for which the code returns the other
   root, a negative u, or a finite wrong value? Is it continuous through C2 = 0 and C2 = -0.0?
2. **Domain check correctness** (`negativeC2Reason`, section A lines 145-165): are t_zero, t_half, u_half right? Is the
   deciding corner right (largest TOF, smallest b = largest C1 factor, both signs of dC1)? Is the m/z condition
   `kDomainMaxMz + C4 <= u_half^2` right, including negative or large C4? Any finite input row (C0, C4, delay,
   timebase, dC1 extremes; infinities other than C2) that the check ACCEPTS while some TOF <= 1e8 or m/z <= 1e5 at a
   T1 within the span gives disc < b^2/4, or where the refusal message computes garbage?
3. **Is the domain the right one?** The TOF bound 1e8 is enforced only by `loadTdfAxisBounds` (DigitizerNumSamples);
   the OpenMS loader converts raw uint32 TOF indices from the frame blob without a bound. The m/z bound 1e5 is
   MzAcqRangeUpper. Find every place that hands the model a TOF > 1e8 or an m/z > 1e5 (or > m_vertex), including
   `TofAxis::tofOf` callers (`best`: cmz +- 3 sd; band edges `acq_hi`, `mzOf(last)+1e-5`; `c.tof = tofOf(amz)`), the
   mzPeak path, dnoise `recoverPoint`, the patch's `inverse_convert`. For each, would a non-monotonic `mzToTof` or an
   ill-conditioned root change output on a real negative-C2 file?
4. **Temperature.** `frameReason` checks |T1 - T1_ref| <= 1000 K; the domain check assumes that bound. Can a frame reach
   `frameFactor` with an unchecked T1 in any path of the tool (OpenMS loader, TofAxis fallback `factor()`,
   `setTofAxis`'s `f > 0 ? f : bref`, mzPeak `exact()`)? Is the floating-point comparison consistent with `cf_hi`?
   Is 1000 K sensible (never refuses a real file, still meaningful)?
5. **Bit identity for C2 >= 0.** Check every changed line: the reordered timebase check, `frameReason` in the Frames loop,
   `kDomainMaxTof`/`kDomainMaxMz` replacing literals, the new `#include <cstdio>`, the `private:` section and
   `static constexpr` members (aggregate-ness, layout, ODR / C++ standard version), the per-frame std::string. Can any
   of them change a single output byte or a refusal for a zero/positive-C2 file? Anything about a mixed deploy
   (libOpenMS built with the old header, the tool with the new one)?
6. **Golden cases.** Are the 210 new cases really vendor values (section 5 generator)? Are they sufficient (T1 spread
   0.004-0.011 K per run, 7 TOF probes incl. N-1, four calibration vectors)? Note the golden JSON has no `C4` key; the
   parsers assume C4 = 0 for every golden file (PXD029836 has C4 = 0 per section 5). Is any assertion in the C++/Python
   tests vacuous, too loose, or dependent on the header it tests (e.g. `g6` mirroring `num`, the `c2_edge` formula)?
7. **Anything else assuming C2 >= 0** in the code shown (comments, docs, CHANGELOG, README, tests, provenance line)?
8. **CHANGELOG accuracy** (section 2 diff): check every number and claim against the evidence in sections 3-4 and the
   code. In particular "the four pins reproduce" is stated before the digest gate ran.
9. **What would you add or change before this ships as 1.3.1?** Rank.

## 1. Branch diff (stat)
```
{stat}
```
`tests/calibration_golden.json`: {gold_diff_stat.strip()} (210 cases appended; summary in section 4, not inlined)

## 2. Full diff except the golden JSON (`git diff {base[:10]}..{head[:10]}`)
```diff
{diff}
```

## 3. Evidence

### 3a. SDK golden generator output (ibminode05, libtimsdata 2.21.0.4; one line per run)
```
{sdk_out}
```

### 3b. Discriminant margins from the laptop tdf copies (runs 1418/1420/1422)
```
{margins}
```

### 3c. Calibration rows of all 23 PXD029836 runs (`MzCalibration` referenced by the frames)
```
{calrows}
```

### 3d. Mutation proof (each mutation applied alone to the header/reader; which test suites catch it)
```
{mutate}
```

### 3e. Local ctest on the branch (AppleClang 21; GCC 16 prints the same numbers)
```
{ctest}
```

## 4. Golden JSON after the change (9 files; the first 3 predate the branch)
{chr(10).join(gold_summary)}

First three new cases (PXD029836 1418):
```json
{first_new}
```

## 5. The SDK golden generator (`sdk_golden_pxd029836.py`, run on the cluster; not in the repo)
```python
{gen}
```

## 6. Code context (unchanged or changed, at the branch head)
{ctx}
"""
out.write_text(brief)
print(out, len(brief), "bytes")
